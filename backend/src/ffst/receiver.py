from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .ffst import Ffst, FfstAuthError


class DemandeRenouvellementRequest(BaseModel):
    """Corps de la requete POST /ffst/demandes_renouvellement."""

    lastName: str
    firstName: str


class FfstReceiver:
    """Recoit les requetes REST (FastAPI) et delegue a Ffst.

    Comme HelloAssoReceiver, enregistre ses routes sur une app FastAPI
    existante (partagee avec les autres modules), pas de service dedie.
    """

    def __init__(self, client: Ffst, app: FastAPI) -> None:
        self.client = client
        self.app = app
        self._register_routes()

    def _register_routes(self) -> None:
        self.app.get("/ffst/licences")(self.getLicences)
        self.app.get("/ffst/demandes_validated")(self.getDemandesValidated)
        self.app.get("/ffst/demandes_draft")(self.getDemandesDraft)
        self.app.post("/ffst/demandes_renouvellement")(self.createDemandeRenouvellement)

    def getLicences(self) -> list[dict]:
        """Endpoint REST GET /ffst/licences. Retourne les licences du club."""
        return self.client.get_licences()

    def getDemandesValidated(self) -> list[dict]:
        """Endpoint REST GET /ffst/demandes_validated. Retourne les demandes
        de licence (nouvelles demandes et renouvellements) en cours pour le
        club."""
        return self.client.get_demandes_validated()

    def getDemandesDraft(self) -> list[dict]:
        """Endpoint REST GET /ffst/demandes_draft. Retourne les demandes de
        licence en brouillon (enregistrees mais pas encore validees/soumises
        a la FFST, le "panier" du portail) pour le club."""
        return self.client.get_demandes_draft()

    def createDemandeRenouvellement(self, request: DemandeRenouvellementRequest) -> dict:
        """Endpoint REST POST /ffst/demandes_renouvellement. Soumet une
        demande de renouvellement de licence pour un ancien licencie du
        club (nom+prenom) et la place dans le panier/brouillon FFST
        (/ffst/demandes_draft) -- aucun paiement n'est declenche a cette
        etape, seule la validation ulterieure (manuelle, sur le portail)
        engage la facturation.
        """
        try:
            self.client.create_demande_renouvellement(request.lastName, request.firstName)
        except FfstAuthError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"status": "ok"}
