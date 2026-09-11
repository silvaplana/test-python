"""Point d'entree unique du backend : assemble les differents modules
(helloasso, ffst, ...) sur une seule app FastAPI / un seul service HTTP.

N'appartient a aucun des modules qu'il assemble (voir DEPLOY.md :
un seul conteneur "backend" pour tout le projet).
"""

import asyncio
import os

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ffst import Ffst, FfstReceiver
from financialbalance import FinancialBalance, FinancialBalanceReceiver
from helloasso import HelloAsso, HelloAssoReceiver
from members_history import MembersHistory, MembersHistoryReceiver
from notifications import NotificationsReceiver, PushNotifications

load_dotenv()  # charge backend/.env si present (variables HELLOASSO_*)

# instance FastAPI exposee pour uvicorn / TestClient, partagee par tous
# les modules montes ci-dessous.
app = FastAPI(title="samboAdmin API")
app.add_middleware(
    # Autorise le frontend React (Vite, servi sur un autre port) a appeler l'API.
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Monte les routes HelloAsso (/helloasso/members, /helloasso/unpaid) sur la
# meme app : un seul service HTTP pour tout le backend (voir DEPLOY.md).
helloasso_client = HelloAsso(
    client_id=os.environ.get("HELLOASSO_CLIENT_ID", ""),
    client_secret=os.environ.get("HELLOASSO_CLIENT_SECRET", ""),
    organization_slug=os.environ.get("HELLOASSO_ORGANIZATION_SLUG"),
    sandbox=os.environ.get("HELLOASSO_SANDBOX", "").lower() in ("1", "true", "yes"),
)
helloasso_receiver = HelloAssoReceiver(
    client=helloasso_client,
    app=app,
    # Slug HelloAsso genere lors de la creation du formulaire, qui ne suit
    # pas forcement le titre affiche : ce formulaire est titre "saison
    # 2026-2027" mais garde le slug de l'annee precedente (suffixe "-2-2"
    # ajoute par HelloAsso pour eviter un doublon de slug).
    form_slug=os.environ.get(
        "HELLOASSO_FORM_SLUG", "rejoignez-notre-club-de-sambo-mma-pour-la-saison-2025-2026-2-2"
    ),
)

# Monte les routes FFST (/ffst/licences) sur la meme app.
ffst_client = Ffst(
    user_part1=os.environ.get("FFST_USER_PART1", ""),
    user_part2=os.environ.get("FFST_USER_PART2", ""),
    user_part3=os.environ.get("FFST_USER_PART3", ""),
    password=os.environ.get("FFST_PASSWORD", ""),
)
ffst_receiver = FfstReceiver(client=ffst_client, app=app)

# Monte les routes du bilan financier (/financialbalance/archives) sur la
# meme app. storage_dir doit pointer vers un repertoire persistant (volume
# Docker, voir docker-compose.yml) sous peine de perdre les archives
# recues au prochain redeploiement.
financialbalance_client = FinancialBalance(
    storage_dir=os.environ.get("FINANCIALBALANCE_STORAGE_DIR", "data/bank_archives"),
)
financialbalance_receiver = FinancialBalanceReceiver(client=financialbalance_client, app=app)

# Monte les routes de l'historique des adherents (/members_history) sur la
# meme app. Aucune config requise : lit un fichier xlsx embarque dans le
# backend (voir members_history/members_history.py), pas une API externe.
members_history_client = MembersHistory()
members_history_receiver = MembersHistoryReceiver(client=members_history_client, app=app)

# Monte les routes de notifications push (/notifications/...) sur la meme
# app. storage_dir doit pointer vers un repertoire persistant (volume
# Docker) : meme necessite que financialbalance_client ci-dessus, sous
# peine de perdre tous les abonnements (et de renotifier tous les
# adherents existants comme "nouveaux") a chaque redeploiement. Cles
# VAPID generees une fois (voir README) et fixes pour la duree de vie du
# club : les regenerer invaliderait tous les abonnements existants
# (chaque utilisateur devrait refaire "Activer les notifications").
notifications_client = PushNotifications(
    storage_dir=os.environ.get("NOTIFICATIONS_STORAGE_DIR", "data/notifications"),
    vapid_private_key=os.environ.get("VAPID_PRIVATE_KEY", ""),
    vapid_public_key=os.environ.get("VAPID_PUBLIC_KEY", ""),
    vapid_subject=os.environ.get("VAPID_SUBJECT", "mailto:contact@example.com"),
)
notifications_receiver = NotificationsReceiver(client=notifications_client, app=app)

# Intervalle de verification des nouveaux adherents HelloAsso (polling,
# voir notifications/notifications.py:check_for_new_members) -- pas de
# webhook HelloAsso : ca eviterait le polling mais demanderait de
# configurer une URL sur le tableau de bord HelloAsso (compte du club,
# hors de portee de ce backend). 5 minutes par defaut : assez reactif
# pour une notification "quasi temps reel" sans solliciter l'API
# HelloAsso trop souvent.
NOTIFICATIONS_POLL_INTERVAL_SECONDS = int(os.environ.get("NOTIFICATIONS_POLL_INTERVAL_SECONDS", "300"))


async def _poll_new_members() -> None:
    """Boucle de fond (lancee au demarrage, voir _start_polling) :
    interroge HelloAsso toutes les NOTIFICATIONS_POLL_INTERVAL_SECONDS et
    notifie les abonnes de tout nouvel adherent. Ne s'arrete jamais sur
    erreur (ex: HelloAsso temporairement indisponible) : reessaie
    simplement au prochain tour."""
    while True:
        try:
            members = await asyncio.to_thread(
                helloasso_client.get_members,
                helloasso_receiver.form_slug,
                helloasso_receiver.form_type,
            )
            for member in notifications_client.check_for_new_members(members):
                name = f"{member.get('firstName') or ''} {member.get('lastName') or ''}".strip()
                notifications_client.send_push_to_all(
                    title="Nouvel adhérent",
                    body=(
                        f"{name} vient de s'inscrire sur HelloAsso"
                        if name
                        else "Un nouvel adhérent vient de s'inscrire sur HelloAsso"
                    ),
                    # Resolu par le service worker relativement a son
                    # propre scope (voir sw.js) : reste correct quel que
                    # soit le chemin de base (dev vs /sambo-admin/ en
                    # prod), que ce backend ne connait pas.
                    url=".",
                )
        except Exception as exc:
            print(f"_poll_new_members: erreur ({exc})")
        await asyncio.sleep(NOTIFICATIONS_POLL_INTERVAL_SECONDS)


@app.on_event("startup")
async def _start_polling() -> None:
    asyncio.create_task(_poll_new_members())


def main() -> None:
    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
