from fastapi import FastAPI

from .helloasso import HelloAsso


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

    def getCampaign(self) -> dict:
        """Endpoint REST GET /helloasso/campaign. Retourne le titre de la campagne."""
        form = self.client.get_form(self.form_slug, self.form_type)
        return {"title": form.get("title"), "formSlug": self.form_slug, "formType": self.form_type}

    def getMembers(self) -> list[dict]:
        """Endpoint REST GET /helloasso/members. Retourne la liste des adherents."""
        return self.client.get_members(self.form_slug, self.form_type)

    def getUnpaid(self) -> list[dict]:
        """Endpoint REST GET /helloasso/unpaid. Retourne les adherents ayant au
        moins un paiement refuse, avec le montant restant du."""
        members = self.client.get_member_payments(self.form_slug, self.form_type)
        unpaid = []
        for member in members:
            refused_payments = [p for p in member["payments"] if p["state"] != "Authorized"]
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
