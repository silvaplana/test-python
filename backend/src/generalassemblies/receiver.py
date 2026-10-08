from urllib.parse import quote

from fastapi import APIRouter, FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .generalassemblies import AssemblyError, AssemblyNotFoundError, GeneralAssemblies

PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


class OrderRequest(BaseModel):
    """Corps de POST /general-assemblies/reorder : identifiants des cartes de la saison, dans
    l'ordre voulu."""

    seasonId: int
    ids: list[int]


class AssemblyRequest(BaseModel):
    """Corps de POST /general-assemblies et PUT /general-assemblies/{id}.
    state : "brouillon", "valide" ou "officiel" ; model : "haiku", "sonnet"
    ou "fable"."""

    seasonId: int | None = None
    name: str
    state: str = "brouillon"
    prompt: str = ""
    model: str | None = None


class SettingsRequest(BaseModel):
    """Corps de PUT /general-assemblies/{id}/settings : zone "Réglages de l'IA"
    depliee (true) ou repliee (false)."""

    open: bool


class RunRequest(BaseModel):
    """Corps de POST /general-assemblies/{id}/run."""

    prompt: str | None = None
    model: str | None = None


class ModelRequest(BaseModel):
    """Corps de PUT /general-assemblies/{id}/model : PPT a copier comme
    modele du calcul. kind : "modele", "genere" ou "modifie" d'un autre
    calcul (sourceId), ou "general" (modele general de l'onglet)."""

    sourceId: int | None = None
    kind: str


class GeneralAssembliesReceiver:
    """Recoit les requetes REST (FastAPI) et delegue a GeneralAssemblies.

    Monte sur le routeur protege par require_accounts_auth (voir
    app/main.py) : les PPT d'AG contiennent les soldes des comptes.
    """

    def __init__(self, client: GeneralAssemblies, app: FastAPI | APIRouter) -> None:
        self.client = client
        self.app = app
        self._register_routes()

    def _register_routes(self) -> None:
        self.app.get("/general-assemblies")(self.listAssemblies)
        self.app.post("/general-assemblies")(self.createAssembly)
        self.app.post("/general-assemblies/reorder")(self.reorderAssemblies)
        self.app.post("/general-assemblies/template")(self.uploadTemplate)
        # Avant /general-assemblies/{assembly_id} : sinon pris pour un id.
        self.app.get("/general-assemblies/model-sources")(self.getModelSources)
        self.app.get("/general-assemblies/{assembly_id}")(self.getAssembly)
        self.app.put("/general-assemblies/{assembly_id}")(self.updateAssembly)
        self.app.delete("/general-assemblies/{assembly_id}")(self.deleteAssembly)
        self.app.post("/general-assemblies/{assembly_id}/run")(self.runAssembly)
        self.app.put("/general-assemblies/{assembly_id}/settings")(self.setSettingsOpen)
        self.app.post("/general-assemblies/{assembly_id}/upload")(self.uploadModified)
        self.app.post("/general-assemblies/{assembly_id}/model")(self.uploadModel)
        self.app.put("/general-assemblies/{assembly_id}/model")(self.copyModel)
        self.app.get("/general-assemblies/{assembly_id}/download")(self.download)
        self.app.get("/general-assemblies/{assembly_id}/files/{kind}/slides")(self.getSlides)
        self.app.get("/general-assemblies/{assembly_id}/files/{kind}/slides/{image}.png")(self.getThumbnail)

    def reorderAssemblies(self, request: OrderRequest) -> dict:
        """Endpoint REST POST /general-assemblies/reorder : nouvel ordre des cartes de
        la saison (poignee de chaque carte)."""
        return {"assemblies": self.client.reorder(request.seasonId, request.ids)}

    def _call(self, action, *args):
        try:
            return action(*args)
        except AssemblyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except AssemblyNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Introuvable") from exc

    def listAssemblies(self, seasonId: int | None = None) -> dict:
        """Endpoint REST GET /general-assemblies?seasonId= : calculs d'AG de la
        saison, modeles, etats, bilan et PPT modele que prendrait un calcul."""
        return {
            **self.client.options(seasonId),
            # Nombre de calculs de chaque saison ({id de saison: nombre}).
            "counts": self.client.counts(),
            "assemblies": self.client.list(seasonId) if seasonId is not None else [],
        }

    def getAssembly(self, assembly_id: int) -> dict:
        return self._call(self.client.get, assembly_id)

    def createAssembly(self, request: AssemblyRequest) -> dict:
        return self._call(self.client.create, request.model_dump())

    def updateAssembly(self, assembly_id: int, request: AssemblyRequest) -> dict:
        return self._call(self.client.update, assembly_id, request.model_dump())

    def deleteAssembly(self, assembly_id: int) -> dict:
        self._call(self.client.delete, assembly_id)
        return {"deleted": assembly_id}

    def runAssembly(self, assembly_id: int, request: RunRequest) -> dict:
        """Endpoint REST POST /general-assemblies/{id}/run : lance le calcul
        du PPT en arriere-plan, voir GeneralAssemblies.run."""
        return self._call(self.client.run, assembly_id, request.model_dump())

    def setSettingsOpen(self, assembly_id: int, request: SettingsRequest) -> dict:
        """Endpoint REST PUT /general-assemblies/{id}/settings : retient si la
        zone "Réglages de l'IA" est depliee."""
        return self._call(self.client.set_settings_open, assembly_id, request.open)

    async def uploadModified(self, assembly_id: int, file: UploadFile) -> dict:
        """Endpoint REST POST /general-assemblies/{id}/upload : PPT modifie
        par le tresorier (remplace le precedent)."""
        content = await file.read()
        return self._call(self.client.upload, assembly_id, content, file.filename or "ag.pptx")

    async def uploadModel(self, assembly_id: int, file: UploadFile) -> dict:
        """Endpoint REST POST /general-assemblies/{id}/model : PPT modele du
        calcul, envoye depuis l'ordinateur."""
        content = await file.read()
        return self._call(self.client.set_model, assembly_id, content, file.filename or "modele.pptx")

    def copyModel(self, assembly_id: int, request: ModelRequest) -> dict:
        """Endpoint REST PUT /general-assemblies/{id}/model : PPT modele du
        calcul, copie d'un PPT d'un autre calcul ou du modele general."""
        return self._call(self.client.copy_model, assembly_id, request.sourceId, request.kind)

    def getModelSources(self, exclude: int | None = None) -> list[dict]:
        """Endpoint REST GET /general-assemblies/model-sources?exclude= : PPT
        des autres calculs (et modele general) utilisables comme modele."""
        return self.client.model_sources(exclude)

    async def uploadTemplate(self, file: UploadFile) -> dict:
        """Endpoint REST POST /general-assemblies/template : PPT modele (utilise
        quand la saison precedente n'a pas d'AG officielle)."""
        content = await file.read()
        return self._call(self.client.set_template, content)

    def download(self, assembly_id: int, kind: str | None = None) -> FileResponse:
        """Endpoint REST GET /general-assemblies/{id}/download?kind= : un des
        3 PPT du calcul ("modele", "genere", "modifie") ; sans kind, le PPT
        final (modifie, sinon produit par l'IA)."""
        path, filename = self._call(self.client.file_path, assembly_id, kind)
        return FileResponse(
            path,
            media_type=PPTX,
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
        )

    def getSlides(self, assembly_id: int, kind: str) -> dict:
        """Endpoint REST GET /general-assemblies/{id}/files/{kind}/slides :
        textes des diapos et images disponibles (LibreOffice)."""
        return self._call(self.client.slides, assembly_id, kind)

    def getThumbnail(self, assembly_id: int, kind: str, image: int) -> FileResponse:
        return FileResponse(self._call(self.client.thumbnail, assembly_id, kind, image), media_type="image/png")
