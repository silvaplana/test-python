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

from .mails import normalize_phone

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


class MemberSmsRequest(BaseModel):
    """Corps de POST /helloasso/members/{id}/sms : texte du SMS prepare."""

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

    def enable_member_mail(self, mailer, contact: str | None, sender: str | None, journal=None, sms_journal=None) -> None:
        """Active l'envoi d'un mail a un adherent (POST
        /helloasso/members/{id}/mail). mailer : voir mailer/mailer.py ;
        contact : adresse de l'association, mise en copie et en adresse de
        reponse ; sender : adresse d'expedition de ces mails ; journal :
        trace des mails envoyes (helloasso.mails.MemberMails). Appele par
        app/main.py une fois le mailer cree."""
        self.mailer = mailer
        self.journal = journal
        # SMS prepares (helloasso.mails.MemberSms) : envoyes par l'appli SMS
        # du telephone de l'utilisateur, voir prepareMemberSms.
        self.sms_journal = sms_journal
        if sms_journal is not None:
            self.app.post("/helloasso/members/{item_id}/sms")(self.prepareMemberSms)
            self.app.get("/helloasso/sms")(self.getSms)
            self.app.get("/helloasso/sms-counts")(self.getSmsCounts)
            self.app.get("/helloasso/members/{item_id}/sms")(self.getMemberSms)
        self.contact = contact or None
        self.mail_sender = sender or None
        self.app.get("/helloasso/mail-settings")(self.getMailSettings)
        self.app.post("/helloasso/members/{item_id}/mail")(self.sendMemberMail)
        self.app.get("/helloasso/mails")(self.getMails)
        self.app.get("/helloasso/mail-counts")(self.getMailCounts)
        self.app.get("/helloasso/members/{item_id}/mails")(self.getMemberMails)

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
        sender = self.mail_sender or self.mailer.sender
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
            # L'echec est garde aussi : on sait qu'un mail n'est pas parti.
            if self.journal is not None:
                self.journal.record(member, to_email, self.contact, sender, subject, text, error=str(exc))
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        if self.journal is not None:
            self.journal.record(member, to_email, self.contact, sender, subject, text)
        print(f"HelloAsso.sendMemberMail: mail « {subject} » envoye a l'adherent {item_id}")
        return {"sent": True, "to": to_email, "cc": self.contact}

    def _member_phone(self, item_id: int) -> tuple[dict, str | None]:
        """Adherent et son numero de telephone HelloAsso (reponse au champ
        "Numéro de téléphone" du formulaire), pret pour un lien "sms:"."""
        member = self.client.get_member_detail(self.form_slug, item_id, self.form_type)
        if member is None:
            raise HTTPException(status_code=404, detail="Adhérent inconnu")
        answer = next((f["answer"] for f in member["fields"] if f.get("type") == "Phone" or "téléphone" in (f.get("name") or "").lower()), None)
        return member, normalize_phone(answer)

    def prepareMemberSms(self, item_id: int, request: MemberSmsRequest) -> dict:
        """Endpoint REST POST /helloasso/members/{id}/sms : note qu'un SMS a
        ete prepare pour cet adherent. Le SMS lui-meme part de l'appli SMS du
        telephone de l'utilisateur (lien "sms:" ouvert par l'ecran) : le
        serveur n'envoie rien et ne peut pas savoir s'il est parti."""
        text = request.message.strip()
        if not text:
            raise HTTPException(status_code=400, detail="Le message est obligatoire")
        member, phone = self._member_phone(item_id)
        if phone is None:
            raise HTTPException(status_code=400, detail="Cet adhérent n'a pas de numéro de téléphone chez HelloAsso")
        return self.sms_journal.record(member, phone, text)

    def getSms(self) -> list[dict]:
        """Endpoint REST GET /helloasso/sms : tous les SMS prepares, le plus
        recent d'abord."""
        return self.sms_journal.list()

    def getSmsCounts(self) -> dict[int, int]:
        """Endpoint REST GET /helloasso/sms-counts : nombre de SMS prepares
        pour chaque adherent (pastille du bouton SMS)."""
        return self.sms_journal.counts()

    def getMemberSms(self, item_id: int) -> list[dict]:
        """Endpoint REST GET /helloasso/members/{id}/sms : SMS prepares pour
        cet adherent, le plus recent d'abord."""
        return self.sms_journal.list(item_id)

    def enable_member_checks(self, checks) -> None:
        """Active la verification par IA des dossiers (checks :
        helloasso.verification.MemberChecks). Lancer une verification ou
        valider un dossier a la main est reserve au mot de passe "comptes"
        (les appels a l'IA sont payants)."""
        self.checks = checks
        admin = [Depends(require_accounts_auth)]
        self.app.get("/helloasso/checks")(self.getChecks)
        self.app.post("/helloasso/checks/run", dependencies=admin)(self.runChecks)
        self.app.put("/helloasso/checks/{member_id}/ok", dependencies=admin)(self.markCheckOk)
        self.app.post("/helloasso/checks/report", dependencies=admin)(self.sendChecksReport)

    def getChecks(self) -> dict:
        """Endpoint REST GET /helloasso/checks : statut de verification de
        chaque adherent, cout cumule de l'IA et avancement de la verification
        en cours (voir MemberChecks.state), relu par l'ecran toutes les 2 s
        pendant une verification."""
        return self.checks.state()

    def runChecks(self) -> dict:
        """Endpoint REST POST /helloasso/checks/run : verifie par IA, en
        arriere-plan, les adherents dont le dossier n'est pas deja bon."""
        try:
            return self.checks.run()
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"HelloAsso injoignable : {exc}") from exc

    def sendChecksReport(self) -> dict:
        """Endpoint REST POST /helloasso/checks/report : envoie a
        l'association (CONTACT_ASSOCIATION) un mail qui recapitule tous les
        dossiers a regarder, adherent par adherent."""
        if not self.contact:
            raise HTTPException(status_code=400, detail="L'adresse de l'association (CONTACT_ASSOCIATION) n'est pas configurée")
        if not self.mailer.enabled:
            raise HTTPException(status_code=503, detail="L'envoi de mails n'est pas configuré sur le serveur")
        try:
            problems = self.checks.problems()
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"HelloAsso injoignable : {exc}") from exc
        if not problems:
            raise HTTPException(status_code=400, detail="Aucun dossier à signaler")
        count = len(problems)
        title = f"{count} dossier{'s' if count > 1 else ''} d'adhérent à vérifier"
        blocks = "".join(
            f"<p><b>{html.escape(p['name'])}</b></p><ul>" + "".join(f"<li>{html.escape(issue)}</li>" for issue in p["issues"]) + "</ul>"
            for p in problems
        )
        text = "\n\n".join(p["name"] + "\n" + "\n".join(f"- {issue}" for issue in p["issues"]) for p in problems)
        try:
            self.mailer.send(
                self.contact,
                "",
                f"Adhérents : {title}",
                f"<p>Vérification des dossiers HelloAsso par IA : {title}.</p>{blocks}"
                "<p>À voir dans sambo-admin, onglet HelloAsso › Adhérents.</p>",
                f"Vérification des dossiers HelloAsso par IA : {title}.\n\n{text}\n\nÀ voir dans sambo-admin, onglet HelloAsso > Adhérents.",
                sender=self.mail_sender,
            )
        except MailError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {"sent": True, "to": self.contact, "count": count}

    def markCheckOk(self, member_id: int) -> dict:
        """Endpoint REST PUT /helloasso/checks/{id}/ok : dossier valide a la
        main, qui ne sera plus reverifie."""
        try:
            self.checks.mark_ok(member_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="Adhérent inconnu") from exc
        return {"status": "ok"}

    def getMails(self) -> list[dict]:
        """Endpoint REST GET /helloasso/mails : journal de tous les mails
        envoyes aux adherents, le plus recent d'abord."""
        return self.journal.list() if self.journal is not None else []

    def getMailCounts(self) -> dict[int, int]:
        """Endpoint REST GET /helloasso/mail-counts : nombre de mails envoyes
        a chaque adherent ({identifiant HelloAsso: nombre}), pour la pastille
        du bouton Mail."""
        return self.journal.counts() if self.journal is not None else {}

    def getMemberMails(self, item_id: int) -> list[dict]:
        """Endpoint REST GET /helloasso/members/{id}/mails : mails envoyes a
        cet adherent, le plus recent d'abord."""
        return self.journal.list(item_id) if self.journal is not None else []

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
