import html
import re
from datetime import datetime
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from auth import require_accounts_auth
from mailer import MailError

from .helloasso import HelloAsso, HelloAssoAuthError
from .summary import FAILED_PAYMENT_STATES, cancellation_preview, members_summary

# Restreint /helloasso/photo aux URL HelloAsso reelles (voir getPhoto) :
# sans ca, ce endpoint deviendrait un proxy HTTP generique authentifie
# avec les identifiants du club, un risque de securite (SSRF) pour un
# gain nul (aucun autre hote n'a besoin de ce relais).
PHOTO_URL_PATH_RE = re.compile(r"^/customFieldsAnswer/\d+$")


class MemberMailRequest(BaseModel):
    """Corps de POST /helloasso/members/{id}/mail : objet et texte du mail
    ecrit dans l'ecran. Le destinataire n'en fait pas partie : c'est
    l'adresse de l'adherent chez HelloAsso."""

    subject: str
    message: str


class HelloAssoReceiver:
    """Recoit les requetes REST (FastAPI) et delegue a HelloAsso.

    Contrairement a MotorReceiver, ne cree pas sa propre app FastAPI : les
    routes sont enregistrees sur une app existante (partagee avec les autres
    modules du backend), pour ne faire tourner qu'un seul service HTTP.

    app est en realite le routeur protege par require_auth (voir
    app/main.py), pas l'app FastAPI elle-meme -- FastAPI | APIRouter
    plutot que juste FastAPI, meme s'ils partagent l'interface utilisee
    ici (.get/.post/.delete).
    """

    def __init__(
        self,
        client: HelloAsso,
        app: FastAPI | APIRouter,
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
        self.app.get("/helloasso/summary")(self.getSummary)
        # Resiliation d'une commande : action irreversible, reservee au mot
        # de passe "comptes" (en plus de la session exigee par le routeur).
        admin = [Depends(require_accounts_auth)]
        self.app.get("/helloasso/orders/{order_id}/cancellation", dependencies=admin)(self.getCancellation)
        self.app.post("/helloasso/orders/{order_id}/cancel", dependencies=admin)(self.cancelOrder)
        self.app.get("/helloasso/photo")(self.getPhoto)
        self.app.get("/helloasso/document")(self.getDocument)
        self.app.get("/helloasso/members/{item_id}")(self.getMember)

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

    def getSummary(self) -> dict:
        """Endpoint REST GET /helloasso/summary. Chiffres des adherents de la
        campagne : majeurs et mineurs, prix moyen de la licence, et ce qui
        reste a encaisser mois par mois (voir members_summary)."""
        return members_summary(
            self.client.get_members(self.form_slug, self.form_type),
            self.client.get_member_payments(self.form_slug, self.form_type),
            datetime.now(ZoneInfo("Europe/Paris")).date(),
        )

    def _order(self, order_id: int) -> dict:
        """Commande du formulaire d'adhesion du club (404 sinon : on ne
        resilie que ses propres commandes)."""
        for order in self.client.get_form_orders(self.form_slug, self.form_type):
            if order.get("id") == order_id:
                return order
        raise HTTPException(status_code=404, detail="Commande inconnue")

    def getCancellation(self, order_id: int) -> dict:
        """Endpoint REST GET /helloasso/orders/{id}/cancellation : ce que la
        resiliation de cette commande changerait (voir cancellation_preview),
        a afficher avant de confirmer."""
        return cancellation_preview(self._order(order_id))

    def cancelOrder(self, order_id: int) -> dict:
        """Endpoint REST POST /helloasso/orders/{id}/cancel : resilie la
        commande chez HelloAsso (tous ses adherents, echeances a venir
        annulees, rien de rembourse -- voir HelloAsso.cancel_order).
        Retourne l'etat de la commande relu apres coup."""
        before = cancellation_preview(self._order(order_id))
        if before["canceled"]:
            raise HTTPException(status_code=400, detail="Cette commande est déjà résiliée")
        try:
            self.client.cancel_order(order_id)
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=502, detail=f"HelloAsso a refusé la résiliation ({exc.response.status_code}) : {exc.response.text[:300]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"HelloAsso injoignable : {exc}") from exc
        return cancellation_preview(self._order(order_id))

    def enable_member_mail(self, mailer, contact: str | None, sender: str | None) -> None:
        """Active l'envoi d'un mail a un adherent (POST
        /helloasso/members/{id}/mail). mailer : voir mailer/mailer.py ;
        contact : adresse de l'association, mise en copie et en adresse de
        reponse ; sender : adresse d'expedition de ces mails. Appele par
        app/main.py une fois le mailer cree."""
        self.mailer = mailer
        self.contact = contact or None
        self.mail_sender = sender or None
        self.app.get("/helloasso/mail-settings")(self.getMailSettings)
        self.app.post("/helloasso/members/{item_id}/mail")(self.sendMemberMail)

    def getMailSettings(self) -> dict:
        """Endpoint REST GET /helloasso/mail-settings : ce que l'ecran affiche
        avant l'envoi d'un mail (expediteur, copie, envoi possible ou non)."""
        return {"enabled": self.mailer.enabled, "sender": self.mail_sender or self.mailer.sender, "contact": self.contact}

    def sendMemberMail(self, item_id: int, request: MemberMailRequest) -> dict:
        """Endpoint REST POST /helloasso/members/{id}/mail : envoie a un
        adherent le mail ecrit dans l'ecran. Destinataire : son adresse chez
        HelloAsso (celle du payeur), relue ici -- jamais une adresse fournie
        par l'ecran, pour que cette route ne serve pas a ecrire a n'importe
        qui. L'association est en copie et recoit les reponses."""
        subject, text = request.subject.strip(), request.message.strip()
        if not subject or not text:
            raise HTTPException(status_code=400, detail="L'objet et le message sont obligatoires")
        if "\n" in subject or "\r" in subject:
            raise HTTPException(status_code=400, detail="L'objet doit tenir sur une ligne")
        member = self.client.get_member_detail(self.form_slug, item_id, self.form_type)
        if member is None:
            raise HTTPException(status_code=404, detail="Adhérent inconnu")
        to_email = (member["payer"].get("email") or "").strip()
        if not to_email:
            raise HTTPException(status_code=400, detail="Cet adhérent n'a pas d'adresse e-mail chez HelloAsso")
        if not self.mailer.enabled:
            raise HTTPException(status_code=503, detail="L'envoi de mails n'est pas configuré sur le serveur")
        paragraphs = "".join(
            f"<p>{html.escape(block).replace(chr(10), '<br>')}</p>" for block in re.split(r"\n\s*\n", text) if block.strip()
        )
        try:
            self.mailer.send(
                to_email,
                f"{member['firstName']} {member['lastName']}",
                subject,
                paragraphs,
                text,
                cc=self.contact,
                reply_to=self.contact,
                sender=self.mail_sender,
            )
        except MailError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        print(f"HelloAsso.sendMemberMail: mail « {subject} » envoye a l'adherent {item_id}")
        return {"sent": True, "to": to_email, "cc": self.contact}

    def getMember(self, item_id: int) -> dict:
        """Endpoint REST GET /helloasso/members/{id} : toutes les informations
        HelloAsso d'un adherent (voir HelloAsso.get_member_detail), pour sa
        fiche dans l'onglet Adherents."""
        member = self.client.get_member_detail(self.form_slug, item_id, self.form_type)
        if member is None:
            raise HTTPException(status_code=404, detail="Adhérent inconnu")
        return member

    @staticmethod
    def _check_file_url(url: str) -> None:
        """Refuse (400) toute URL qui n'est pas un fichier depose dans un
        formulaire HelloAsso (docs.helloasso.com, voir PHOTO_URL_PATH_RE) :
        sans cette restriction, les relais /helloasso/photo et /document
        authentifieraient n'importe quelle URL avec les identifiants du club
        (SSRF)."""
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc != "docs.helloasso.com" or not PHOTO_URL_PATH_RE.match(parsed.path):
            raise HTTPException(status_code=400, detail="URL de fichier invalide")

    def getDocument(self, url: str) -> Response:
        """Endpoint REST GET /helloasso/document?url=... : relaie (avec
        authentification) un fichier depose par un adherent -- certificat
        medical, autorisation parentale, photo d'origine -- tel qu'il a ete
        envoye (image ou PDF), pour l'afficher depuis sa fiche. Meme
        restriction d'URL que /helloasso/photo. Pas de cache navigateur
        partage : ce sont des documents personnels."""
        self._check_file_url(url)
        try:
            content, media_type = self.client.get_document(url)
        except HelloAssoAuthError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Échec de récupération du fichier : {exc}") from exc
        return Response(
            content=content,
            media_type=media_type,
            headers={"Content-Disposition": "inline", "Cache-Control": "private, no-store"},
        )

    def getPhoto(self, url: str, size: int = Query(default=128, ge=32, le=640)) -> Response:
        """Endpoint REST GET /helloasso/photo?url=...&size=... . Relaie (avec
        authentification) une photo hebergee par HelloAsso -- typiquement
        customFields["photo d'identité"] d'un adherent, deja presente
        telle quelle dans la reponse de /helloasso/members. Le navigateur
        ne peut pas la charger directement (401 sans le jeton OAuth2 du
        club, confirme en conditions reelles).

        url doit pointer vers docs.helloasso.com (voir PHOTO_URL_PATH_RE) :
        sans cette restriction, ce endpoint authentifierait n'importe
        quelle URL fournie avec les identifiants du club (SSRF).

        size (128 par defaut, vignette du tableau) : voir MemberPhoto cote
        frontend, qui redemande une taille plus grande au clic ("zoom").
        Bornes (32-640) : evite qu'une taille absurde fasse redimensionner
        inutilement une image demesuree.
        """
        self._check_file_url(url)
        try:
            thumbnail = self.client.get_photo_thumbnail(url, size=size)
        except HelloAssoAuthError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Échec de récupération de la photo : {exc}") from exc
        # Cache navigateur genereux (photo statique une fois uploadee) :
        # evite de re-solliciter ce relais (et HelloAsso) a chaque
        # rafraichissement du tableau des adherents.
        return Response(content=thumbnail, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})
