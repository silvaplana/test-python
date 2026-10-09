from collections.abc import Callable

from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel

from .seasons import SeasonError, SeasonNotFoundError, Seasons


class SeasonRequest(BaseModel):
    """Corps de POST /seasons et PUT /seasons/{id}. Dates AAAA-MM-JJ,
    montants en euros. endBalance (compte courant + Livret Bleu) absent
    (null) : calcule depuis l'historique des comptes."""

    name: str
    startDate: str
    endDate: str
    licences: int | None = None
    endBalance: float | None = None
    aiCost: float | None = None


class SeasonsReceiver:
    """Recoit les requetes REST (FastAPI) et delegue a Seasons.

    Monte sur le routeur protege par require_accounts_auth (voir
    app/main.py) : les saisons affichent les soldes des comptes.
    """

    def __init__(
        self,
        client: Seasons,
        app: FastAPI | APIRouter,
        licences_count: Callable[[], int] | None = None,
    ) -> None:
        """licences_count : nombre de licencies de la saison en cours chez
        FFST (voir Ffst.get_licences), pour POST /seasons/sync-licences."""
        self.client = client
        self.app = app
        self.licences_count = licences_count
        self._register_routes()

    def _register_routes(self) -> None:
        self.app.get("/seasons")(self.getSeasons)
        self.app.post("/seasons")(self.createSeason)
        # Avant /seasons/{season_id} : sinon "sync-licences" serait pris pour un id.
        self.app.post("/seasons/sync-licences")(self.syncLicences)
        self.app.get("/seasons/payroll-projection")(self.getPayrollProjection)
        self.app.put("/seasons/{season_id}")(self.updateSeason)
        self.app.delete("/seasons/{season_id}")(self.deleteSeason)

    def getSeasons(self) -> dict:
        """Endpoint REST GET /seasons : toutes les saisons et la courbe du
        solde total (voir Seasons.get_seasons)."""
        return self.client.get_seasons()

    def createSeason(self, request: SeasonRequest) -> dict:
        try:
            return self.client.create(request.model_dump())
        except SeasonError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def updateSeason(self, season_id: int, request: SeasonRequest) -> dict:
        try:
            return self.client.update(season_id, request.model_dump())
        except SeasonError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except SeasonNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Saison inconnue") from exc

    def deleteSeason(self, season_id: int) -> dict:
        try:
            self.client.delete(season_id)
        except SeasonNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Saison inconnue") from exc
        return {"deleted": season_id}

    def getPayrollProjection(self) -> dict:
        """Endpoint REST GET /seasons/payroll-projection : salaires et
        cotisations a payer jusqu'a la fin de la saison en cours, calcules
        depuis les operations des comptes ({"projection": null} sans saison
        en cours)."""
        return {"projection": self.client.payroll_projection()}

    def syncLicences(self) -> dict:
        """Endpoint REST POST /seasons/sync-licences : met a jour le nombre de
        licencies de la saison en cours depuis FFST (appele a chaque
        ouverture de l'onglet). Jamais en erreur HTTP : FFST injoignable ne
        doit pas empecher d'afficher les saisons -> {"season": null,
        "error": "..."}."""
        if self.licences_count is None:
            return {"season": None}
        try:
            return {"season": self.client.set_current_licences(self.licences_count())}
        except Exception as exc:
            return {"season": None, "error": str(exc)}
