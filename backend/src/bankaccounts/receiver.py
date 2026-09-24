from fastapi import APIRouter, FastAPI, HTTPException, Query

from .bankaccounts import BankAccountNotFoundError, BankAccounts


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
        self.app.get("/bankaccounts/accounts")(self.getAccounts)
        self.app.get("/bankaccounts/accounts/{account_id}/transactions")(self.getTransactions)

    def getAccounts(self) -> list[dict]:
        """Endpoint REST GET /bankaccounts/accounts. Retourne les comptes
        de l'association avec leur solde."""
        return self.client.get_accounts()

    def getTransactions(self, account_id: str, limit: int = Query(default=5, ge=1, le=100)) -> list[dict]:
        """Endpoint REST GET /bankaccounts/accounts/{account_id}/transactions
        ?limit=N. Retourne les N dernieres operations du compte (5 par
        defaut), la plus recente en premier."""
        try:
            return self.client.get_transactions(account_id, limit)
        except BankAccountNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Compte inconnu") from exc
