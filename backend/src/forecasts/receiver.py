from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from .forecasts import ForecastError, ForecastNotFoundError, Forecasts
from .sandbox import FormulaError


class ForecastRequest(BaseModel):
    """Corps de POST /forecasts et PUT /forecasts/{id}. state : "brouillon",
    "valide" ou "officiel" ; model : "haiku", "sonnet" ou "fable" ;
    startDate : AAAA-MM-JJ, vide pour le dernier jour connu des comptes."""

    seasonId: int | None = None
    name: str
    state: str = "brouillon"
    prompt: str = ""
    model: str | None = None
    startDate: str | None = None


class RunRequest(BaseModel):
    """Corps de POST /forecasts/{id}/run : champs du formulaire, enregistres
    avant le calcul."""

    name: str | None = None
    state: str | None = None
    prompt: str | None = None
    model: str | None = None
    startDate: str | None = None


class ParamsRequest(BaseModel):
    """Corps de PUT /forecasts/{id}/params : position des curseurs."""

    params: dict[str, float]


class ExplanationRequest(BaseModel):
    """Corps de PUT /forecasts/{id}/explanation et /settings : zone
    "Explication du résultat de l'IA" ou "Réglages de l'IA" depliee (true) ou
    repliee (false)."""

    open: bool


class ForecastsReceiver:
    """Recoit les requetes REST (FastAPI) et delegue a Forecasts.

    Monte sur le routeur protege par require_accounts_auth (voir
    app/main.py) : les previsionnels affichent les soldes des comptes.
    """

    def __init__(self, client: Forecasts, app: FastAPI | APIRouter) -> None:
        self.client = client
        self.app = app
        self._register_routes()

    def _register_routes(self) -> None:
        self.app.get("/forecasts")(self.listForecasts)
        self.app.post("/forecasts")(self.createForecast)
        self.app.get("/forecasts/{forecast_id}")(self.getForecast)
        self.app.put("/forecasts/{forecast_id}")(self.updateForecast)
        self.app.delete("/forecasts/{forecast_id}")(self.deleteForecast)
        self.app.post("/forecasts/{forecast_id}/run")(self.runForecast)
        self.app.put("/forecasts/{forecast_id}/params")(self.setParams)
        self.app.put("/forecasts/{forecast_id}/explanation")(self.setExplanationOpen)
        self.app.put("/forecasts/{forecast_id}/settings")(self.setSettingsOpen)
        self.app.get("/forecasts/{forecast_id}/download")(self.downloadForecast)

    def _call(self, action, *args):
        try:
            return action(*args)
        except (ForecastError, FormulaError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ForecastNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Prévisionnel inconnu") from exc

    def listForecasts(self, seasonId: int | None = None) -> dict:
        """Endpoint REST GET /forecasts?seasonId= : previsionnels de la saison
        (sans leur resultat), modeles et etats possibles, et nombre de
        previsionnels de chaque saison (counts : {id de saison: nombre})."""
        return {
            **self.client.models(),
            "counts": self.client.counts(),
            "forecasts": self.client.list(seasonId) if seasonId is not None else [],
        }

    def getForecast(self, forecast_id: int) -> dict:
        """Endpoint REST GET /forecasts/{id} : previsionnel complet, relu par
        l'ecran pendant un calcul (status "running")."""
        return self._call(self.client.get, forecast_id)

    def createForecast(self, request: ForecastRequest) -> dict:
        return self._call(self.client.create, request.model_dump())

    def updateForecast(self, forecast_id: int, request: ForecastRequest) -> dict:
        return self._call(self.client.update, forecast_id, request.model_dump())

    def deleteForecast(self, forecast_id: int) -> dict:
        self._call(self.client.delete, forecast_id)
        return {"deleted": forecast_id}

    def runForecast(self, forecast_id: int, request: RunRequest) -> dict:
        """Endpoint REST POST /forecasts/{id}/run : l'IA ecrit la formule, en
        arriere-plan (voir Forecasts.run)."""
        return self._call(self.client.run, forecast_id, request.model_dump())

    def setParams(self, forecast_id: int, request: ParamsRequest) -> dict:
        """Endpoint REST PUT /forecasts/{id}/params : rejoue la formule avec
        ces curseurs (sans IA) et les enregistre."""
        return self._call(self.client.set_params, forecast_id, request.params)

    def setExplanationOpen(self, forecast_id: int, request: ExplanationRequest) -> dict:
        """Endpoint REST PUT /forecasts/{id}/explanation : retient si la zone
        "Explication du résultat de l'IA" est depliee."""
        return self._call(self.client.set_explanation_open, forecast_id, request.open)

    def setSettingsOpen(self, forecast_id: int, request: ExplanationRequest) -> dict:
        """Endpoint REST PUT /forecasts/{id}/settings : retient si la zone
        "Réglages de l'IA" (prompt, modele, cout) est depliee."""
        return self._call(self.client.set_settings_open, forecast_id, request.open)

    def downloadForecast(self, forecast_id: int, format: str = "png") -> Response:
        """Endpoint REST GET /forecasts/{id}/download?format=png|pdf : resultat
        en image ou en PDF."""
        content, media_type, name = self._call(self.client.export, forecast_id, format)
        return Response(content, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{name}"'})
