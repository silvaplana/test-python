"""Client HTTP minimal pour l'API Enable Banking (https://enablebanking.com),
agregateur bancaire PSD2 : lit soldes et operations des comptes de
l'association apres autorisation de l'utilisateur chez sa banque.

Authentification de l'application : un JWT signe RS256 avec la cle privee
(.pem, telechargee a la creation de l'application dans le Control Panel), dont
le header "kid" est l'Application ID. Voir get_token().

Flux d'autorisation (voir BankAccounts.start_connection/complete_connection) :
  1. POST /auth       -> URL de la banque ou envoyer l'utilisateur
  2. la banque le redirige vers redirect_url avec ?code=...&state=...
  3. POST /sessions   -> session_id + liste des comptes autorises (uid)
  4. GET /accounts/{uid}/balances et /transactions
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import jwt


class EnableBankingError(RuntimeError):
    """Levee quand l'API Enable Banking (ou son authentification) echoue."""


class EnableBankingClient:
    BASE_URL = "https://api.enablebanking.com"

    def __init__(
        self,
        app_id: str,
        private_key_path: str,
        redirect_url: str,
        aspsp_name: str = "Boursorama Banque",
        aspsp_country: str = "FR",
        psu_type: str = "personal",
        valid_days: int = 179,
    ) -> None:
        self.app_id = app_id
        self.private_key_path = Path(private_key_path)
        self.redirect_url = redirect_url
        self.aspsp_name = aspsp_name
        self.aspsp_country = aspsp_country
        self.psu_type = psu_type
        # Le maximum accepte par les banques est 180 jours (voir
        # maximum_consent_validity de GET /aspsps) : 179 pour rester en dessous.
        self.valid_days = valid_days

    def get_token(self) -> str:
        """JWT de l'application (valable 1 h, recalcule a chaque requete :
        peu couteux, evite de gerer une expiration)."""
        try:
            private_key = self.private_key_path.read_bytes()
        except OSError as exc:
            raise EnableBankingError(f"Clé privée Enable Banking illisible ({self.private_key_path})") from exc
        now = int(time.time())
        return jwt.encode(
            {"iss": "enablebanking.com", "aud": "api.enablebanking.com", "iat": now, "exp": now + 3600},
            private_key,
            algorithm="RS256",
            headers={"kid": self.app_id},
        )

    def _request(self, method: str, path: str, **kwargs) -> dict:
        try:
            response = httpx.request(
                method,
                f"{self.BASE_URL}{path}",
                headers={"Authorization": f"Bearer {self.get_token()}"},
                timeout=30,
                **kwargs,
            )
        except httpx.HTTPError as exc:
            raise EnableBankingError(f"Enable Banking injoignable : {exc}") from exc
        if response.status_code >= 400:
            try:
                detail = response.json().get("message") or response.text
            except ValueError:
                detail = response.text
            raise EnableBankingError(f"Enable Banking {response.status_code} : {detail[:300]}")
        return response.json()

    def start_authorization(self, state: str) -> str:
        """Demarre l'autorisation chez la banque ; retourne l'URL ou envoyer
        l'utilisateur. `state` revient tel quel a redirect_url (protection
        contre les faux retours, voir BankAccounts)."""
        valid_until = datetime.now(timezone.utc) + timedelta(days=self.valid_days)
        data = self._request(
            "POST",
            "/auth",
            json={
                "access": {"valid_until": valid_until.strftime("%Y-%m-%dT%H:%M:%SZ")},
                "aspsp": {"name": self.aspsp_name, "country": self.aspsp_country},
                "state": state,
                "redirect_url": self.redirect_url,
                "psu_type": self.psu_type,
                "language": "fr",
            },
        )
        return data["url"]

    def create_session(self, code: str) -> dict:
        """Echange le code recu au retour de la banque contre une session
        (session_id, accounts, access.valid_until...)."""
        return self._request("POST", "/sessions", json={"code": code})

    def get_balances(self, account_uid: str) -> list[dict]:
        return self._request("GET", f"/accounts/{account_uid}/balances").get("balances", [])

    def get_transactions(self, account_uid: str, date_from: str, continuation_key: str | None = None) -> dict:
        params = {"date_from": date_from}
        if continuation_key:
            params["continuation_key"] = continuation_key
        return self._request("GET", f"/accounts/{account_uid}/transactions", params=params)
