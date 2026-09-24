from fastapi import APIRouter, FastAPI, HTTPException, Query
from pydantic import BaseModel

from .bankaccounts import (
    BankAccountNotFoundError,
    BankAccounts,
    BankNotConnectedError,
    InvalidConnectionStateError,
)
from .enablebanking import EnableBankingError


class SessionRequest(BaseModel):
    """Corps de POST /bankaccounts/session : parametres du retour de la banque."""

    code: str
    state: str


class BankAccountsReceiver:
    """Recoit les requetes REST (FastAPI) et delegue a BankAccounts.

    Comme les autres receivers, enregistre ses routes sur une app FastAPI
    existante (partagee avec les autres modules), pas de service dedie.
    En realite un routeur protege par require_accounts_auth (voir
    app/main.py) : ces donnees exigent le mot de passe "comptes", pas
    seulement une session valide.
    """

    def __init__(self, client: BankAccounts, app: FastAPI | APIRouter) -> None:
        self.client = client
        self.app = app
        self._register_routes()

    def _register_routes(self) -> None:
        self.app.get("/bankaccounts/status")(self.getStatus)
        self.app.post("/bankaccounts/connect")(self.connect)
        self.app.post("/bankaccounts/session")(self.createSession)
        self.app.get("/bankaccounts/accounts")(self.getAccounts)
        self.app.get("/bankaccounts/accounts/{account_id}/transactions")(self.getTransactions)

    def getStatus(self) -> dict:
        """Endpoint REST GET /bankaccounts/status. Mode (demo/live) et etat de
        la connexion bancaire (active ou a refaire, date d'expiration)."""
        return self.client.get_status()

    def connect(self) -> dict:
        """Endpoint REST POST /bankaccounts/connect. Demarre l'autorisation
        chez la banque : retourne {"url"} ou envoyer l'utilisateur."""
        try:
            return {"url": self.client.start_connection()}
        except BankNotConnectedError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except EnableBankingError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    def createSession(self, request: SessionRequest) -> dict:
        """Endpoint REST POST /bankaccounts/session. Appele par le frontend au
        retour de la banque (code + state lus dans l'URL de redirection)."""
        try:
            self.client.complete_connection(request.code, request.state)
        except InvalidConnectionStateError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except BankNotConnectedError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except EnableBankingError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return self.client.get_status()

    def getAccounts(self, refresh: bool = False) -> list[dict]:
        """Endpoint REST GET /bankaccounts/accounts. Retourne les comptes
        de l'association avec leur solde (409 si la banque n'est pas
        connectee). refresh=true ignore le cache (bouton "Rafraichir")."""
        try:
            return self.client.get_accounts(refresh)
        except BankNotConnectedError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except EnableBankingError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    def getTransactions(
        self, account_id: str, limit: int = Query(default=5, ge=1, le=100), refresh: bool = False
    ) -> list[dict]:
        """Endpoint REST GET /bankaccounts/accounts/{account_id}/transactions
        ?limit=N. Retourne les N dernieres operations du compte (5 par
        defaut), la plus recente en premier."""
        try:
            return self.client.get_transactions(account_id, limit, refresh)
        except BankAccountNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Compte inconnu") from exc
        except BankNotConnectedError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except EnableBankingError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
