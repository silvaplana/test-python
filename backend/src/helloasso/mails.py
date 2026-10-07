"""Journal des mails envoyes aux adherents depuis l'onglet HelloAsso >
Adherents (table member_mails, voir database.py).

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
