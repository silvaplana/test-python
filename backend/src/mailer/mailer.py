"""Envoi de mails via l'API "transactionnelle" de Brevo (https://brevo.com,
gratuit jusqu'a 300 mails par jour).

Configuration (backend/.env) : BREVO_API_KEY, MAIL_SENDER (adresse
d'expedition, sur un domaine verifie chez Brevo -- ex: essai@silvaplana.cloud),
MAIL_SENDER_NAME, MAIL_REPLY_TO (ou arrivent les reponses des destinataires).
Sans BREVO_API_KEY : aucun mail n'est envoye (send retourne False), pratique
en developpement local.
"""

from __future__ import annotations

import base64

import httpx


class MailError(RuntimeError):
    """Levee quand Brevo refuse le mail ou est injoignable."""


class Mailer:
    API_URL = "https://api.brevo.com/v3/smtp/email"

    def __init__(self, api_key: str, sender: str, sender_name: str, reply_to: str | None = None) -> None:
        self.api_key = api_key
        self.sender = sender
        self.sender_name = sender_name
        self.reply_to = reply_to

    @property
    def enabled(self) -> bool:
        return bool(self.api_key and self.sender)

    def send(
        self,
        to_email: str,
        to_name: str,
        subject: str,
        html: str,
        attachments: list[tuple[str, bytes]] | None = None,
    ) -> bool:
        """Envoie un mail HTML (+ pieces jointes : couples (nom, contenu)).
        Retourne False sans rien faire si le mailer n'est pas configure ;
        leve MailError si Brevo refuse."""
        if not self.enabled:
            print(f"Mailer non configuré : mail « {subject} » non envoyé à {to_email}")
            return False
        payload = {
            "sender": {"email": self.sender, "name": self.sender_name},
            "to": [{"email": to_email, "name": to_name}],
            "subject": subject,
            "htmlContent": html,
        }
        if self.reply_to:
            payload["replyTo"] = {"email": self.reply_to}
        if attachments:
            payload["attachment"] = [
                {"name": name, "content": base64.b64encode(content).decode("ascii")} for name, content in attachments
            ]
        try:
            response = httpx.post(self.API_URL, json=payload, headers={"api-key": self.api_key}, timeout=20)
        except httpx.HTTPError as exc:
            raise MailError(f"Brevo injoignable : {exc}") from exc
        if response.status_code >= 400:
            raise MailError(f"Brevo {response.status_code} : {response.text[:300]}")
        return True
