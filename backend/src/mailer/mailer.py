"""Envoi de mails par SMTP (ex: un compte Gmail avec un "mot de passe
d'application").

Configuration (backend/.env) : SMTP_HOST, SMTP_PORT, SMTP_USER,
SMTP_PASSWORD, MAIL_SENDER (adresse d'expedition -- avec Gmail, celle du
compte), MAIL_SENDER_NAME, MAIL_REPLY_TO (ou arrivent les reponses des
destinataires, ex: l'adresse du club). Sans SMTP_USER/SMTP_PASSWORD : aucun
mail n'est envoye (send retourne False), pratique en developpement local.

Gmail : https://myaccount.google.com/apppasswords (validation en 2 etapes
requise), SMTP_HOST=smtp.gmail.com, SMTP_PORT=587 -- 500 mails par jour max.
"""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid


class MailError(RuntimeError):
    """Levee quand le serveur SMTP refuse le mail ou est injoignable."""


class Mailer:
    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        sender: str,
        sender_name: str,
        reply_to: str | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.sender = sender or user
        self.sender_name = sender_name
        self.reply_to = reply_to

    @property
    def enabled(self) -> bool:
        return bool(self.host and self.user and self.password)

    def send(
        self,
        to_email: str,
        to_name: str,
        subject: str,
        html: str,
        text: str,
        inline_images: dict[str, bytes] | None = None,
    ) -> bool:
        """Envoie un mail HTML (+ version texte pour les messageries qui
        n'affichent pas le HTML). inline_images : {cid: PNG}, images integrees
        au mail et referencees dans le HTML par src="cid:<cid>". Retourne False
        sans rien faire si le mailer n'est pas configure ; leve MailError si
        l'envoi echoue."""
        if not self.enabled:
            print(f"Mailer non configuré : mail « {subject} » non envoyé à {to_email}")
            return False
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = formataddr((self.sender_name, self.sender))
        message["To"] = formataddr((to_name, to_email))
        if self.reply_to:
            message["Reply-To"] = self.reply_to
        message["Message-ID"] = make_msgid(domain=self.sender.split("@")[-1])
        message.set_content(text)
        message.add_alternative(html, subtype="html")
        html_part = message.get_payload()[1]
        for cid, png in (inline_images or {}).items():
            html_part.add_related(png, maintype="image", subtype="png", cid=f"<{cid}>", filename=f"{cid}.png")
        try:
            with smtplib.SMTP(self.host, self.port, timeout=20) as smtp:
                smtp.starttls(context=ssl.create_default_context())
                smtp.login(self.user, self.password)
                smtp.send_message(message)
        except (smtplib.SMTPException, OSError) as exc:
            raise MailError(f"Envoi du mail impossible : {exc}") from exc
        return True
