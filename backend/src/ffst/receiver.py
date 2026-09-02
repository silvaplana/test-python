from fastapi import FastAPI

from .ffst import Ffst


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
