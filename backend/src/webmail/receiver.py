from urllib.parse import quote

from fastapi import APIRouter, FastAPI, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from .webmail import SEND_MAX_BYTES, Webmail, WebmailError, WebmailNotFoundError


class FlagsRequest(BaseModel):
    """Corps de PUT /webmail/messages/{dossier}/{uid}/flags : lu, suivi
    (absent : inchange)."""

    seen: bool | None = None
    starred: bool | None = None


class MoveRequest(BaseModel):
    """Corps de POST /webmail/messages/{dossier}/{uid}/move : to = inbox,
    archive, trash ou spam."""

    to: str


class WebmailReceiver:
    """Recoit les requetes REST (FastAPI) et delegue a Webmail.

    Monte sur le routeur protege par require_accounts_auth (voir
    app/main.py) : la boite de l'association n'est visible qu'avec le mot de
    passe "comptes". Routes synchrones (IMAP bloquant) : FastAPI les execute
    dans un thread a part.
    """

    def __init__(self, client: Webmail, app: FastAPI | APIRouter) -> None:
        self.client = client
        self.app = app
        self._register_routes()

    def _register_routes(self) -> None:
        self.app.get("/webmail/settings")(self.getSettings)
        self.app.get("/webmail/folders")(self.getFolders)
        self.app.get("/webmail/unread")(self.getUnread)
        self.app.get("/webmail/messages")(self.listMessages)
        self.app.get("/webmail/messages/{folder}/{uid}")(self.getMessage)
        self.app.get("/webmail/messages/{folder}/{uid}/attachments/{index}")(self.getAttachment)
        self.app.put("/webmail/messages/{folder}/{uid}/flags")(self.setFlags)
        self.app.post("/webmail/messages/{folder}/{uid}/move")(self.moveMessage)
        self.app.delete("/webmail/messages/{folder}/{uid}")(self.deleteMessage)
        self.app.post("/webmail/send")(self.sendMessage)

    def _call(self, action, *args, **kwargs):
        try:
            return action(*args, **kwargs)
        except WebmailError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except WebmailNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Message introuvable (déplacé ou supprimé ?)") from exc

    def getSettings(self) -> dict:
        """Endpoint REST GET /webmail/settings : boite configuree ? adresse."""
        return self.client.settings()

    def getFolders(self) -> dict:
        """Endpoint REST GET /webmail/folders : dossiers de la boite, non lus
        de la reception."""
        return self._call(self.client.folders)

    def getUnread(self) -> dict:
        """Endpoint REST GET /webmail/unread : non lus de la reception
        (pastille de l'onglet). 0 si la boite n'est pas configuree."""
        if not self.client.configured:
            return {"unread": 0}
        return {"unread": self._call(self.client.unread)}

    def listMessages(self, folder: str = "inbox", before: int | None = None, q: str = "") -> dict:
        """Endpoint REST GET /webmail/messages?folder=&before=&q= : page de
        messages (q : recherche, syntaxe Gmail)."""
        return self._call(self.client.list, folder, before, q)

    def getMessage(self, folder: str, uid: int) -> dict:
        """Endpoint REST GET /webmail/messages/{dossier}/{uid} : message
        complet, marque comme lu."""
        return self._call(self.client.get, folder, uid)

    def getAttachment(self, folder: str, uid: int, index: int) -> Response:
        """Endpoint REST GET /webmail/messages/{dossier}/{uid}/attachments/{n} :
        piece jointe, toujours en telechargement (jamais affichee par le
        navigateur sur le domaine de l'appli)."""
        data, filename, _content_type = self._call(self.client.attachment, folder, uid, index)
        ascii_name = filename.encode("ascii", "replace").decode("ascii").replace('"', "_").replace("?", "_")
        return Response(
            data,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}",
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "no-store",
            },
        )

    def setFlags(self, folder: str, uid: int, request: FlagsRequest) -> dict:
        return self._call(self.client.set_flags, folder, uid, request.seen, request.starred)

    def moveMessage(self, folder: str, uid: int, request: MoveRequest) -> dict:
        return self._call(self.client.move, folder, uid, request.to)

    def deleteMessage(self, folder: str, uid: int) -> dict:
        """Endpoint REST DELETE /webmail/messages/{dossier}/{uid} : suppression
        definitive (corbeille ou spam seulement)."""
        return self._call(self.client.delete, folder, uid)

    async def sendMessage(
        self,
        to: str = Form(""),
        cc: str = Form(""),
        bcc: str = Form(""),
        subject: str = Form(""),
        body: str = Form(""),
        inReplyTo: str = Form(""),
        references: str = Form(""),
        answeredFolder: str = Form(""),
        answeredUid: int | None = Form(None),
        forwardFolder: str = Form(""),
        forwardUid: int | None = Form(None),
        files: list[UploadFile] | None = None,
    ) -> dict:
        """Endpoint REST POST /webmail/send (formulaire multipart) : envoie un
        mail depuis la boite. Reponse : answered* (message repondu, marque
        "repondu") ; transfert : forward* (pieces jointes reprises)."""
        attachments = []
        total = 0
        for upload in files or []:
            data = await upload.read()
            total += len(data)
            if total > SEND_MAX_BYTES:
                raise HTTPException(status_code=400, detail="Pièces jointes trop lourdes (18 Mo au total au maximum)")
            attachments.append((upload.filename or "piece-jointe", upload.content_type or "", data))
        # IMAP et SMTP bloquants : hors de la boucle d'evenements.
        return await run_in_threadpool(
            self._call,
            self.client.send,
            to=to,
            cc=cc,
            bcc=bcc,
            subject=subject,
            body=body,
            in_reply_to=inReplyTo,
            references=references,
            attachments=attachments,
            forward=(forwardFolder, forwardUid) if forwardFolder and forwardUid is not None else None,
            answered=(answeredFolder, answeredUid) if answeredFolder and answeredUid is not None else None,
        )
