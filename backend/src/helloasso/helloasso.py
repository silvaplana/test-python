"""Client pour l'API HelloAsso (https://api.helloasso.com).

HelloAsso expose une API REST v5 protegee par OAuth2 (flow
"client_credentials"). Ce module fournit une classe HelloAsso qui gere
l'authentification puis quelques appels courants (organisation, formulaires).

Variables d'environnement attendues pour le main() de demo :
    HELLOASSO_CLIENT_ID          identifiant OAuth2 (cle API HelloAsso)
    HELLOASSO_CLIENT_SECRET      secret OAuth2
    HELLOASSO_ORGANIZATION_SLUG  slug de l'organisation (optionnel)
    HELLOASSO_SANDBOX            "1" pour utiliser l'environnement de bac a sable

Voir .env.example a la racine de backend/.
"""

from __future__ import annotations

import os

import httpx
from dotenv import load_dotenv


class HelloAssoAuthError(RuntimeError):
    """Levee quand l'authentification OAuth2 aupres de HelloAsso echoue."""


class HelloAsso:
    """Client HTTP pour l'API HelloAsso.

    Gere l'authentification OAuth2 (client_credentials) et expose quelques
    appels REST de l'API v5. Le token est recupere paresseusement au premier
    appel authentifie et reutilise ensuite.
    """

    PRODUCTION_URL = "https://api.helloasso.com"
    SANDBOX_URL = "https://api.helloasso-sandbox.com"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        organization_slug: str | None = None,
        sandbox: bool = False,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.organization_slug = organization_slug
        self.base_url = self.SANDBOX_URL if sandbox else self.PRODUCTION_URL
        self._access_token: str | None = None

    def authenticate(self) -> str:
        """Recupere un access_token via le flow OAuth2 client_credentials."""
        response = httpx.post(
            f"{self.base_url}/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
        )
        if response.status_code != 200:
            raise HelloAssoAuthError(
                f"Authentification HelloAsso echouee ({response.status_code}): {response.text}"
            )
        self._access_token = response.json()["access_token"]
        print("HelloAsso.authenticate: token obtenu")
        return self._access_token

    def _headers(self) -> dict[str, str]:
        if self._access_token is None:
            self.authenticate()
        return {"Authorization": f"Bearer {self._access_token}"}

    def get(self, path: str, params: dict | None = None) -> dict:
        """Appel GET authentifie sur l'API (path relatif, ex: '/v5/users/me')."""
        response = httpx.get(f"{self.base_url}{path}", headers=self._headers(), params=params)
        response.raise_for_status()
        return response.json()

    def get_organization(self) -> dict:
        """Retourne les informations de l'organisation (necessite organization_slug)."""
        if not self.organization_slug:
            raise ValueError("organization_slug requis pour get_organization()")
        print(f"HelloAsso.get_organization: slug={self.organization_slug}")
        return self.get(f"/v5/organizations/{self.organization_slug}")

    def get_forms(self) -> list:
        """Retourne la liste des formulaires (campagnes) de l'organisation."""
        if not self.organization_slug:
            raise ValueError("organization_slug requis pour get_forms()")
        print(f"HelloAsso.get_forms: slug={self.organization_slug}")
        data = self.get(f"/v5/organizations/{self.organization_slug}/forms")
        return data.get("data", data)

    def get_form(self, form_slug: str, form_type: str = "Membership") -> dict:
        """Retourne les infos d'un formulaire (dont son titre), via get_forms()."""
        for form in self.get_forms():
            if form.get("formSlug") == form_slug and form.get("formType") == form_type:
                return form
        raise ValueError(f"Formulaire introuvable : {form_type}/{form_slug}")

    def get_form_orders(
        self,
        form_slug: str,
        form_type: str = "Membership",
        *,
        page_size: int = 100,
        with_details: bool = True,
    ) -> list[dict]:
        """Retourne toutes les commandes (orders) d'un formulaire, pagination geree automatiquement.

        form_type doit etre l'une des valeurs HelloAsso : CrowdFunding, Membership,
        Event, Donation, PaymentForm, Checkout, Shop.
        """
        if not self.organization_slug:
            raise ValueError("organization_slug requis pour get_form_orders()")
        orders: list[dict] = []
        page_index = 1
        while True:
            data = self.get(
                f"/v5/organizations/{self.organization_slug}/forms/{form_type}/{form_slug}/orders",
                params={"pageIndex": page_index, "pageSize": page_size, "withDetails": with_details},
            )
            orders.extend(data.get("data", []))
            total_pages = data.get("pagination", {}).get("totalPages", page_index)
            if page_index >= total_pages:
                break
            page_index += 1
        print(f"HelloAsso.get_form_orders: {len(orders)} commande(s) recuperee(s) pour {form_slug}")
        return orders

    def get_members(self, form_slug: str, form_type: str = "Membership") -> list[dict]:
        """Extrait la liste des adherents d'un formulaire d'adhesion.

        Un adherent = un item de type "Membership" dans une commande (une commande
        peut contenir plusieurs adherents, ex: fratrie payee par un meme parent).
        Retourne pour chaque adherent : nom, prenom, email du payeur, montant paye
        (en euros), statut, date de commande, et les champs personnalises du
        formulaire (telephone, adresse, date de naissance, etc.) sous forme de dict.
        """
        members: list[dict] = []
        for order in self.get_form_orders(form_slug, form_type):
            payer = order.get("payer", {})
            for item in order.get("items", []):
                if item.get("type") != "Membership":
                    continue
                user = item.get("user", {})
                custom_fields = {
                    field["name"]: field.get("answer") for field in item.get("customFields", [])
                }
                members.append(
                    {
                        "firstName": user.get("firstName") or payer.get("firstName"),
                        "lastName": user.get("lastName") or payer.get("lastName"),
                        "email": payer.get("email"),
                        "amount": item.get("amount", 0) / 100,
                        "state": item.get("state"),
                        "orderDate": order.get("date"),
                        "customFields": custom_fields,
                    }
                )
        print(f"HelloAsso.get_members: {len(members)} adherent(s) extrait(s) pour {form_slug}")
        return members

    def get_member_payments(self, form_slug: str, form_type: str = "Membership") -> list[dict]:
        """Retourne chaque adherent avec le detail de ses paiements.

        Une adhesion peut etre payee en plusieurs fois (paiement echelonne) : la
        part de chaque paiement affectee a l'adherent est retrouvee via
        item["payments"] (references id + part) croisee avec les paiements complets
        de la commande (order["payments"], qui portent date/moyen/statut/encaissement).
        """
        members: list[dict] = []
        for order in self.get_form_orders(form_slug, form_type):
            payer = order.get("payer", {})
            payments_by_id = {p["id"]: p for p in order.get("payments", [])}
            for item in order.get("items", []):
                if item.get("type") != "Membership":
                    continue
                user = item.get("user", {})
                item_payments = []
                for ref in item.get("payments", []):
                    payment = payments_by_id.get(ref.get("id"))
                    if payment is None:
                        continue
                    item_payments.append(
                        {
                            "amount": ref.get("shareAmount", 0) / 100,
                            "date": payment.get("date"),
                            "paymentMeans": payment.get("paymentMeans"),
                            "state": payment.get("state"),
                            "installmentNumber": payment.get("installmentNumber"),
                            "cashOutState": payment.get("cashOutState"),
                            "cashOutDate": payment.get("cashOutDate"),
                        }
                    )
                members.append(
                    {
                        "firstName": user.get("firstName") or payer.get("firstName"),
                        "lastName": user.get("lastName") or payer.get("lastName"),
                        "email": payer.get("email"),
                        "totalAmount": item.get("amount", 0) / 100,
                        "payments": item_payments,
                    }
                )
        print(
            f"HelloAsso.get_member_payments: {len(members)} adherent(s), "
            f"{sum(len(m['payments']) for m in members)} paiement(s) au total pour {form_slug}"
        )
        return members


def main() -> None:
    load_dotenv()  # charge backend/.env si present (variables deja definies restent prioritaires)

    client_id = os.environ.get("HELLOASSO_CLIENT_ID")
    client_secret = os.environ.get("HELLOASSO_CLIENT_SECRET")
    organization_slug = os.environ.get("HELLOASSO_ORGANIZATION_SLUG")
    sandbox = os.environ.get("HELLOASSO_SANDBOX", "").lower() in ("1", "true", "yes")

    if not client_id or not client_secret:
        raise SystemExit(
            "HELLOASSO_CLIENT_ID et HELLOASSO_CLIENT_SECRET doivent etre definis "
            "(variables d'environnement, voir backend/.env.example)."
        )

    client = HelloAsso(client_id, client_secret, organization_slug, sandbox=sandbox)
    client.authenticate()

    if organization_slug:
        print(client.get_organization())
    else:
        print(
            "Authentification OK. Definir HELLOASSO_ORGANIZATION_SLUG pour "
            "interroger une organisation."
        )


if __name__ == "__main__":
    main()
