from fastapi import APIRouter, FastAPI, HTTPException, UploadFile

from .bankstatements import BankAccountNotFoundError, BankStatements


class BankStatementsReceiver:
    """Recoit les requetes REST (FastAPI) et delegue a BankStatements.

    Monte sur le routeur protege par require_accounts_auth (voir
    app/main.py) : donnees bancaires, mot de passe "comptes" exige.
    """

    def __init__(self, client: BankStatements, app: FastAPI | APIRouter) -> None:
        self.client = client
        self.app = app
        self._register_routes()

    def _register_routes(self) -> None:
        self.app.post("/bankstatements/import")(self.importStatements)
        self.app.get("/bankstatements/ledger")(self.getLedger)

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
