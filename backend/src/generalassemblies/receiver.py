from urllib.parse import quote

from fastapi import APIRouter, FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .generalassemblies import AssemblyError, AssemblyNotFoundError, GeneralAssemblies

PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


class AssemblyRequest(BaseModel):
    """Corps de POST /general-assemblies et PUT /general-assemblies/{id}.
    state : "brouillon", "valide" ou "officiel" ; model : "haiku", "sonnet"
    ou "fable"."""

    seasonId: int | None = None
    name: str
    state: str = "brouillon"
    prompt: str = ""
    model: str | None = None


class RunRequest(BaseModel):
    """Corps de POST /general-assemblies/{id}/run."""

    prompt: str | None = None
    model: str | None = None


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
        self.app.post("/general-assemblies/template")(self.uploadTemplate)
        self.app.get("/general-assemblies/{assembly_id}")(self.getAssembly)
        self.app.put("/general-assemblies/{assembly_id}")(self.updateAssembly)
        self.app.delete("/general-assemblies/{assembly_id}")(self.deleteAssembly)
        self.app.post("/general-assemblies/{assembly_id}/run")(self.runAssembly)
        self.app.post("/general-assemblies/{assembly_id}/upload")(self.uploadVersion)
        self.app.get("/general-assemblies/{assembly_id}/download")(self.download)
        self.app.get("/general-assemblies/{assembly_id}/versions/{number}/slides")(self.getSlides)
        self.app.get("/general-assemblies/{assembly_id}/versions/{number}/slides/{image}.png")(self.getThumbnail)

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

    async def uploadVersion(self, assembly_id: int, file: UploadFile) -> dict:
        """Endpoint REST POST /general-assemblies/{id}/upload : PPT modifie
        par le tresorier, enregistre comme nouvelle version."""
        content = await file.read()
        return self._call(self.client.upload, assembly_id, content, file.filename or "ag.pptx")

    async def uploadTemplate(self, file: UploadFile) -> dict:
        """Endpoint REST POST /general-assemblies/template : PPT modele (utilise
        quand la saison precedente n'a pas d'AG officielle)."""
        content = await file.read()
        return self._call(self.client.set_template, content)

    def download(self, assembly_id: int, version: int | None = None) -> FileResponse:
        """Endpoint REST GET /general-assemblies/{id}/download?version= : PPT
        d'une version (la derniere par defaut)."""
        path, filename = self._call(self.client.version_path, assembly_id, version)
        return FileResponse(
            path,
            media_type=PPTX,
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
        )

    def getSlides(self, assembly_id: int, number: int) -> dict:
        """Endpoint REST GET /general-assemblies/{id}/versions/{n}/slides :
        textes des diapos et images disponibles (LibreOffice)."""
        return self._call(self.client.slides, assembly_id, number)

    def getThumbnail(self, assembly_id: int, number: int, image: int) -> FileResponse:
        return FileResponse(self._call(self.client.thumbnail, assembly_id, number, image), media_type="image/png")
