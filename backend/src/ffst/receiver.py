from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .ffst import FFST_FONCTIONS, Ffst, FfstAuthError


class DemandeRenouvellementRequest(BaseModel):
    """Corps de la requete POST /ffst/demandes_renouvellement.

    fonction doit etre l'une des valeurs de GET /ffst/fonctions, par
    defaut "005-PRATIQUANT" (le cas le plus courant). gender/birthDate/
    addressLine1/postalCode/city/phone/email ne sont utilises que si
    l'adherent n'a pas d'ancienne licence renouvelable (chemin "nouvelle
    demande", voir Ffst.create_demande_renouvellement) : optionnels ici,
    mais leur absence fait alors echouer la requete avec le detail de ce
    qui manque.
    """

    lastName: str
    firstName: str
    fonction: str = "005-PRATIQUANT"
    gender: str | None = None
    birthDate: str | None = None
    addressLine1: str | None = None
    postalCode: str | None = None
    city: str | None = None
    phone: str | None = None
    email: str | None = None


class DemandeDraftRequest(BaseModel):
    """Corps de la requete DELETE /ffst/demandes_draft."""

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
        self.app.get("/ffst/fonctions")(self.getFonctions)
        self.app.post("/ffst/demandes_renouvellement")(self.createDemandeRenouvellement)
        self.app.delete("/ffst/demandes_draft")(self.deleteDemandeDraft)

    def getLicences(self) -> list[dict]:
        """Endpoint REST GET /ffst/licences. Retourne les licences du club."""
        return self.client.get_licences()

    def getFonctions(self) -> list[str]:
        """Endpoint REST GET /ffst/fonctions. Retourne la liste des valeurs
        possibles pour le champ "fonction" d'une demande de licence (voir
        FFST_FONCTIONS), pour peupler un choix dans l'IHM avant de soumettre
        une demande pour un role autre que pratiquant."""
        return FFST_FONCTIONS

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
        demande de licence pour un adherent du club (nom+prenom) et la
        place dans le panier/brouillon FFST (/ffst/demandes_draft) --
        aucun paiement n'est declenche a cette etape, seule la validation
        ulterieure (manuelle, sur le portail) engage la facturation.

        Essaie d'abord un renouvellement (ancien licencie du club) puis,
        si l'adherent n'a jamais ete licencie, une nouvelle demande a
        partir des champs HelloAsso gender/birthDate/addressLine1/etc.
        (voir Ffst.create_demande_renouvellement).

        La reponse peut inclure des avertissements non bloquants (ex:
        commune de naissance de repli utilisee pour une fonction autre que
        pratiquant), a afficher a l'utilisateur -- la demande est malgre
        tout bien enregistree.
        """
        try:
            warnings = self.client.create_demande_renouvellement(
                request.lastName,
                request.firstName,
                fonction=request.fonction,
                gender=request.gender,
                birth_date=request.birthDate,
                address_line1=request.addressLine1,
                postal_code=request.postalCode,
                city=request.city,
                phone=request.phone,
                email=request.email,
            )
        except FfstAuthError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"status": "ok", "warnings": warnings}

    def deleteDemandeDraft(self, request: DemandeDraftRequest) -> dict:
        """Endpoint REST DELETE /ffst/demandes_draft. Supprime une demande
        en brouillon (panier) pour un adherent du club (nom+prenom, doit
        correspondre a une seule ligne du panier).
        """
        try:
            self.client.delete_demande_draft(request.lastName, request.firstName)
        except FfstAuthError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"status": "ok"}
