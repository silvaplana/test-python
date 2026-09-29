import base64
import binascii
import time
from collections import defaultdict, deque

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile as StarletteUploadFile

from mailer import MailError

from . import content
from .trials import MAX_FAMILY_SIZE, RegistrationError, Trials


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


def _checked(value) -> bool:
    """Case a cocher du formulaire ("true"/"on"/"1") -> booleen."""
    return str(value or "").lower() in ("true", "on", "1")


class TrialsPublicReceiver:
    """Routes PUBLIQUES (sans mot de passe) de la page d'inscription au cours
    d'essai. Montees directement sur l'app (pas sur le routeur protege, voir
    app/main.py) : a garder minimales -- lire les textes, s'inscrire."""

    def __init__(self, client: Trials, app: FastAPI | APIRouter) -> None:
        self.client = client
        self.app = app
        self.limiter = RateLimiter(limit=10, window_seconds=3600)
        self._register_routes()

    def _register_routes(self) -> None:
        self.app.get("/public/trials/info")(self.getInfo)
        self.app.post("/public/trials/register")(self.register)

    def getInfo(self) -> dict:
        """Endpoint REST GET /public/trials/info. Textes de la page
        (modalites, horaires, lieux, decharge...), voir trials/content.py."""
        return content.public_info()

    async def register(self, request: Request) -> dict:
        """Endpoint REST POST /public/trials/register (formulaire multipart :
        un certificat medical par personne). Champs communs : email,
        termsVersion, signature (1re personne), parentSignatureName{k} +
        parentSignature{k} (representants legaux exterieurs), website ; par
        personne i (0 a 2) : firstName{i}, lastName{i}, minor{i}, age{i},
        waiverAccepted{i}, certificate{i}, parentIsFirst{i},
        parentFirstName{i}, parentLastName{i}.

        Retourne {"people": [{"status": "created", "firstName", "lastName",
        "qrPng" (base64)} ou {"status": "existing", "firstName", "lastName"}],
        "emailSent"} -- une personne deja inscrite ne voit pas son QR code a
        l'ecran, il est seulement renvoye par mail (voir Trials.register).
        422 avec un message lisible si incomplet."""
        form = await request.form()
        # "website" : champ invisible pour un humain (piege a robots) -- s'il
        # est rempli, on fait comme si tout allait bien sans rien enregistrer.
        if form.get("website"):
            return {"people": [], "emailSent": False}
        if not self.limiter.allow(client_ip(request)):
            raise HTTPException(status_code=429, detail="Trop d'inscriptions depuis cette connexion, réessayez plus tard")
        people = []
        for i in range(MAX_FAMILY_SIZE):
            if f"firstName{i}" not in form:
                break
            certificate = form.get(f"certificate{i}")
            people.append(
                {
                    "first_name": form.get(f"firstName{i}", ""),
                    "last_name": form.get(f"lastName{i}", ""),
                    "minor": _checked(form.get(f"minor{i}")),
                    "age": form.get(f"age{i}", ""),
                    "waiver_accepted": _checked(form.get(f"waiverAccepted{i}")),
                    "certificate": (certificate.filename, await certificate.read())
                    if isinstance(certificate, StarletteUploadFile) and certificate.filename
                    else None,
                    "parent_is_first": _checked(form.get(f"parentIsFirst{i}")),
                    "parent_first_name": form.get(f"parentFirstName{i}", ""),
                    "parent_last_name": form.get(f"parentLastName{i}", ""),
                }
            )
        parent_signatures = [
            (form.get(f"parentSignatureName{k}", ""), _decode_signature(form.get(f"parentSignature{k}", "")))
            for k in range(MAX_FAMILY_SIZE)
            if f"parentSignatureName{k}" in form
        ]
        try:
            registrations = await run_in_threadpool(
                self.client.register,
                {"email": form.get("email", ""), "terms_version": form.get("termsVersion", "")},
                people,
                _decode_signature(form.get("signature", "")),
                parent_signatures,
                client_ip(request),
            )
        except RegistrationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        try:
            email_sent = await run_in_threadpool(self.client.send_confirmation, registrations)
        except MailError as exc:
            print(f"register: mail de confirmation non envoyé ({exc})")
            email_sent = False
        return {
            "people": [
                {
                    "status": r["status"],
                    "firstName": r["student"]["firstName"],
                    "lastName": r["student"]["lastName"],
                    **(
                        {"qrPng": base64.b64encode(self.client.qr_png(r["token"])).decode("ascii")}
                        if r["status"] == "created"
                        else {}
                    ),
                }
                for r in registrations
            ],
            "emailSent": email_sent,
        }
