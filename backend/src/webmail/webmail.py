"""Boite mail de l'association (onglet Messagerie > Mail), facon Gmail.

La boite reste sur Gmail : l'appli la lit en IMAP (imap.gmail.com) et envoie
en SMTP (smtp.gmail.com), avec un mot de passe d'application Google
(WEBMAIL_APP_PASSWORD, compte avec validation en deux etapes). Rien n'est
copie en base : chaque requete ouvre sa propre connexion IMAP.

Dossiers : reperes par leur role IMAP (SPECIAL-USE : \\Sent, \\Trash...)
plutot que par leur nom, qui depend de la langue du compte Gmail ("[Gmail]/
Messages envoyes"...). L'ecran ne connait que des cles (inbox, sent...) :
aucun nom de dossier ne vient du navigateur.

Messages reperes par (dossier, UID IMAP). Les pieces jointes sont numerotees
dans l'ordre des feuilles du message (voir _leaves).
"""

import base64
import html
import imaplib
import mimetypes
import quopri
import re
import smtplib
import ssl
import threading
import time
from datetime import datetime, timezone
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import formataddr, formatdate, getaddresses, make_msgid, parsedate_to_datetime

# Dossiers proposes a l'ecran, dans l'ordre : cle, libelle, role IMAP
# (SPECIAL-USE), noms essayes a defaut (serveurs sans SPECIAL-USE).
FOLDERS = [
    ("inbox", "Boîte de réception", None, ("INBOX",)),
    ("starred", "Suivis", "\\Flagged", ("Starred", "Flagged")),
    ("sent", "Envoyés", "\\Sent", ("Sent", "Sent Messages", "Sent Items")),
    ("drafts", "Brouillons", "\\Drafts", ("Drafts",)),
    ("spam", "Spam", "\\Junk", ("Spam", "Junk")),
    ("trash", "Corbeille", "\\Trash", ("Trash", "Deleted Messages", "Deleted Items")),
    ("all", "Tous les messages", "\\All", ("All Mail", "Archive", "Archives")),
]

PAGE_SIZE = 40
# Debut de message lu pour la liste (en-tetes + debut du texte, pour
# l'apercu) : evite de telecharger les pieces jointes.
PREVIEW_BYTES = 16384
# Images integrees au HTML (cid:) remplacees par leur contenu jusqu'a cette
# taille ; au-dela, elles restent des pieces jointes.
INLINE_IMAGE_MAX = 3 * 1024 * 1024
# Gmail refuse les mails de plus de 25 Mo (encodage compris).
SEND_MAX_BYTES = 18 * 1024 * 1024
FOLDER_CACHE_SECONDS = 600


class WebmailError(Exception):
    """Erreur a montrer telle quelle (boite non configuree, refus de Gmail,
    requete invalide)."""


class WebmailNotFoundError(Exception):
    """Message ou piece jointe introuvable (deja deplace ou supprime)."""


def _quote(name: str) -> str:
    return '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _unquote(raw: bytes) -> str:
    text = raw.decode("utf-8", "replace").strip()
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        text = text[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return text


_LIST_LINE = re.compile(rb'^\((?P<flags>[^)]*)\) (?P<delim>"(?:[^"\\]|\\.)*"|NIL) (?P<name>.+)$')


def parse_folders(lines: list) -> dict:
    """Reponse de LIST -> {cle: nom IMAP} pour les dossiers de FOLDERS
    trouves (role SPECIAL-USE d'abord, nom ensuite). "starred" absent : vue
    des messages suivis de la boite de reception (voir Webmail._target)."""
    found = []
    for line in lines:
        if isinstance(line, tuple):  # nom envoye en litteral
            head, literal = line
            match = _LIST_LINE.match(head.rstrip() + b" " + b'"' + literal + b'"')
        elif line:
            match = _LIST_LINE.match(line)
        else:
            continue
        if not match:
            continue
        flags = {flag.lower() for flag in match["flags"].decode("ascii", "replace").split()}
        if "\\noselect" in flags or "\\nonexistent" in flags:
            continue
        found.append((flags, _unquote(match["name"])))
    folders = {}
    for key, _label, role, names in FOLDERS:
        if role:
            for flags, name in found:
                if role.lower() in flags:
                    folders[key] = name
                    break
        if key not in folders:
            for flags, name in found:
                leaf = name.rsplit("/", 1)[-1].rsplit(".", 1)[-1]
                if name.upper() == "INBOX" and key == "inbox" or leaf.lower() in {n.lower() for n in names}:
                    folders[key] = "INBOX" if key == "inbox" else name
                    break
    folders.setdefault("inbox", "INBOX")
    return folders


def parse_fetch(data: list) -> list[dict]:
    """Reponse de UID FETCH (imaplib) -> [{uid, flags, internaldate, size,
    literal}] : texte hors litteraux regroupe par message (Gmail peut placer
    UID et FLAGS avant ou apres le litteral)."""
    items = []
    current = None
    for part in data:
        if part is None:
            continue
        if isinstance(part, tuple):
            head, literal = part
            if re.match(rb"^\d+ \(", head):
                current = {"meta": head, "literals": [literal]}
                items.append(current)
            elif current is not None:
                current["meta"] += head
                current["literals"].append(literal)
        elif re.match(rb"^\d+ \(", part):
            current = {"meta": part, "literals": []}
            items.append(current)
        elif current is not None:
            current["meta"] += part
    result = []
    for item in items:
        meta = item["meta"]
        uid = re.search(rb"UID (\d+)", meta)
        if not uid:
            continue  # notification spontanee (ex: drapeaux changes ailleurs)
        flags = re.search(rb"FLAGS \(([^)]*)\)", meta)
        internal = re.search(rb'INTERNALDATE "([^"]+)"', meta)
        size = re.search(rb"RFC822\.SIZE (\d+)", meta)
        date = None
        if internal:
            parsed = imaplib.Internaldate2tuple(b'INTERNALDATE "' + internal[1] + b'"')
            if parsed:
                date = datetime.fromtimestamp(time.mktime(parsed), timezone.utc).isoformat()
        result.append({
            "uid": int(uid[1]),
            "flags": flags[1].decode("ascii", "replace").split() if flags else [],
            "internaldate": date,
            "size": int(size[1]) if size else None,
            "literal": item["literals"][0] if item["literals"] else b"",
        })
    return result


def _address_list(message, header: str) -> list[dict]:
    try:
        value = message[header]
        if value is None:
            return []
        return [
            {"name": address.display_name or "", "address": address.addr_spec}
            for address in value.addresses
            if address.addr_spec and address.addr_spec != "<>"
        ]
    except Exception:  # en-tete mal forme
        raw = message.get(header, "")
        return [{"name": name, "address": address} for name, address in getaddresses([str(raw)]) if address]


def _header(message, name: str) -> str:
    try:
        return str(message.get(name, "") or "").strip()
    except Exception:
        return ""


def _date(message, fallback: str | None) -> str | None:
    try:
        value = message.get("Date")
        if value:
            parsed = parsedate_to_datetime(str(value))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.isoformat()
    except Exception:
        pass
    return fallback


def _part_bytes(part) -> bytes:
    """Contenu decode d'une feuille, tolerant (base64 coupe dans un debut de
    message, encodage inconnu)."""
    if part.get_content_type() == "message/rfc822":
        inner = part.get_payload()
        inner = inner[0] if isinstance(inner, list) and inner else inner
        return inner.as_bytes() if hasattr(inner, "as_bytes") else b""
    encoding = str(part.get("Content-Transfer-Encoding", "")).lower().strip()
    raw = part.get_payload(decode=False)
    if isinstance(raw, list):
        return b""
    if encoding == "base64":
        # Debut de message : base64 parfois coupe, on decode ce qui est entier.
        cleaned = re.sub(r"[^A-Za-z0-9+/]", "", raw or "")
        if len(cleaned) % 4 == 1:
            cleaned = cleaned[:-1]
        cleaned += "=" * (-len(cleaned) % 4)
        try:
            return base64.b64decode(cleaned)
        except Exception:
            return b""
    if encoding == "quoted-printable":
        return quopri.decodestring((raw or "").encode("ascii", "replace"))
    try:
        data = part.get_payload(decode=True)
        return data or b""
    except Exception:
        return (raw or "").encode("utf-8", "replace")


def _part_text(part) -> str:
    data = _part_bytes(part)
    charset = part.get_content_charset() or "utf-8"
    try:
        return data.decode(charset, "replace")
    except LookupError:
        return data.decode("utf-8", "replace")


def _leaves(message) -> list:
    """Feuilles du message dans l'ordre (un mail joint, message/rfc822, compte
    pour une feuille) : leur position numerote les pieces jointes."""
    leaves = []

    def walk(part):
        if part.get_content_type() == "message/rfc822":
            leaves.append(part)
        elif part.is_multipart():
            for sub in part.get_payload():
                walk(sub)
        else:
            leaves.append(part)

    walk(message)
    return leaves


def _is_body(part) -> bool:
    return (
        part.get_content_type() in ("text/plain", "text/html")
        and part.get_content_disposition() != "attachment"
        and not part.get_filename()
    )


def html_to_text(source: str) -> str:
    text = re.sub(r"(?is)<(script|style|head)\b.*?</\1>", "", source)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|tr|li|h[1-6]|blockquote)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text).replace("\xa0", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def snippet(message) -> str:
    """Apercu de la liste : debut du texte, sur une ligne."""
    plain = html_part = None
    for part in _leaves(message):
        if not _is_body(part):
            continue
        if part.get_content_type() == "text/plain" and plain is None:
            plain = part
        elif part.get_content_type() == "text/html" and html_part is None:
            html_part = part
    try:
        if plain is not None:
            text = _part_text(plain)
        elif html_part is not None:
            text = html_to_text(_part_text(html_part))
        else:
            return ""
    except Exception:
        return ""
    # Lignes citees d'une reponse ("> ...") inutiles dans l'apercu.
    text = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith(">"))
    return re.sub(r"\s+", " ", text).strip()[:200]


def _filename(part, index: int) -> str:
    name = part.get_filename()
    if name:
        return str(name).replace("/", "_").replace("\\", "_").strip() or f"piece-jointe-{index}"
    if part.get_content_type() == "message/rfc822":
        inner = part.get_payload()
        inner = inner[0] if isinstance(inner, list) and inner else inner
        subject = _header(inner, "Subject") if inner is not None else ""
        return (re.sub(r'[\\/:*?"<>|]', "_", subject)[:80] or "message") + ".eml"
    extension = mimetypes.guess_extension(part.get_content_type()) or ""
    return f"piece-jointe-{index}{extension}"


def _content_id(part) -> str | None:
    value = part.get("Content-ID")
    if not value:
        return None
    return str(value).strip().strip("<>").strip() or None


def parse_message(raw: bytes) -> dict:
    """Message complet -> corps (HTML, texte), pieces jointes, en-tetes."""
    message = message_from_bytes(raw, policy=policy.default)
    leaves = _leaves(message)
    html_body = text_body = None
    for part in leaves:
        if not _is_body(part):
            continue
        if part.get_content_type() == "text/html" and html_body is None:
            html_body = _part_text(part)
        elif part.get_content_type() == "text/plain" and text_body is None:
            text_body = _part_text(part)

    # Images integrees (cid:) : remplacees dans le HTML par leur contenu.
    inline = set()
    if html_body:
        for index, part in enumerate(leaves):
            cid = _content_id(part)
            if not cid or part.get_content_maintype() != "image":
                continue
            if f"cid:{cid}" not in html_body:
                continue
            data = _part_bytes(part)
            if len(data) > INLINE_IMAGE_MAX:
                continue
            uri = f"data:{part.get_content_type()};base64,{base64.b64encode(data).decode('ascii')}"
            html_body = html_body.replace(f"cid:{cid}", uri)
            inline.add(index)

    attachments = []
    for index, part in enumerate(leaves):
        if index in inline or _is_body(part):
            continue
        size = len(_part_bytes(part))
        if size == 0 and not part.get_filename():
            continue
        attachments.append({
            "index": index,
            "filename": _filename(part, index),
            "contentType": part.get_content_type(),
            "size": size,
        })

    return {
        "subject": _header(message, "Subject"),
        "from": _address_list(message, "From"),
        "to": _address_list(message, "To"),
        "cc": _address_list(message, "Cc"),
        "replyTo": _address_list(message, "Reply-To"),
        "date": _date(message, None),
        "messageId": _header(message, "Message-ID"),
        "references": _header(message, "References"),
        "html": html_body,
        "text": text_body if text_body is not None else (html_to_text(html_body) if html_body else ""),
        "attachments": attachments,
    }


def attachment_from(raw: bytes, index: int) -> tuple[bytes, str, str]:
    """Piece jointe numero index (voir parse_message) : contenu, nom, type."""
    message = message_from_bytes(raw, policy=policy.default)
    leaves = _leaves(message)
    if index < 0 or index >= len(leaves) or _is_body(leaves[index]):
        raise WebmailNotFoundError()
    part = leaves[index]
    content_type = "message/rfc822" if part.get_content_type() == "message/rfc822" else part.get_content_type()
    return _part_bytes(part), _filename(part, index), content_type


def parse_recipients(value: str) -> list[str]:
    """"a@b.fr, Nom <c@d.fr>" -> adresses ; refuse ce qui n'en est pas une."""
    if not value or not value.strip():
        return []
    if "\n" in value or "\r" in value:
        raise WebmailError("Adresse invalide")
    addresses = []
    for name, address in getaddresses([value]):
        address = address.strip()
        if not re.fullmatch(r"[^@\s<>,;]+@[^@\s<>,;]+\.[^@\s<>,;]+", address):
            raise WebmailError(f"Adresse invalide : {address or name or value}")
        addresses.append(formataddr((name, address)) if name else address)
    return addresses


def build_message(
    sender: str,
    sender_name: str,
    to: str,
    cc: str = "",
    subject: str = "",
    body: str = "",
    in_reply_to: str = "",
    references: str = "",
    attachments: list[tuple[str, str, bytes]] = (),
) -> tuple[EmailMessage, list[str]]:
    """Mail a envoyer et liste de tous ses destinataires (Cci comprise,
    ajoutee par l'appelant). attachments : (nom, type, contenu)."""
    to_list = parse_recipients(to)
    cc_list = parse_recipients(cc)
    if not to_list and not cc_list:
        raise WebmailError("Indique au moins un destinataire")
    for header_value in (subject, in_reply_to, references):
        if "\n" in header_value or "\r" in header_value:
            raise WebmailError("En-tête invalide")
    message = EmailMessage()
    message["From"] = formataddr((sender_name, sender)) if sender_name else sender
    if to_list:
        message["To"] = ", ".join(to_list)
    if cc_list:
        message["Cc"] = ", ".join(cc_list)
    message["Subject"] = subject.strip()
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid(domain=sender.rsplit("@", 1)[-1])
    if in_reply_to.strip():
        message["In-Reply-To"] = in_reply_to.strip()
        message["References"] = (references.strip() + " " + in_reply_to.strip()).strip()
    message.set_content(body or "")
    total = 0
    for name, content_type, data in attachments:
        total += len(data)
        if total > SEND_MAX_BYTES:
            raise WebmailError("Pièces jointes trop lourdes (18 Mo au total au maximum)")
        if "/" not in (content_type or ""):
            content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
        maintype, subtype = content_type.split("/", 1)
        if maintype == "message":
            maintype, subtype = "application", "octet-stream"
        message.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    recipients = [address for _name, address in getaddresses(to_list + cc_list)]
    return message, recipients


class Webmail:
    def __init__(
        self,
        address: str,
        password: str,
        sender_name: str = "",
        imap_host: str = "imap.gmail.com",
        imap_port: int = 993,
        smtp_host: str = "smtp.gmail.com",
        smtp_port: int = 587,
        timeout: float = 30,
    ) -> None:
        """address / password : compte Gmail et son mot de passe
        d'application ; vides : boite non configuree. Port IMAP 993 : TLS
        direct (autre port : connexion simple, serveur de test local) ; port
        SMTP 465 : TLS direct, 587 : STARTTLS."""
        self.address = (address or "").strip()
        self.password = (password or "").replace(" ", "")
        self.sender_name = sender_name
        self.imap_host = imap_host
        self.imap_port = imap_port
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.timeout = timeout
        self._folders = None
        self._folders_at = 0.0
        self._lock = threading.Lock()

    @property
    def configured(self) -> bool:
        return bool(self.address and self.password)

    def settings(self) -> dict:
        return {"configured": self.configured, "address": self.address}

    # --- Connexion -------------------------------------------------------

    def _connect(self):
        if not self.configured:
            raise WebmailError("Boîte mail non configurée (WEBMAIL_APP_PASSWORD manquant)")
        try:
            if self.imap_port == 993:
                conn = imaplib.IMAP4_SSL(self.imap_host, self.imap_port, ssl_context=ssl.create_default_context(), timeout=self.timeout)
            else:
                conn = imaplib.IMAP4(self.imap_host, self.imap_port, timeout=self.timeout)
        except OSError as exc:
            raise WebmailError(f"Serveur mail injoignable ({exc})") from exc
        try:
            conn.login(self.address, self.password)
        except imaplib.IMAP4.error as exc:
            conn.shutdown()
            raise WebmailError(
                "Connexion refusée par Gmail : vérifie l'adresse et le mot de passe d'application"
            ) from exc
        # Capacites completes (MOVE, X-GM-EXT-1...) annoncees apres connexion.
        status, data = conn.capability()
        if status == "OK" and data and data[0]:
            conn.capabilities = tuple(data[0].decode("ascii", "replace").upper().split())
        return conn

    def _session(self):
        webmail = self

        class Session:
            def __enter__(self):
                self.conn = webmail._connect()
                return self.conn

            def __exit__(self, *_exc):
                try:
                    self.conn.logout()
                except Exception:
                    pass

        return Session()

    def _folder_names(self, conn) -> dict:
        with self._lock:
            if self._folders is not None and time.monotonic() - self._folders_at < FOLDER_CACHE_SECONDS:
                return self._folders
        status, lines = conn.list()
        folders = parse_folders(lines if status == "OK" else [])
        with self._lock:
            self._folders, self._folders_at = folders, time.monotonic()
        return folders

    def _target(self, conn, key: str) -> tuple[str, str]:
        """Cle de dossier -> (nom IMAP, critere de recherche). Sans dossier
        "Suivis" (serveur non Gmail) : messages suivis de la boite de
        reception."""
        if key not in {k for k, *_ in FOLDERS}:
            raise WebmailError("Dossier inconnu")
        folders = self._folder_names(conn)
        if key in folders:
            return folders[key], "ALL"
        if key == "starred":
            return folders["inbox"], "FLAGGED"
        raise WebmailError("Ce dossier n'existe pas dans cette boîte")

    def _select(self, conn, name: str, readonly: bool) -> None:
        status, data = conn.select(_quote(name), readonly=readonly)
        if status != "OK":
            raise WebmailError(f"Dossier illisible ({(data or [b''])[0].decode('utf-8', 'replace')})")

    def _search(self, conn, criteria: str, query: str) -> list[int]:
        if query:
            if "X-GM-EXT-1" in conn.capabilities:
                # Recherche de Gmail (memes mots-cles : from:, has:attachment...).
                conn.literal = query.encode("utf-8")
                status, data = conn.uid("SEARCH", "CHARSET", "UTF-8", "X-GM-RAW")
            else:
                conn.literal = query.encode("utf-8")
                status, data = conn.uid("SEARCH", "CHARSET", "UTF-8", criteria, "TEXT")
        else:
            status, data = conn.uid("SEARCH", None, criteria)
        if status != "OK":
            raise WebmailError("Recherche refusée par le serveur")
        return sorted(int(uid) for uid in b" ".join(part for part in data if part).split())

    def _fetch(self, conn, uids: list[int], items: str) -> list[dict]:
        if not uids:
            return []
        status, data = conn.uid("FETCH", ",".join(str(uid) for uid in uids), items)
        if status != "OK":
            raise WebmailError("Lecture refusée par le serveur")
        return parse_fetch(data)

    # --- Lecture ---------------------------------------------------------

    def folders(self) -> dict:
        """Dossiers presents dans la boite et nombre de non lus de la
        reception."""
        with self._session() as conn:
            names = self._folder_names(conn)
            unread = self._unread(conn, names["inbox"])
        available = [
            {"key": key, "label": label}
            for key, label, *_ in FOLDERS
            if key in names or key == "starred"
        ]
        return {"address": self.address, "folders": available, "unread": unread}

    def _unread(self, conn, inbox: str) -> int:
        status, data = conn.status(_quote(inbox), "(UNSEEN)")
        if status != "OK" or not data or not data[0]:
            return 0
        match = re.search(rb"UNSEEN (\d+)", data[0])
        return int(match[1]) if match else 0

    def unread(self) -> int:
        with self._session() as conn:
            return self._unread(conn, self._folder_names(conn)["inbox"])

    def list(self, folder: str = "inbox", before: int | None = None, query: str = "") -> dict:
        """Page de messages, du plus recent au plus ancien. before : UID du
        dernier message deja affiche (page suivante)."""
        query = (query or "").strip()
        with self._session() as conn:
            name, criteria = self._target(conn, folder)
            self._select(conn, name, readonly=True)
            uids = self._search(conn, criteria, query)
            if before is not None:
                uids = [uid for uid in uids if uid < before]
            page = uids[-PAGE_SIZE:]
            fetched = self._fetch(
                conn, page, f"(UID FLAGS INTERNALDATE RFC822.SIZE BODY.PEEK[]<0.{PREVIEW_BYTES}>)"
            )
        messages = []
        for item in fetched:
            message = message_from_bytes(item["literal"], policy=policy.default)
            content_type = _header(message, "Content-Type").lower()
            messages.append({
                "uid": item["uid"],
                "subject": _header(message, "Subject"),
                "from": _address_list(message, "From"),
                "to": _address_list(message, "To") + _address_list(message, "Cc"),
                "date": item["internaldate"] or _date(message, None),
                "seen": "\\Seen" in item["flags"],
                "starred": "\\Flagged" in item["flags"],
                "answered": "\\Answered" in item["flags"],
                "hasAttachments": content_type.startswith("multipart/mixed"),
                "snippet": snippet(message),
                "size": item["size"],
            })
        messages.sort(key=lambda message: message["uid"], reverse=True)
        return {"folder": folder, "messages": messages, "hasMore": len(uids) > len(page)}

    def _fetch_one(self, conn, uid: int) -> dict:
        fetched = self._fetch(conn, [uid], "(UID FLAGS INTERNALDATE BODY.PEEK[])")
        if not fetched:
            raise WebmailNotFoundError()
        return fetched[0]

    def _raw(self, conn, uid: int) -> tuple[bytes, list[str]]:
        item = self._fetch_one(conn, uid)
        return item["literal"], item["flags"]

    def get(self, folder: str, uid: int) -> dict:
        """Message complet ; le marque comme lu."""
        with self._session() as conn:
            name, _criteria = self._target(conn, folder)
            self._select(conn, name, readonly=False)
            item = self._fetch_one(conn, uid)
            raw, flags = item["literal"], item["flags"]
            if "\\Seen" not in flags:
                conn.uid("STORE", str(uid), "+FLAGS", "(\\Seen)")
        detail = parse_message(raw)
        return {
            **detail,
            # Sans en-tete Date : date de reception.
            "date": detail["date"] or item["internaldate"],
            "uid": uid,
            "folder": folder,
            "seen": True,
            "starred": "\\Flagged" in flags,
        }

    def attachment(self, folder: str, uid: int, index: int) -> tuple[bytes, str, str]:
        with self._session() as conn:
            name, _criteria = self._target(conn, folder)
            self._select(conn, name, readonly=True)
            raw, _flags = self._raw(conn, uid)
        return attachment_from(raw, index)

    # --- Actions ---------------------------------------------------------

    def set_flags(self, folder: str, uid: int, seen: bool | None = None, starred: bool | None = None) -> dict:
        with self._session() as conn:
            name, _criteria = self._target(conn, folder)
            self._select(conn, name, readonly=False)
            for flag, value in (("\\Seen", seen), ("\\Flagged", starred)):
                if value is None:
                    continue
                status, _data = conn.uid("STORE", str(uid), "+FLAGS" if value else "-FLAGS", f"({flag})")
                if status != "OK":
                    raise WebmailError("Modification refusée par le serveur")
        return {"uid": uid, "folder": folder, "seen": seen, "starred": starred}

    def move(self, folder: str, uid: int, to: str) -> dict:
        """Deplace vers inbox, archive (Gmail : "Tous les messages", donc
        retire de la reception), trash ou spam."""
        targets = {"inbox": "inbox", "archive": "all", "trash": "trash", "spam": "spam"}
        if to not in targets:
            raise WebmailError("Destination inconnue")
        with self._session() as conn:
            name, _criteria = self._target(conn, folder)
            destination, _ = self._target(conn, targets[to])
            if destination == name:
                return {"uid": uid, "folder": folder, "to": to}
            self._select(conn, name, readonly=False)
            if "MOVE" in conn.capabilities:
                status, _data = conn.uid("MOVE", str(uid), _quote(destination))
            else:
                status, _data = conn.uid("COPY", str(uid), _quote(destination))
                if status == "OK":
                    conn.uid("STORE", str(uid), "+FLAGS", "(\\Deleted)")
                    self._expunge(conn, uid)
            if status != "OK":
                raise WebmailError("Déplacement refusé par le serveur")
        return {"uid": uid, "folder": folder, "to": to}

    def _expunge(self, conn, uid: int) -> None:
        if "UIDPLUS" in conn.capabilities:
            conn.uid("EXPUNGE", str(uid))
        else:
            conn.expunge()

    def delete(self, folder: str, uid: int) -> dict:
        """Suppression definitive, seulement depuis la corbeille ou le spam."""
        if folder not in ("trash", "spam"):
            raise WebmailError("Supprimer définitivement : seulement depuis la corbeille ou le spam")
        with self._session() as conn:
            name, _criteria = self._target(conn, folder)
            self._select(conn, name, readonly=False)
            status, _data = conn.uid("STORE", str(uid), "+FLAGS", "(\\Deleted)")
            if status != "OK":
                raise WebmailError("Suppression refusée par le serveur")
            self._expunge(conn, uid)
        return {"uid": uid, "folder": folder, "deleted": True}

    # --- Envoi -----------------------------------------------------------

    def send(
        self,
        to: str,
        cc: str = "",
        bcc: str = "",
        subject: str = "",
        body: str = "",
        in_reply_to: str = "",
        references: str = "",
        attachments: list[tuple[str, str, bytes]] = (),
        forward: tuple[str, int] | None = None,
        answered: tuple[str, int] | None = None,
    ) -> dict:
        """Envoie par SMTP. forward : (dossier, UID) dont les pieces jointes
        sont reprises ; answered : (dossier, UID) marque "repondu"."""
        if not self.configured:
            raise WebmailError("Boîte mail non configurée (WEBMAIL_APP_PASSWORD manquant)")
        attachments = list(attachments)
        if forward is not None:
            folder, uid = forward
            with self._session() as conn:
                name, _criteria = self._target(conn, folder)
                self._select(conn, name, readonly=True)
                raw, _flags = self._raw(conn, uid)
            for item in parse_message(raw)["attachments"]:
                data, filename, content_type = attachment_from(raw, item["index"])
                attachments.append((filename, content_type, data))
        message, recipients = build_message(
            self.address, self.sender_name, to, cc, subject, body, in_reply_to, references, attachments
        )
        hidden = [address for _name, address in getaddresses(parse_recipients(bcc))]
        try:
            if self.smtp_port == 465:
                smtp = smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=self.timeout, context=ssl.create_default_context())
            else:
                smtp = smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=self.timeout)
            with smtp:
                if self.smtp_port == 587:
                    smtp.starttls(context=ssl.create_default_context())
                    smtp.login(self.address, self.password)
                smtp.send_message(message, to_addrs=recipients + hidden)
        except smtplib.SMTPAuthenticationError as exc:
            raise WebmailError("Envoi refusé par Gmail : vérifie le mot de passe d'application") from exc
        except (smtplib.SMTPException, OSError) as exc:
            raise WebmailError(f"Envoi impossible ({exc})") from exc

        # Gmail range lui-meme le mail dans "Envoyes" ; ailleurs, on l'y copie.
        if "gmail" not in self.smtp_host or answered is not None:
            try:
                with self._session() as conn:
                    if "gmail" not in self.smtp_host:
                        sent = self._folder_names(conn).get("sent")
                        if sent:
                            conn.append(_quote(sent), "(\\Seen)", None, message.as_bytes())
                    if answered is not None:
                        name, _criteria = self._target(conn, answered[0])
                        self._select(conn, name, readonly=False)
                        conn.uid("STORE", str(answered[1]), "+FLAGS", "(\\Answered)")
            except (WebmailError, imaplib.IMAP4.error, OSError):
                pass  # le mail est parti : le rangement n'est qu'un plus
        return {"sent": True, "messageId": message["Message-ID"]}
