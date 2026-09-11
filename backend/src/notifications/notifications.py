"""Notifications push (Web Push standard, RFC 8030 + VAPID) pour prevenir
en temps quasi-reel d'un nouvel adherent HelloAsso, meme telephone
verrouille / onglet ferme.

Fonctionnement : un navigateur qui active les notifications (onglet
Profil du frontend) cree un "abonnement" aupres de son propre service de
push (FCM pour Chrome/Edge/Android, service Apple pour Safari/iOS, ...),
transmis a ce backend et stocke ici (voir add_subscription). Envoyer une
notification = chiffrer un message et le poster sur l'endpoint de chaque
abonnement, signe avec la paire de cles VAPID du club (voir
VAPID_PRIVATE_KEY/VAPID_PUBLIC_KEY, .env.example) : c'est cette signature
qui identifie ce backend aupres des services de push sans avoir besoin de
s'enregistrer individuellement chez chacun (Google, Apple, Mozilla...).

Detection des nouveaux adherents : voir check_for_new_members(), appelee
periodiquement par un thread de fond (app/main.py) qui interroge
HelloAsso.get_members() -- polling plutot que webhook HelloAsso, pour ne
demander aucune configuration supplementaire sur le tableau de bord
HelloAsso (compte du club, pas accessible a ce backend).
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from pywebpush import WebPushException, webpush


class PushNotifications:
    """Stocke les abonnements push + l'etat "derniers adherents connus",
    et sait envoyer une notification a tous les abonnes.

    Stockage en fichiers JSON (pas de base de donnees pour ce volume de
    donnees, meme pattern que financialbalance) dans storage_dir, qui
    doit pointer vers un repertoire persistant (volume Docker) sous peine
    de tout reoublier -- et donc renotifier tous les adherents existants
    -- a chaque redeploiement.
    """

    def __init__(
        self,
        storage_dir: Path | str,
        vapid_private_key: str,
        vapid_public_key: str,
        vapid_subject: str,
    ) -> None:
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.subscriptions_path = self.storage_dir / "subscriptions.json"
        self.known_member_ids_path = self.storage_dir / "known_member_ids.json"
        self.vapid_private_key = vapid_private_key
        self.vapid_public_key = vapid_public_key
        self.vapid_subject = vapid_subject
        # Un seul verrou pour les 2 fichiers : usage largement sequentiel
        # (polling toutes les quelques minutes, quelques requetes
        # d'abonnement par saison), pas besoin de plus fin.
        self._lock = threading.Lock()

    def get_public_key(self) -> str:
        """Cle publique VAPID (base64url) : le frontend en a besoin pour
        PushManager.subscribe({applicationServerKey: ...})."""
        return self.vapid_public_key

    def _load_json(self, path: Path, default):
        if not path.exists():
            return default
        return json.loads(path.read_text())

    def _save_json(self, path: Path, data) -> None:
        path.write_text(json.dumps(data))

    def add_subscription(self, subscription: dict) -> None:
        """Enregistre un abonnement push (subscription.toJSON() cote
        navigateur : {endpoint, keys: {p256dh, auth}, ...}). Idempotent :
        remplace un abonnement existant de meme endpoint (un navigateur
        qui se reabonne, ex: apres avoir coupe puis reactive)."""
        with self._lock:
            subs = self._load_json(self.subscriptions_path, [])
            subs = [s for s in subs if s.get("endpoint") != subscription.get("endpoint")]
            subs.append(subscription)
            self._save_json(self.subscriptions_path, subs)
        print("PushNotifications.add_subscription: abonnement enregistre")

    def remove_subscription(self, endpoint: str) -> None:
        with self._lock:
            subs = self._load_json(self.subscriptions_path, [])
            subs = [s for s in subs if s.get("endpoint") != endpoint]
            self._save_json(self.subscriptions_path, subs)
        print("PushNotifications.remove_subscription: abonnement retire")

    def check_for_new_members(self, members: list[dict]) -> list[dict]:
        """Compare les ids HelloAsso des adherents actuels a ceux deja
        connus (persistes), met a jour la liste persistee, et retourne
        les adherents jamais vus jusqu'ici (a notifier).

        Premiere execution (fichier absent, ex: tout juste deploye) :
        memorise l'etat actuel sans rien remonter comme "nouveau" --
        sinon tous les adherents existants declencheraient une
        notification au demarrage.
        """
        with self._lock:
            known = self._load_json(self.known_member_ids_path, None)
            first_run = known is None
            known_ids = set(known or [])
            current_ids = {m["id"] for m in members if m.get("id") is not None}
            new_ids = current_ids - known_ids
            self._save_json(self.known_member_ids_path, sorted(known_ids | current_ids))
        if first_run:
            print(f"PushNotifications.check_for_new_members: 1ere execution, {len(current_ids)} adherent(s) memorise(s)")
            return []
        if new_ids:
            print(f"PushNotifications.check_for_new_members: {len(new_ids)} nouvel(aux) adherent(s)")
        return [m for m in members if m.get("id") in new_ids]

    def send_push_to_all(self, title: str, body: str, url: str) -> None:
        """Envoie une notification push a tous les abonnes. Retire
        automatiquement les abonnements expires/revoques (le service de
        push repond alors 404/410, cas normal -- ex: l'utilisateur a
        desinstalle l'appli ou change de telephone) sans faire echouer
        l'envoi aux autres abonnes."""
        subs = self._load_json(self.subscriptions_path, [])
        if not subs:
            return
        payload = json.dumps({"title": title, "body": body, "url": url})
        still_valid = []
        for sub in subs:
            try:
                webpush(
                    subscription_info=sub,
                    data=payload,
                    vapid_private_key=self.vapid_private_key,
                    vapid_claims={"sub": self.vapid_subject},
                )
                still_valid.append(sub)
            except WebPushException as exc:
                status = exc.status_code
                if status in (404, 410):
                    print(f"PushNotifications.send_push_to_all: abonnement expire, retire ({exc})")
                    continue
                print(f"PushNotifications.send_push_to_all: echec d'envoi a un abonnement ({exc})")
                still_valid.append(sub)  # erreur transitoire (ex: reseau) : on le garde
            except Exception as exc:
                # Pas seulement WebPushException : une erreur reseau brute
                # (endpoint injoignable, DNS...) remonterait sinon non
                # capturee et interromprait l'envoi aux abonnes suivants.
                print(f"PushNotifications.send_push_to_all: erreur inattendue sur un abonnement ({exc})")
                still_valid.append(sub)
        if len(still_valid) != len(subs):
            self._save_json(self.subscriptions_path, still_valid)
        print(f"PushNotifications.send_push_to_all: notification envoyee a {len(still_valid)} abonne(s)")
