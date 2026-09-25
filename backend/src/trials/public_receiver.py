import base64
import binascii
import time
from collections import defaultdict, deque

from fastapi import APIRouter, FastAPI, File, Form, HTTPException, Request, Response, UploadFile

from mailer import MailError

from . import content
from .trials import RegistrationError, Trials, TrialStudentNotFoundError


class RateLimiter:
    """Limite le nombre d'inscriptions par adresse IP (anti-spam) : au plus
    `limit` appels par fenetre de `window_seconds`. En memoire : remis a zero
    au redemarrage du backend, suffisant ici."""

    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._calls: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        calls = self._calls[key]
        while calls and now - calls[0] > self.window_seconds:
            calls.popleft()
        if len(calls) >= self.limit:
            return False
        calls.append(now)
        return True


def client_ip(request: Request) -> str:
    """IP du visiteur : 1re adresse de X-Forwarded-For (le Caddy "gateway"
    la remplace toujours par la vraie IP du visiteur, qui ne peut donc pas la
    falsifier -- voir frontend/Caddyfile), sinon l'IP de la connexion."""
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() or (request.client.host if request.client else "")


def _decode_signature(data_url: str) -> bytes:
    """"data:image/png;base64,..." (canvas de la page) -> octets PNG."""
    _, _, encoded = data_url.partition("base64,")
    try:
        return base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        return b""


class TrialsPublicReceiver:
    """Routes PUBLIQUES (sans mot de passe) de la page d'inscription au cours
    d'essai. Montees directement sur l'app (pas sur le routeur protege, voir
    app/main.py) : a garder minimales -- lire les textes, s'inscrire, afficher
    l'image d'un QR code dont on connait le jeton."""

    def __init__(self, client: Trials, app: FastAPI | APIRouter) -> None:
        self.client = client
        self.app = app
        self.limiter = RateLimiter(limit=10, window_seconds=3600)
        self._register_routes()

    def _register_routes(self) -> None:
        self.app.get("/public/trials/info")(self.getInfo)
        self.app.post("/public/trials/register")(self.register)
        self.app.get("/public/trials/qr/{token}.png")(self.getQrPng)

    def getInfo(self) -> dict:
        """Endpoint REST GET /public/trials/info. Textes de la page
        (modalites, horaires, lieux, decharge...), voir trials/content.py."""
        return content.public_info()

    def register(
        self,
        request: Request,
        firstName: str = Form(""),
        lastName: str = Form(""),
        birthDate: str = Form(""),
        gender: str = Form(""),
        email: str = Form(""),
        phone: str = Form(""),
        parentName: str = Form(""),
        medicalAttestation: bool = Form(False),
        parentalConsent: bool = Form(False),
        waiverAccepted: bool = Form(False),
        termsVersion: str = Form(""),
        signature: str = Form(""),
        website: str = Form(""),
        certificate: UploadFile | None = File(None),
    ) -> dict:
        """Endpoint REST POST /public/trials/register (formulaire multipart,
        pour le fichier du certificat). Retourne {"status": "created",
        "qrPng" (base64), "emailSent"} ou {"status": "existing", "emailSent"}
        -- dans ce 2e cas, le QR code n'est envoye que par mail (voir
        Trials.register). 422 avec un message lisible si incomplet."""
        # "website" : champ invisible pour un humain (piege a robots) -- s'il
        # est rempli, on fait comme si tout allait bien sans rien enregistrer.
        if website:
            return {"status": "created", "qrPng": None, "emailSent": False}
        if not self.limiter.allow(client_ip(request)):
            raise HTTPException(status_code=429, detail="Trop d'inscriptions depuis cette connexion, réessayez plus tard")
        form = {
            "first_name": firstName,
            "last_name": lastName,
            "birth_date": birthDate,
            "gender": gender or None,
            "email": email,
            "phone": phone,
            "parent_name": parentName,
            "medical_attestation": medicalAttestation,
            "parental_consent": parentalConsent,
            "waiver_accepted": waiverAccepted,
            "terms_version": termsVersion,
        }
        certificate_file = None
        if certificate is not None and certificate.filename:
            certificate_file = (certificate.filename, certificate.file.read())
        try:
            result = self.client.register(form, _decode_signature(signature), certificate_file, client_ip(request))
        except RegistrationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        try:
            email_sent = self.client.send_confirmation(result["student"], result["token"])
        except MailError as exc:
            print(f"register: mail de confirmation non envoyé ({exc})")
            email_sent = False
        if result["status"] == "existing":
            return {"status": "existing", "emailSent": email_sent}
        return {
            "status": "created",
            "firstName": result["student"]["firstName"],
            "lastName": result["student"]["lastName"],
            "qrPng": base64.b64encode(self.client.qr_png(result["token"])).decode("ascii"),
            "emailSent": email_sent,
        }

    def getQrPng(self, token: str) -> Response:
        """Endpoint REST GET /public/trials/qr/{jeton}.png. Image du QR code,
        affichee dans le mail de confirmation (404 si jeton inconnu)."""
        try:
            png = self.client.qr_png(token)
        except TrialStudentNotFoundError as exc:
            raise HTTPException(status_code=404, detail="QR code inconnu") from exc
        return Response(content=png, media_type="image/png", headers={"Cache-Control": "private, max-age=86400"})
