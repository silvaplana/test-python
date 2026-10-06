from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from .exports import to_pdf, to_xlsx
from .financialreports import FinancialReports, ReportError, ReportNotFoundError


class ReportRequest(BaseModel):
    """Corps de POST /financial-reports et PUT /financial-reports/{id}.
    state : "brouillon", "valide" ou "officiel" ; model : "haiku", "sonnet"
    ou "fable"."""

    seasonId: int | None = None
    name: str
    state: str = "brouillon"
    prompt: str = ""
    model: str | None = None


class SettingsRequest(BaseModel):
    """Corps de PUT /financial-reports/{id}/settings : zone "Réglages de l'IA"
    depliee (true) ou repliee (false)."""

    open: bool


class RunRequest(BaseModel):
    """Corps de POST /financial-reports/{id}/run : prompt et modele du
    calcul (enregistres dans le bilan)."""

    prompt: str | None = None
    model: str | None = None


class FinancialReportsReceiver:
    """Recoit les requetes REST (FastAPI) et delegue a FinancialReports.

    Monte sur le routeur protege par require_accounts_auth (voir
    app/main.py) : les bilans affichent les soldes des comptes.
    """

    def __init__(self, client: FinancialReports, app: FastAPI | APIRouter) -> None:
        self.client = client
        self.app = app
        self._register_routes()

    def _register_routes(self) -> None:
        self.app.get("/financial-reports")(self.listReports)
        self.app.post("/financial-reports")(self.createReport)
        self.app.get("/financial-reports/{report_id}")(self.getReport)
        self.app.put("/financial-reports/{report_id}")(self.updateReport)
        self.app.delete("/financial-reports/{report_id}")(self.deleteReport)
        self.app.post("/financial-reports/{report_id}/run")(self.runReport)
        self.app.put("/financial-reports/{report_id}/settings")(self.setSettingsOpen)
        self.app.get("/financial-reports/{report_id}/download")(self.downloadReport)

    def listReports(self, seasonId: int | None = None) -> dict:
        """Endpoint REST GET /financial-reports?seasonId= : bilans de la
        saison (sans leur resultat), modeles et etats possibles, et nombre de
        bilans de chaque saison (counts : {id de saison: nombre})."""
        return {
            **self.client.models(),
            "counts": self.client.counts(),
            "reports": self.client.list(seasonId) if seasonId is not None else [],
        }

    def getReport(self, report_id: int) -> dict:
        """Endpoint REST GET /financial-reports/{id} : bilan complet, relu par
        l'ecran pendant un calcul (status "running")."""
        try:
            return self.client.get(report_id)
        except ReportNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Bilan inconnu") from exc

    def createReport(self, request: ReportRequest) -> dict:
        try:
            return self.client.create(request.model_dump())
        except ReportError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def updateReport(self, report_id: int, request: ReportRequest) -> dict:
        try:
            return self.client.update(report_id, request.model_dump())
        except ReportError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ReportNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Bilan inconnu") from exc

    def deleteReport(self, report_id: int) -> dict:
        try:
            self.client.delete(report_id)
        except ReportNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Bilan inconnu") from exc
        return {"deleted": report_id}

    def runReport(self, report_id: int, request: RunRequest) -> dict:
        """Endpoint REST POST /financial-reports/{id}/run : lance le calcul
        (tableau + IA) en arriere-plan, voir FinancialReports.run."""
        try:
            return self.client.run(report_id, request.model_dump())
        except ReportError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ReportNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Bilan inconnu") from exc

    def setSettingsOpen(self, report_id: int, request: SettingsRequest) -> dict:
        """Endpoint REST PUT /financial-reports/{id}/settings : retient si la
        zone "Réglages de l'IA" est depliee."""
        try:
            return self.client.set_settings_open(report_id, request.open)
        except ReportNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Bilan inconnu") from exc

    def downloadReport(self, report_id: int, format: str = "xlsx") -> Response:
        """Endpoint REST GET /financial-reports/{id}/download?format=xlsx|pdf :
        resultat du dernier calcul en fichier."""
        try:
            report = self.client.get(report_id)
        except ReportNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Bilan inconnu") from exc
        if report["result"] is None:
            raise HTTPException(status_code=400, detail="Ce bilan n'a pas encore été calculé")
        if format == "pdf":
            content, media_type = to_pdf(report), "application/pdf"
        elif format == "xlsx":
            content = to_xlsx(report)
            media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        else:
            raise HTTPException(status_code=400, detail="Format inconnu (xlsx ou pdf)")
        name = f"bilan-{report['result']['seasonName']}-{report['id']}.{format}"
        return Response(content, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{name}"'})
