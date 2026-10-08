from email import message_from_bytes, policy
from email.message import EmailMessage

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from webmail import Webmail, WebmailError, WebmailNotFoundError, WebmailReceiver
from webmail.webmail import attachment_from, build_message, parse_fetch, parse_folders, parse_message, snippet


def rich_message() -> bytes:
    message = EmailMessage()
    message["From"] = "Président Fédé <president@ffst.fr>"
    message["To"] = "club@example.org"
    message["Subject"] = "Réunion à 18h"
    message["Message-ID"] = "<abc@ffst.fr>"
    message.set_content("Bonjour,\nLa réunion est à 18h.")
    message.add_alternative('<p>Bonjour</p><img src="cid:logo1">', subtype="html")
    message.get_payload()[1].add_related(b"PNGDATA", maintype="image", subtype="png", cid="<logo1>")
    message.add_attachment("Ordre du jour : élection".encode(), maintype="text", subtype="plain", filename="ordre é.txt")
    return message.as_bytes()


def test_gmail_folders_found_by_role_whatever_the_language():
    lines = [
        b'(\\HasNoChildren) "/" "INBOX"',
        b'(\\HasChildren \\Noselect) "/" "[Gmail]"',
        b'(\\All \\HasNoChildren) "/" "[Gmail]/Tous les messages"',
        b'(\\HasNoChildren \\Sent) "/" "[Gmail]/Messages envoy&AOk-s"',
        b'(\\HasNoChildren \\Trash) "/" "[Gmail]/Corbeille"',
        b'(\\Flagged \\HasNoChildren) "/" "[Gmail]/Suivis"',
        b'(\\HasNoChildren \\Junk) "/" "[Gmail]/Spam"',
    ]
    assert parse_folders(lines) == {
        "inbox": "INBOX",
        "starred": "[Gmail]/Suivis",
        "sent": "[Gmail]/Messages envoy&AOk-s",
        "spam": "[Gmail]/Spam",
        "trash": "[Gmail]/Corbeille",
        "all": "[Gmail]/Tous les messages",
    }


def test_folders_by_name_without_special_use():
    lines = [b'(\\HasNoChildren) "/" INBOX', b'(\\HasNoChildren) "/" Sent', b'(\\HasNoChildren) "/" Trash']
    assert parse_folders(lines) == {"inbox": "INBOX", "sent": "Sent", "trash": "Trash"}


def test_fetch_response_with_uid_after_the_literal():
    data = [
        (b'1 (FLAGS (\\Seen \\Flagged) INTERNALDATE "08-Oct-2026 10:00:00 +0200" RFC822.SIZE 12 BODY[]<0> {5}', b"Hello"),
        b" UID 42)",
        (b"2 (UID 43 FLAGS () BODY[]<0> {3}", b"Bye"),
        b")",
        b"3 (FLAGS (\\Seen))",  # notification spontanee, sans UID : ignoree
    ]
    items = parse_fetch(data)
    assert [(item["uid"], item["flags"], item["literal"]) for item in items] == [
        (42, ["\\Seen", "\\Flagged"], b"Hello"),
        (43, [], b"Bye"),
    ]
    assert items[0]["internaldate"] == "2026-10-08T08:00:00+00:00"
    assert items[0]["size"] == 12


def test_message_body_inline_image_and_attachment():
    detail = parse_message(rich_message())
    assert detail["subject"] == "Réunion à 18h"
    assert detail["from"] == [{"name": "Président Fédé", "address": "president@ffst.fr"}]
    assert detail["text"].startswith("Bonjour,\nLa réunion")
    # Image integree remplacee dans le HTML, donc pas listee en piece jointe.
    assert "data:image/png;base64,UE5HREFUQQ==" in detail["html"]
    assert detail["attachments"] == [{"index": 3, "filename": "ordre é.txt", "contentType": "text/plain", "size": 25}]
    data, name, _type = attachment_from(rich_message(), 3)
    assert (data.decode(), name) == ("Ordre du jour : élection", "ordre é.txt")
    with pytest.raises(WebmailNotFoundError):
        attachment_from(rich_message(), 0)  # le corps n'est pas une piece jointe


def test_snippet_from_a_truncated_message():
    raw = rich_message()
    message = message_from_bytes(raw[: len(raw) // 2], policy=policy.default)
    assert snippet(message).startswith("Bonjour, La réunion est à 18h.")


def test_build_message_reply_and_header_injection():
    message, recipients = build_message(
        "club@example.org",
        "Alliance Sambo",
        "Président <president@ffst.fr>, autre@ex.fr",
        cc="copie@ex.fr",
        subject="Re: Réunion",
        body="Merci",
        in_reply_to="<abc@ffst.fr>",
        references="<old@ffst.fr>",
        attachments=[("liste.csv", "text/csv", b"a;b")],
    )
    assert recipients == ["president@ffst.fr", "autre@ex.fr", "copie@ex.fr"]
    assert message["In-Reply-To"] == "<abc@ffst.fr>"
    assert message["References"] == "<old@ffst.fr> <abc@ffst.fr>"
    assert message["From"] == "Alliance Sambo <club@example.org>"
    assert [part.get_filename() for part in message.iter_attachments()] == ["liste.csv"]
    with pytest.raises(WebmailError):
        build_message("club@example.org", "", "a@b.fr", subject="x\nBcc: pirate@x.fr")
    with pytest.raises(WebmailError):
        build_message("club@example.org", "", "pas-une-adresse")
    with pytest.raises(WebmailError):
        build_message("club@example.org", "", "")


def test_unconfigured_mailbox():
    webmail = Webmail("club@example.org", "")
    assert webmail.settings() == {"configured": False, "address": "club@example.org"}
    with pytest.raises(WebmailError):
        webmail.list()
    client = TestClient(_app(webmail))
    assert client.get("/webmail/unread").json() == {"unread": 0}
    assert client.get("/webmail/messages").status_code == 400


def _app(webmail):
    app = FastAPI()
    WebmailReceiver(client=webmail, app=app)
    return app


class FakeWebmail(Webmail):
    def __init__(self):
        super().__init__("club@example.org", "secret")
        self.sent = []

    def send(self, **kwargs):
        self.sent.append(kwargs)
        return {"sent": True}

    def attachment(self, folder, uid, index):
        return b"<script>alert(1)</script>", "page é.html", "text/html"


def test_send_route_and_attachment_download():
    webmail = FakeWebmail()
    client = TestClient(_app(webmail))
    response = client.post(
        "/webmail/send",
        data={"to": "a@b.fr", "subject": "Re: x", "body": "Merci", "answeredFolder": "inbox", "answeredUid": "7"},
        files=[("files", ("note.txt", b"hello", "text/plain"))],
    )
    assert response.json() == {"sent": True}
    sent = webmail.sent[0]
    assert sent["attachments"] == [("note.txt", "text/plain", b"hello")]
    assert sent["answered"] == ("inbox", 7)
    assert sent["forward"] is None

    # Piece jointe toujours telechargee, jamais interpretee par le navigateur.
    response = client.get("/webmail/messages/inbox/7/attachments/2")
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["content-disposition"].startswith("attachment;")
    assert "filename*=UTF-8''page%20%C3%A9.html" in response.headers["content-disposition"]
    assert response.headers["x-content-type-options"] == "nosniff"


def test_bulk_actions_on_checked_mails():
    calls = []

    class Recorder(Webmail):
        def move(self, folder, uid, to):
            calls.append(("move", folder, self._uid_set(uid), to))

        def delete(self, folder, uid):
            calls.append(("delete", folder, self._uid_set(uid)))

        def set_flags(self, folder, uid, seen=None, starred=None):
            calls.append(("flags", folder, self._uid_set(uid), seen))

    webmail = Recorder("club@example.org", "secret")
    webmail.bulk("inbox", [5, 7, 5], "trash")  # doublon retire
    webmail.bulk("trash", [9], "delete")
    webmail.bulk("inbox", [1, 2], "unread")
    assert calls == [("move", "inbox", "5,7", "trash"), ("delete", "trash", "9"), ("flags", "inbox", "1,2", False)]
    with pytest.raises(WebmailError):
        webmail.bulk("inbox", [1], "autre")
    with pytest.raises(WebmailError):
        Webmail._uid_set([])
    with pytest.raises(WebmailError):
        Webmail._uid_set(list(range(501)))
    # Suppression definitive refusee hors corbeille et spam, avant toute connexion.
    with pytest.raises(WebmailError):
        Webmail("club@example.org", "secret").bulk("inbox", [1], "delete")
