"""Point d'entree unique du backend : assemble les differents modules
(helloasso, ffst, ...) sur une seule app FastAPI / un seul service HTTP.

N'appartient a aucun des modules qu'il assemble (voir DEPLOY.md :
un seul conteneur "backend" pour tout le projet).
"""

import asyncio
import os

import uvicorn
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from auth import AuthReceiver, require_accounts_auth, require_auth
from bankaccounts import BankAccounts, BankAccountsReceiver, EnableBankingClient
from database import Database
from ffst import Ffst, FfstReceiver
from financialbalance import FinancialBalance, FinancialBalanceReceiver
from helloasso import HelloAsso, HelloAssoReceiver
from mailer import Mailer
from members_history import MembersHistory, MembersHistoryReceiver
from notifications import NotificationsReceiver, PushNotifications
from trials import Trials, TrialsPublicReceiver, TrialsReceiver

load_dotenv()  # charge backend/.env si present (variables HELLOASSO_*)

# instance FastAPI exposee pour uvicorn / TestClient, partagee par tous
# les modules montes ci-dessous.
app = FastAPI(title="samboAdmin API")
app.add_middleware(
    # Autorise le frontend React (Vite, servi sur un autre port en dev
    # local -- meme origine en prod via le gateway, ce middleware n'y
    # entre pas en jeu) a appeler l'API. allow_credentials=True + une
    # origine precise (pas de wildcard, incompatible avec les
    # identifiants) : necessaire pour que le cookie de session (voir
    # module auth) soit envoye/accepte sur ces requetes cross-origin en
    # dev.
    CORSMiddleware,
    allow_origin_regex=r"http://localhost:\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes d'authentification (/auth/login, /auth/logout, /auth/status) :
# montees directement sur l'app, jamais sur protected_router plus bas --
# il faut pouvoir les appeler justement quand on n'est pas encore
# authentifie (notamment /auth/login, sous peine de ne jamais pouvoir se
# connecter).
auth_receiver = AuthReceiver(app=app)

# Toutes les autres routes de ce backend passent par ce routeur plutot
# que par l'app directement : Depends(require_auth) s'applique alors a
# chacune d'elles sans avoir a le repeter route par route. Inclus dans
# l'app (app.include_router plus bas) une fois que tous les modules
# ci-dessous y ont enregistre leurs routes -- voir require_auth pour la
# doc complete de la dependance, et sa docstring/celle du module auth
# pour ce que "sauf les fichiers statiques" (mentionne dans la demande
# initiale) signifie concretement dans cette architecture (le frontend,
# qui sert ses fichiers statiques lui-meme, hors de portee de ce
# backend -- voir DEPLOY.md).
protected_router = APIRouter(dependencies=[Depends(require_auth)])

# Monte les routes HelloAsso (/helloasso/members, /helloasso/unpaid) sur la
# meme app : un seul service HTTP pour tout le backend (voir DEPLOY.md).
helloasso_client = HelloAsso(
    client_id=os.environ.get("HELLOASSO_CLIENT_ID", ""),
    client_secret=os.environ.get("HELLOASSO_CLIENT_SECRET", ""),
    organization_slug=os.environ.get("HELLOASSO_ORGANIZATION_SLUG"),
    sandbox=os.environ.get("HELLOASSO_SANDBOX", "").lower() in ("1", "true", "yes"),
    # Cache disque des vignettes de photo d'adherent (voir
    # HelloAsso.get_photo_thumbnail) : doit pointer vers un repertoire
    # persistant (volume Docker, meme necessite que
    # financialbalance_client/notifications_client plus bas) sous peine
    # de re-telecharger+redimensionner la photo d'origine (jusqu'a
    # plusieurs Mo) de chaque adherent a chaque redeploiement.
    photo_cache_dir=os.environ.get("HELLOASSO_PHOTO_CACHE_DIR", "data/photos_cache"),
)
helloasso_receiver = HelloAssoReceiver(
    client=helloasso_client,
    app=protected_router,
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
ffst_receiver = FfstReceiver(client=ffst_client, app=protected_router)

# Base de donnees SQLite de l'appli (voir database/database.py) : fichier
# dans le volume Docker (/app/data), meme necessite de persistance que
# financialbalance_client plus bas. Schema mis a jour au demarrage.
database = Database(os.environ.get("DATABASE_PATH", "data/sambo.db"))
database.migrate()

# Envoi de mails (Brevo, voir mailer/mailer.py) : inactif tant que
# BREVO_API_KEY n'est pas definie (les mails sont alors juste journalises).
mailer = Mailer(
    api_key=os.environ.get("BREVO_API_KEY", ""),
    sender=os.environ.get("MAIL_SENDER", "essai@silvaplana.cloud"),
    sender_name=os.environ.get("MAIL_SENDER_NAME", "Alliance Sambo Combat La Ciotat"),
    reply_to=os.environ.get("MAIL_REPLY_TO") or None,
)

# Monte les routes des eleves en cours d'essai (/trials/...) sur la meme app
# (onglet "Essai"). Les certificats medicaux envoyes (donnees de sante)
# restent dans le volume Docker, jamais dans Git. PUBLIC_BASE_URL : adresse
# publique du site, pour les liens du QR code et du mail de confirmation.
public_base_url = os.environ.get("PUBLIC_BASE_URL", "https://silvaplana.cloud").rstrip("/")
trials_client = Trials(
    db=database,
    certificates_dir=os.environ.get("TRIALS_CERTIFICATES_DIR", "data/trial_certificates"),
    checkin_url=f"{public_base_url}/sambo-admin/?essai=",
    qr_image_url=f"{public_base_url}/sambo-admin/api/public/trials/qr/",
    mailer=mailer,
)
trials_receiver = TrialsReceiver(client=trials_client, app=protected_router)
# Page publique d'inscription au cours d'essai : routes /public/trials/...
# montees directement sur l'app, SANS mot de passe (comme /auth/login).
trials_public_receiver = TrialsPublicReceiver(client=trials_client, app=app)

# Monte les routes du bilan financier (/financialbalance/archives) sur la
# meme app. storage_dir doit pointer vers un repertoire persistant (volume
# Docker, voir docker-compose.yml) sous peine de perdre les archives
# recues au prochain redeploiement.
financialbalance_client = FinancialBalance(
    storage_dir=os.environ.get("FINANCIALBALANCE_STORAGE_DIR", "data/bank_archives"),
)
financialbalance_receiver = FinancialBalanceReceiver(client=financialbalance_client, app=protected_router)

# Monte les routes de l'historique des adherents (/members_history) sur la
# meme app. Aucune config requise : lit un fichier xlsx embarque dans le
# backend (voir members_history/members_history.py), pas une API externe.
members_history_client = MembersHistory()
members_history_receiver = MembersHistoryReceiver(client=members_history_client, app=protected_router)

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
notifications_receiver = NotificationsReceiver(client=notifications_client, app=protected_router)

# Comptes bancaires (/bankaccounts/...) : routeur a part, protege par
# require_accounts_auth (mot de passe "comptes", 2e niveau d'acces) et non
# par le simple require_auth du routeur commun -- une session "generale"
# obtient 403 ici. Donnees inventees pour l'instant (voir
# bankaccounts/bankaccounts.py). Mode LIVE (Enable Banking) seulement si
# ENABLE_BANKING_APP_ID et ENABLE_BANKING_KEY_PATH sont definis, sinon mode
# DEMO (donnees inventees) -- pratique en dev local, sans cle. storage_dir :
# repertoire persistant (volume Docker), la session bancaire (comptes
# autorises + expiration) y est memorisee.
accounts_router = APIRouter(dependencies=[Depends(require_accounts_auth)])
enable_banking_client = None
if os.environ.get("ENABLE_BANKING_APP_ID") and os.environ.get("ENABLE_BANKING_KEY_PATH"):
    enable_banking_client = EnableBankingClient(
        app_id=os.environ["ENABLE_BANKING_APP_ID"],
        private_key_path=os.environ["ENABLE_BANKING_KEY_PATH"],
        redirect_url=os.environ.get("ENABLE_BANKING_REDIRECT_URL", "https://silvaplana.cloud/sambo-admin/"),
        aspsp_name=os.environ.get("ENABLE_BANKING_ASPSP_NAME", "Crédit Mutuel"),
        aspsp_country=os.environ.get("ENABLE_BANKING_ASPSP_COUNTRY", "FR"),
        psu_type=os.environ.get("ENABLE_BANKING_PSU_TYPE", "personal"),
    )
# BANKACCOUNTS_DISPLAY : comptes a afficher, dans l'ordre, "fin_IBAN=Libelle"
# separes par ";" (ex: "6527=Compte courant;9706=Compte commun") -- voir
# BankAccounts. Vide : tous les comptes ayant un IBAN.
bank_accounts_display = [
    (suffix.strip(), label.strip())
    for suffix, _, label in (item.partition("=") for item in os.environ.get("BANKACCOUNTS_DISPLAY", "").split(";"))
    if suffix.strip() and label.strip()
]
bank_accounts_client = BankAccounts(
    storage_dir=os.environ.get("BANKACCOUNTS_STORAGE_DIR", "data/bankaccounts"),
    client=enable_banking_client,
    display=bank_accounts_display,
)
bank_accounts_receiver = BankAccountsReceiver(client=bank_accounts_client, app=accounts_router)

# Toutes les routes protegees ont ete enregistrees sur protected_router
# ci-dessus (par les differents *_receiver) : les incorpore maintenant
# dans l'app, Depends(require_auth) applique a chacune d'elles d'un
# coup.
app.include_router(protected_router)
app.include_router(accounts_router)

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


async def _purge_expired_trials() -> None:
    """Boucle de fond : une fois par jour, supprime les eleves a l'essai
    sans activite depuis un an (voir Trials.purge_expired)."""
    while True:
        try:
            removed = await asyncio.to_thread(trials_client.purge_expired)
            if removed:
                print(f"_purge_expired_trials: {removed} eleve(s) a l'essai supprime(s)")
        except Exception as exc:
            print(f"_purge_expired_trials: erreur ({exc})")
        await asyncio.sleep(24 * 60 * 60)


@app.on_event("startup")
async def _start_polling() -> None:
    asyncio.create_task(_poll_new_members())
    asyncio.create_task(_purge_expired_trials())


def main() -> None:
    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
