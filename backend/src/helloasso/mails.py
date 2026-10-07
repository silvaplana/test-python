"""Journal des mails envoyes et des SMS prepares pour les adherents depuis
l'onglet HelloAsso > Adherents (tables member_mails et member_sms, voir
database.py).

Les adherents ne sont pas en base : ils sont lus de l'API HelloAsso. Chaque
mail est donc rattache a l'identifiant HelloAsso de l'adhesion (member_id,
stable et unique) et garde une copie du nom et de l'adresse au moment de
l'envoi -- le journal reste lisible meme si l'adherent disparait de
HelloAsso, et pourra etre relie a une future table des adherents par ce
meme identifiant.
"""

from __future__ import annotations

from datetime import datetime, timezone

from database import Database

SENT, FAILED = "envoye", "echec"


class MemberMails:
    def __init__(self, db: Database) -> None:
        self.db = db

    def record(
        self,
        member: dict,
        to_email: str,
        cc: str | None,
        sender: str | None,
        subject: str,
        body: str,
        error: str | None = None,
    ) -> dict:
        """Garde la trace d'un mail (member : fiche HelloAsso de l'adherent).
        error : raison de l'echec si l'envoi n'a pas abouti."""
        sent_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.db.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO member_mails (member_id, first_name, last_name, to_email, cc, sender, subject, body,
                   status, error, sent_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    member["id"],
                    member.get("firstName") or "",
                    member.get("lastName") or "",
                    to_email,
                    cc,
                    sender,
                    subject,
                    body,
                    FAILED if error else SENT,
                    error,
                    sent_at,
                ),
            )
        return self._get(cursor.lastrowid)

    def list(self, member_id: int | None = None, limit: int = 300) -> list[dict]:
        """Mails envoyes, le plus recent d'abord : ceux d'un adherent
        (member_id), ou tous."""
        query = "SELECT * FROM member_mails"
        params: tuple = ()
        if member_id is not None:
            query, params = query + " WHERE member_id = ?", (member_id,)
        with self.db.connect() as connection:
            rows = connection.execute(query + " ORDER BY sent_at DESC, id DESC LIMIT ?", (*params, limit)).fetchall()
        return [self._to_dict(row) for row in rows]

    def counts(self) -> dict[int, int]:
        """Nombre de mails reellement envoyes a chaque adherent (pastille du
        bouton Mail) : {identifiant HelloAsso: nombre}."""
        with self.db.connect() as connection:
            rows = connection.execute(
                "SELECT member_id, COUNT(*) FROM member_mails WHERE status = ? GROUP BY member_id", (SENT,)
            ).fetchall()
        return {row[0]: row[1] for row in rows}

    def _get(self, mail_id: int) -> dict:
        with self.db.connect() as connection:
            return self._to_dict(connection.execute("SELECT * FROM member_mails WHERE id = ?", (mail_id,)).fetchone())

    @staticmethod
    def _to_dict(row) -> dict:
        return {
            "id": row["id"],
            "memberId": row["member_id"],
            "firstName": row["first_name"],
            "lastName": row["last_name"],
            "to": row["to_email"],
            "cc": row["cc"],
            "sender": row["sender"],
            "subject": row["subject"],
            "body": row["body"],
            "sent": row["status"] == SENT,
            "error": row["error"],
            "sentAt": row["sent_at"],
        }


def normalize_phone(value: str | None) -> str | None:
    """Numero du formulaire -> numero utilisable dans un lien "sms:" :
    "06 12 34 56 78" -> "+33612345678". None s'il est absent ou trop court
    pour etre un numero."""
    text = (value or "").strip()
    digits = "".join(c for c in text if c.isdigit())
    if len(digits) < 9:
        return None
    if text.startswith("+"):
        return "+" + digits
    if digits.startswith("00"):
        return "+" + digits[2:]
    if len(digits) == 10 and digits.startswith("0"):
        return "+33" + digits[1:]
    if len(digits) == 9:  # numero francais saisi sans le 0
        return "+33" + digits
    return digits


class MemberSms:
    """SMS prepares depuis l'appli. L'envoi se fait dans l'appli SMS du
    telephone de l'utilisateur (lien "sms:") : le journal note que le SMS a
    ete prepare, il ne peut pas savoir s'il est reellement parti."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def record(self, member: dict, phone: str, body: str) -> dict:
        sent_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.db.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO member_sms (member_id, first_name, last_name, phone, body, sent_at) VALUES (?, ?, ?, ?, ?, ?)",
                (member["id"], member.get("firstName") or "", member.get("lastName") or "", phone, body, sent_at),
            )
            row = connection.execute("SELECT * FROM member_sms WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return self._to_dict(row)

    def list(self, member_id: int | None = None, limit: int = 300) -> list[dict]:
        """SMS prepares, le plus recent d'abord : ceux d'un adherent, ou tous."""
        query = "SELECT * FROM member_sms"
        params: tuple = ()
        if member_id is not None:
            query, params = query + " WHERE member_id = ?", (member_id,)
        with self.db.connect() as connection:
            rows = connection.execute(query + " ORDER BY sent_at DESC, id DESC LIMIT ?", (*params, limit)).fetchall()
        return [self._to_dict(row) for row in rows]

    def counts(self) -> dict[int, int]:
        """Nombre de SMS prepares pour chaque adherent (pastille du bouton SMS)."""
        with self.db.connect() as connection:
            rows = connection.execute("SELECT member_id, COUNT(*) FROM member_sms GROUP BY member_id").fetchall()
        return {row[0]: row[1] for row in rows}

    @staticmethod
    def _to_dict(row) -> dict:
        return {
            "id": row["id"],
            "memberId": row["member_id"],
            "firstName": row["first_name"],
            "lastName": row["last_name"],
            "phone": row["phone"],
            "body": row["body"],
            "sentAt": row["sent_at"],
        }
