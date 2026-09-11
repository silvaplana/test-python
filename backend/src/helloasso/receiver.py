import re
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response

from .helloasso import HelloAsso, HelloAssoAuthError

# Restreint /helloasso/photo aux URL HelloAsso reelles (voir getPhoto) :
# sans ca, ce endpoint deviendrait un proxy HTTP generique authentifie
# avec les identifiants du club, un risque de securite (SSRF) pour un
# gain nul (aucun autre hote n'a besoin de ce relais).
PHOTO_URL_PATH_RE = re.compile(r"^/customFieldsAnswer/\d+$")

# Etats HelloAsso (PaymentState) indiquant un paiement reellement refuse/en
# echec definitif. A distinguer des etats "futur/en attente" (Pending,
# Waiting*, Init) : une adhesion payee en plusieurs fois a des echeances a
# venir dans cet etat le temps qu'elles arrivent a echeance, ce n'est pas un
# impaye. Registered/Authorized/Refunding/Contested/Corrected sont des etats
# de succes (partiel ou en cours), pas des echecs non plus.
FAILED_PAYMENT_STATES = {
    "Refused",
    "Error",
    "Canceled",
    "Abandoned",
    "Deleted",
    "Inconsistent",
    "NoDonation",
}


class HelloAssoReceiver:
    """Recoit les requetes REST (FastAPI) et delegue a HelloAsso.

    Contrairement a MotorReceiver, ne cree pas sa propre app FastAPI : les
    routes sont enregistrees sur une app existante (partagee avec les autres
    modules du backend), pour ne faire tourner qu'un seul service HTTP.
    """

    def __init__(
        self,
        client: HelloAsso,
        app: FastAPI,
        form_slug: str,
        form_type: str = "Membership",
    ) -> None:
        self.client = client
        self.app = app
        self.form_slug = form_slug
        self.form_type = form_type
        self._register_routes()

    def _register_routes(self) -> None:
        self.app.get("/helloasso/campaign")(self.getCampaign)
        self.app.get("/helloasso/members")(self.getMembers)
        self.app.get("/helloasso/unpaid")(self.getUnpaid)
        self.app.get("/helloasso/photo")(self.getPhoto)

    def getCampaign(self) -> dict:
        """Endpoint REST GET /helloasso/campaign. Retourne le titre de la campagne."""
        form = self.client.get_form(self.form_slug, self.form_type)
        return {"title": form.get("title"), "formSlug": self.form_slug, "formType": self.form_type}

    def getMembers(self) -> list[dict]:
        """Endpoint REST GET /helloasso/members. Retourne la liste des adherents."""
        return self.client.get_members(self.form_slug, self.form_type)

    def getUnpaid(self) -> list[dict]:
        """Endpoint REST GET /helloasso/unpaid. Retourne les adherents ayant au
        moins un paiement reellement refuse/en echec (voir
        FAILED_PAYMENT_STATES), avec le montant restant du.

        Ne compte pas les echeances futures d'un paiement echelonne (etat
        Pending/Waiting* le temps qu'elles arrivent a echeance) comme des
        impayes.
        """
        members = self.client.get_member_payments(self.form_slug, self.form_type)
        unpaid = []
        for member in members:
            refused_payments = [p for p in member["payments"] if p["state"] in FAILED_PAYMENT_STATES]
            if not refused_payments:
                continue
            unpaid.append(
                {
                    "firstName": member["firstName"],
                    "lastName": member["lastName"],
                    "email": member["email"],
                    "totalAmount": member["totalAmount"],
                    "unpaidAmount": sum(p["amount"] for p in refused_payments),
                    "refusedPayments": refused_payments,
                }
            )
        return unpaid

    def getPhoto(self, url: str) -> Response:
        """Endpoint REST GET /helloasso/photo?url=... . Relaie (avec
        authentification) une photo hebergee par HelloAsso -- typiquement
        customFields["photo d'identité"] d'un adherent, deja presente
        telle quelle dans la reponse de /helloasso/members. Le navigateur
        ne peut pas la charger directement (401 sans le jeton OAuth2 du
        club, confirme en conditions reelles).

        url doit pointer vers docs.helloasso.com (voir PHOTO_URL_PATH_RE) :
        sans cette restriction, ce endpoint authentifierait n'importe
        quelle URL fournie avec les identifiants du club (SSRF).
        """
        parsed = urlparse(url)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "docs.helloasso.com"
            or not PHOTO_URL_PATH_RE.match(parsed.path)
        ):
            raise HTTPException(status_code=400, detail="URL de photo invalide")
        try:
            thumbnail = self.client.get_photo_thumbnail(url)
        except HelloAssoAuthError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Échec de récupération de la photo : {exc}") from exc
        # Cache navigateur genereux (photo statique une fois uploadee) :
        # evite de re-solliciter ce relais (et HelloAsso) a chaque
        # rafraichissement du tableau des adherents.
        return Response(content=thumbnail, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})
