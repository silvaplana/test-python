from collections.abc import Callable

from fastapi import APIRouter, FastAPI, HTTPException, UploadFile

from .bankstatements import BankAccountNotFoundError, BankStatements


class BankStatementsReceiver:
    """Recoit les requetes REST (FastAPI) et delegue a BankStatements.

    Monte sur le routeur protege par require_accounts_auth (voir
    app/main.py) : donnees bancaires, mot de passe "comptes" exige.
    """

    def __init__(
        self,
        client: BankStatements,
        app: FastAPI | APIRouter,
        live_operations: Callable[[], list[dict]] | None = None,
    ) -> None:
        """live_operations : lit les operations recentes a la banque (voir
        BankAccounts.get_recent_operations), pour POST /bankstatements/sync."""
        self.client = client
        self.app = app
        self.live_operations = live_operations
        self._register_routes()

    def _register_routes(self) -> None:
        self.app.post("/bankstatements/import")(self.importStatements)
        self.app.get("/bankstatements/ledger")(self.getLedger)
        self.app.post("/bankstatements/sync")(self.syncLive)

    async def importStatements(self, files: list[UploadFile]) -> dict:
        """Endpoint REST POST /bankstatements/import (multipart, champ
        "files" repete). Releves PDF ou zip de releves ; retourne le compte
        rendu (importes / deja presents / erreurs)."""
        return self.client.import_files([(f.filename or "releve.pdf", await f.read()) for f in files])

    def getLedger(self, account: int | None = None) -> dict:
        """Endpoint REST GET /bankstatements/ledger[?account=id]. Historique
        de tous les comptes ensemble (defaut) ou d'un seul."""
        try:
            return self.client.get_ledger(account)
        except BankAccountNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Compte inconnu") from exc

    def syncLive(self) -> dict:
        """Endpoint REST POST /bankstatements/sync. Ajoute a l'historique les
        operations recentes lues a la banque (appele a chaque ouverture de
        l'onglet). Jamais en erreur HTTP : une banque injoignable ou non
        connectee ne doit pas empecher d'afficher l'historique ->
        {"added": [], "error": "..."}."""
        if self.live_operations is None:
            return {"added": []}
        try:
            return self.client.sync_live(self.live_operations())
        except Exception as exc:
            return {"added": [], "error": str(exc)}
