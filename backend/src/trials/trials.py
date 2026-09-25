"""Eleves en cours d'essai (onglet "Essai" de l'appli).

Un eleve s'inscrit sur la page publique (ou est ajoute a la main dans
l'onglet, exceptionnellement) et recoit un QR code, a montrer au debut de son
cours d'essai. Regles (decidees avec le bureau du club) :
- un seul QR code par eleve, pour toujours (reinscription -> le meme) ;
- il ne sert qu'une fois : le scan remplit le 1er cours vide (sinon le 2e),
  un nouveau scan repond "cours d'essai deja effectue le ..." ;
- 2 cours d'essai au maximum : on en annonce un, un 2e est une exception.
  Un cours peut aussi etre ajoute a la main (eleve sans son QR code) ; pour
  chaque cours on garde sa date et son mode ("qr" ou "manual").
- un eleve est supprime automatiquement un an apres sa derniere activite
  (inscription ou cours), certificat medical compris (voir purge_expired).

Stockage : table trial_students de la base SQLite (voir database/database.py).
Certificats medicaux envoyes (donnees de sante) : fichiers dans
certificates_dir (volume Docker), jamais dans Git.
"""

from __future__ import annotations

import io
import re
import secrets
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pillow_heif
import segno
from PIL import Image, ImageOps

from database import Database
from mailer import Mailer

from . import content
from .emails import confirmation_email

# Photos d'iPhone (HEIC) : lisibles par Pillow une fois ce module enregistre.
pillow_heif.register_heif_opener()

PARIS = ZoneInfo("Europe/Paris")
COURSE_MODES = ("qr", "manual")
GENDERS = ("M", "F")
# Champs modifiables depuis l'onglet (voir update_student).
EDITABLE_FIELDS = ("first_name", "last_name", "birth_date", "gender", "email", "phone", "parent_name", "comment")


class TrialStudentNotFoundError(LookupError):
    """Levee quand l'eleve demande n'existe pas (ou plus)."""


class TrialCoursesFullError(ValueError):
    """Levee quand on ajoute un cours a un eleve qui a deja ses 2 cours."""


class RegistrationError(ValueError):
    """Levee quand une inscription en ligne est incomplete ou invalide (le
    message est affiche tel quel sur la page publique)."""


EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ADULT_AGE = 18
MAX_SIGNATURE_BYTES = 500_000
MAX_CERTIFICATE_BYTES = 15_000_000
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def today() -> date:
    """Date du jour au club (pas celle du serveur, en UTC)."""
    return datetime.now(PARIS).date()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _age(birth_date: str | None, on: date) -> int | None:
    if not birth_date:
        return None
    born = date.fromisoformat(birth_date)
    return on.year - born.year - ((on.month, on.day) < (born.month, born.day))


class Trials:
    """Gestion des eleves en cours d'essai (voir le docstring du module)."""

    RETENTION_DAYS = 365
    MAX_COURSES = 2

    def __init__(
        self,
        db: Database,
        certificates_dir: str,
        checkin_url: str = "https://silvaplana.cloud/sambo-admin/?essai=",
        qr_image_url: str = "https://silvaplana.cloud/sambo-admin/api/public/trials/qr/",
        mailer: Mailer | None = None,
    ) -> None:
        """checkin_url : debut de l'URL contenue dans le QR code, suivie du
        jeton -- scanne avec l'appareil photo du telephone, il ouvre
        directement l'onglet Essai de l'appli. qr_image_url : adresse publique
        de l'image du QR code (suivie de "<jeton>.png"), affichee dans le mail."""
        self.db = db
        self.certificates_dir = Path(certificates_dir)
        self.checkin_url = checkin_url
        self.qr_image_url = qr_image_url
        self.mailer = mailer

    # ----- lecture -----

    def _to_dict(self, row) -> dict:
        """Format expose a l'onglet (sans la signature, lue a part)."""
        return {
            "id": row["id"],
            "firstName": row["first_name"],
            "lastName": row["last_name"],
            "birthDate": row["birth_date"],
            "age": _age(row["birth_date"], today()),
            "gender": row["gender"],
            "email": row["email"],
            "phone": row["phone"],
            "parentName": row["parent_name"],
            "medicalAttestation": bool(row["medical_attestation"]),
            "hasMedicalCertificate": bool(row["medical_certificate_file"]),
            "parentalConsent": bool(row["parental_consent"]),
            "waiverAccepted": bool(row["waiver_accepted"]),
            "signedAt": row["signed_at"],
            "hasSignature": row["signature_png"] is not None,
            "qrGenerated": row["qr_token"] is not None,
            "qrCreatedAt": row["qr_created_at"],
            "courses": [
                {"number": n, "date": row[f"course{n}_date"], "mode": row[f"course{n}_mode"]}
                for n in range(1, self.MAX_COURSES + 1)
            ],
            "comment": row["comment"],
            "source": row["source"],
            "createdAt": row["created_at"],
        }

    def _get_row(self, connection, student_id: int):
        row = connection.execute("SELECT * FROM trial_students WHERE id = ?", (student_id,)).fetchone()
        if row is None:
            raise TrialStudentNotFoundError(student_id)
        return row

    def list_students(self) -> list[dict]:
        """Tous les eleves, le plus recemment inscrit en premier."""
        with self.db.connect() as connection:
            rows = connection.execute("SELECT * FROM trial_students ORDER BY created_at DESC, id DESC").fetchall()
        return [self._to_dict(row) for row in rows]

    def get_student(self, student_id: int) -> dict:
        with self.db.connect() as connection:
            return self._to_dict(self._get_row(connection, student_id))

    # ----- ecriture -----

    @staticmethod
    def _clean(fields: dict) -> dict:
        """Normalise les champs saisis (espaces, e-mail en minuscules, chaines
        vides -> NULL) et verifie ceux qui ont un format impose."""
        cleaned = {}
        for key, value in fields.items():
            if isinstance(value, date):
                value = value.isoformat()
            if isinstance(value, str):
                value = value.strip()
                if key == "email":
                    value = value.lower()
                if not value and key != "comment":
                    value = None
            cleaned[key] = value
        if cleaned.get("gender") not in (None, *GENDERS):
            raise ValueError(f"Genre inconnu : {cleaned['gender']}")
        if cleaned.get("birth_date"):
            date.fromisoformat(cleaned["birth_date"])
        for key in ("first_name", "last_name"):
            if key in cleaned and not cleaned[key]:
                raise ValueError("Le prénom et le nom sont obligatoires")
        return cleaned

    def add_student(
        self,
        first_name: str,
        last_name: str,
        birth_date: str | date | None = None,
        gender: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        parent_name: str | None = None,
        comment: str = "",
    ) -> dict:
        """Ajout a la main depuis l'onglet (exceptionnel : normalement
        l'eleve s'inscrit lui-meme sur la page publique). Pas de QR code."""
        fields = self._clean(
            {
                "first_name": first_name,
                "last_name": last_name,
                "birth_date": birth_date,
                "gender": gender,
                "email": email,
                "phone": phone,
                "parent_name": parent_name,
                "comment": comment or "",
            }
        )
        now = _now_iso()
        fields.update({"source": "manual", "created_at": now, "updated_at": now})
        columns = ", ".join(fields)
        placeholders = ", ".join("?" for _ in fields)
        with self.db.connect() as connection:
            cursor = connection.execute(
                f"INSERT INTO trial_students ({columns}) VALUES ({placeholders})", tuple(fields.values())
            )
            return self._to_dict(self._get_row(connection, cursor.lastrowid))

    def update_student(self, student_id: int, fields: dict) -> dict:
        """Modifie les champs fournis (parmi EDITABLE_FIELDS), les autres
        restent inchanges."""
        unknown = set(fields) - set(EDITABLE_FIELDS)
        if unknown:
            raise ValueError(f"Champs non modifiables : {', '.join(sorted(unknown))}")
        fields = self._clean(fields)
        if fields.get("comment") is None and "comment" in fields:
            fields["comment"] = ""
        with self.db.connect() as connection:
            self._get_row(connection, student_id)
            if fields:
                assignments = ", ".join(f"{key} = ?" for key in fields)
                connection.execute(
                    f"UPDATE trial_students SET {assignments}, updated_at = ? WHERE id = ?",
                    (*fields.values(), _now_iso(), student_id),
                )
            return self._to_dict(self._get_row(connection, student_id))

    def delete_student(self, student_id: int) -> None:
        """Supprime l'eleve et son certificat medical eventuel."""
        with self.db.connect() as connection:
            row = self._get_row(connection, student_id)
            connection.execute("DELETE FROM trial_students WHERE id = ?", (student_id,))
        self._delete_certificate(row["medical_certificate_file"])

    def _delete_certificate(self, filename: str | None) -> None:
        if filename:
            (self.certificates_dir / filename).unlink(missing_ok=True)

    # ----- cours d'essai -----

    def add_course(self, student_id: int, course_date: str | date | None = None) -> dict:
        """Bouton "Ajouter cours d'essai" : date saisie a la main (aujourd'hui
        par defaut) dans le 1er cours vide. TrialCoursesFullError si l'eleve a
        deja ses 2 cours."""
        course_date = str(course_date or today())
        date.fromisoformat(course_date)
        with self.db.connect() as connection:
            row = self._get_row(connection, student_id)
            number = self._next_free_course(row)
            if number is None:
                raise TrialCoursesFullError("Les 2 cours d'essai sont déjà renseignés")
            self._write_course(connection, student_id, number, course_date, "manual")
            return self._to_dict(self._get_row(connection, student_id))

    def set_course(self, student_id: int, number: int, course_date: str | date | None) -> dict:
        """Corrige la date du cours `number` (1 ou 2), ou l'efface (None). Un
        cours deja renseigne garde son mode (qr/manual) ; un cours vide
        renseigne ici devient "manual"."""
        if number not in range(1, self.MAX_COURSES + 1):
            raise ValueError(f"Cours d'essai inconnu : {number}")
        if course_date is not None:
            course_date = str(course_date)
            date.fromisoformat(course_date)
        with self.db.connect() as connection:
            row = self._get_row(connection, student_id)
            mode = None if course_date is None else (row[f"course{number}_mode"] or "manual")
            self._write_course(connection, student_id, number, course_date, mode)
            return self._to_dict(self._get_row(connection, student_id))

    def _next_free_course(self, row) -> int | None:
        return next((n for n in range(1, self.MAX_COURSES + 1) if not row[f"course{n}_date"]), None)

    @staticmethod
    def _write_course(connection, student_id: int, number: int, course_date: str | None, mode: str | None) -> None:
        connection.execute(
            f"UPDATE trial_students SET course{number}_date = ?, course{number}_mode = ?, updated_at = ? WHERE id = ?",
            (course_date, mode, _now_iso(), student_id),
        )

    def check_in(self, token: str) -> dict:
        """Scan du QR code presente en debut de cours. Retourne {"status"} :
        - "added"     : cours du jour ajoute (+ "course", numero du cours) ;
        - "unknown"   : QR code non identifie ;
        - "used"      : QR code deja utilise (+ "date" de ce cours) ;
        - "full"      : QR code jamais utilise mais 2 cours deja renseignes a
                        la main (+ "date" du dernier).
        "student" (sauf si unknown) : l'eleve a jour."""
        token = self._extract_token(token)
        with self.db.connect() as connection:
            row = connection.execute("SELECT * FROM trial_students WHERE qr_token = ?", (token,)).fetchone()
            if not token or row is None:
                return {"status": "unknown"}
            used = next((n for n in range(1, self.MAX_COURSES + 1) if row[f"course{n}_mode"] == "qr"), None)
            if used is not None:
                return {"status": "used", "date": row[f"course{used}_date"], "student": self._to_dict(row)}
            number = self._next_free_course(row)
            if number is None:
                return {"status": "full", "date": row[f"course{self.MAX_COURSES}_date"], "student": self._to_dict(row)}
            self._write_course(connection, row["id"], number, today().isoformat(), "qr")
            return {"status": "added", "course": number, "student": self._to_dict(self._get_row(connection, row["id"]))}

    # ----- QR code -----

    @staticmethod
    def new_qr_token() -> str:
        """Jeton aleatoire, seule donnee du QR code (aucune donnee
        personnelle) : impossible a deviner."""
        return secrets.token_urlsafe(16)

    def _extract_token(self, scanned: str | None) -> str:
        """Contenu scanne -> jeton : le QR code contient l'URL complete
        (checkin_url + jeton), mais le jeton seul (saisi a la main) marche
        aussi."""
        scanned = (scanned or "").strip()
        match = re.search(r"[?&]essai=([A-Za-z0-9_-]+)", scanned)
        return match.group(1) if match else scanned

    def qr_png(self, token: str) -> bytes:
        """Image PNG du QR code d'un eleve. TrialStudentNotFoundError si le
        jeton n'existe pas (pas de generateur de QR code ouvert a tous)."""
        with self.db.connect() as connection:
            if connection.execute("SELECT 1 FROM trial_students WHERE qr_token = ?", (token,)).fetchone() is None:
                raise TrialStudentNotFoundError(token)
        buffer = io.BytesIO()
        segno.make(self.checkin_url + token, error="m").save(buffer, kind="png", scale=10, border=4)
        return buffer.getvalue()

    # ----- inscription en ligne (page publique) -----

    def register(self, form: dict, signature_png: bytes, certificate: tuple[str, bytes] | None, ip: str | None) -> dict:
        """Inscription depuis la page publique. form : first_name, last_name,
        birth_date, gender, email, phone, parent_name, medical_attestation,
        parental_consent, waiver_accepted, terms_version.

        Eleve deja inscrit (meme e-mail, nom et prenom) : rien n'est modifie
        et on lui renvoie son QR code par mail -- jamais affiche a l'ecran,
        sinon n'importe qui connaissant son nom et son e-mail le recupererait.
        Eleve ajoute a la main sans QR code : son inscription est completee.

        Retourne {"status": "created" | "existing", "student", "token"}.
        Leve RegistrationError si le formulaire est incomplet."""
        fields = self._validate_registration(form, signature_png)
        now = _now_iso()
        with self.db.connect() as connection:
            existing = self._find_existing(connection, fields)
            if existing is not None and existing["qr_token"]:
                return {"status": "existing", "student": self._to_dict(existing), "token": existing["qr_token"]}
            token = self.new_qr_token()
            fields.update(
                {
                    "signature_png": signature_png,
                    "signed_at": now,
                    "signed_ip": ip,
                    "qr_token": token,
                    "qr_created_at": now,
                    "updated_at": now,
                }
            )
            if existing is not None:
                assignments = ", ".join(f"{key} = ?" for key in fields)
                connection.execute(
                    f"UPDATE trial_students SET {assignments} WHERE id = ?", (*fields.values(), existing["id"])
                )
                student_id = existing["id"]
            else:
                fields.update({"source": "web", "created_at": now})
                columns = ", ".join(fields)
                placeholders = ", ".join("?" for _ in fields)
                cursor = connection.execute(
                    f"INSERT INTO trial_students ({columns}) VALUES ({placeholders})", tuple(fields.values())
                )
                student_id = cursor.lastrowid
            if certificate is not None:
                self._store_certificate(connection, student_id, *certificate)
            return {"status": "created", "student": self._to_dict(self._get_row(connection, student_id)), "token": token}

    def _validate_registration(self, form: dict, signature_png: bytes) -> dict:
        try:
            date.fromisoformat(form.get("birth_date") or "")
        except ValueError as exc:
            raise RegistrationError("Merci d'indiquer une date de naissance valide") from exc
        try:
            fields = self._clean({key: form.get(key) for key in EDITABLE_FIELDS if key != "comment"})
        except ValueError as exc:
            raise RegistrationError(str(exc)) from exc
        for key, label in (("birth_date", "la date de naissance"), ("gender", "le genre"), ("email", "l'e-mail")):
            if not fields.get(key):
                raise RegistrationError(f"Merci d'indiquer {label}")
        if not EMAIL_PATTERN.match(fields["email"]):
            raise RegistrationError("Adresse e-mail invalide")
        age = _age(fields["birth_date"], today())
        if age < 3 or age > 100:
            raise RegistrationError("Date de naissance invalide")
        minor = age < ADULT_AGE
        if minor and not fields.get("parent_name"):
            raise RegistrationError("Pour un mineur, merci d'indiquer le nom du parent ou représentant légal")
        if not minor:
            fields["parent_name"] = None
        checks = {
            "medical_attestation": "Merci de cocher l'attestation médicale",
            "waiver_accepted": "Merci d'accepter la décharge de responsabilité",
        }
        if minor:
            checks["parental_consent"] = "Merci de cocher l'autorisation parentale"
        for key, message in checks.items():
            if not form.get(key):
                raise RegistrationError(message)
        if not signature_png.startswith(PNG_MAGIC) or len(signature_png) > MAX_SIGNATURE_BYTES:
            raise RegistrationError("Signature manquante ou invalide")
        fields.update(
            {
                "medical_attestation": 1,
                "waiver_accepted": 1,
                "parental_consent": 1 if minor else 0,
                "terms_version": form.get("terms_version") or content.TERMS_VERSION,
            }
        )
        return fields

    @staticmethod
    def _find_existing(connection, fields: dict):
        """Meme eleve = meme e-mail + meme nom et prenom (sans tenir compte
        des majuscules) : 2 enfants inscrits avec l'e-mail d'un parent restent
        2 eleves."""
        rows = connection.execute(
            "SELECT * FROM trial_students WHERE lower(email) = ?", (fields["email"].lower(),)
        ).fetchall()
        key = (fields["first_name"].casefold(), fields["last_name"].casefold())
        return next((row for row in rows if (row["first_name"].casefold(), row["last_name"].casefold()) == key), None)

    # ----- certificat medical et signature -----

    def _store_certificate(self, connection, student_id: int, filename: str, data: bytes) -> None:
        """Enregistre le certificat medical envoye : PDF tel quel, photo
        convertie en JPEG (les photos HEIC d'iPhone ne s'affichent pas dans
        tous les navigateurs) et reduite a 2000 px."""
        if len(data) > MAX_CERTIFICATE_BYTES:
            raise RegistrationError("Certificat trop volumineux (15 Mo maximum)")
        if data.startswith(b"%PDF"):
            extension, stored = "pdf", data
        else:
            try:
                image = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
                image.thumbnail((2000, 2000))
                buffer = io.BytesIO()
                image.convert("RGB").save(buffer, format="JPEG", quality=85)
            except Exception as exc:
                raise RegistrationError("Certificat illisible : envoyez une photo ou un PDF") from exc
            extension, stored = "jpg", buffer.getvalue()
        self.certificates_dir.mkdir(parents=True, exist_ok=True)
        name = f"{student_id}-{secrets.token_hex(8)}.{extension}"
        (self.certificates_dir / name).write_bytes(stored)
        previous = connection.execute(
            "SELECT medical_certificate_file FROM trial_students WHERE id = ?", (student_id,)
        ).fetchone()[0]
        connection.execute("UPDATE trial_students SET medical_certificate_file = ? WHERE id = ?", (name, student_id))
        self._delete_certificate(previous)

    def get_certificate(self, student_id: int) -> tuple[Path, str]:
        """Fichier du certificat medical et son type MIME."""
        with self.db.connect() as connection:
            row = self._get_row(connection, student_id)
        if not row["medical_certificate_file"]:
            raise TrialStudentNotFoundError(student_id)
        path = self.certificates_dir / row["medical_certificate_file"]
        return path, "application/pdf" if path.suffix == ".pdf" else "image/jpeg"

    def get_signature(self, student_id: int) -> bytes:
        with self.db.connect() as connection:
            row = self._get_row(connection, student_id)
        if row["signature_png"] is None:
            raise TrialStudentNotFoundError(student_id)
        return row["signature_png"]

    # ----- mail de confirmation -----

    def send_confirmation(self, student: dict, token: str) -> bool:
        """Envoie (ou renvoie) a l'eleve le mail avec son QR code et les
        modalites du cours d'essai. False si le mailer n'est pas configure ;
        MailError si l'envoi echoue."""
        if self.mailer is None or not student.get("email"):
            return False
        subject, html = confirmation_email(student, f"{self.qr_image_url}{token}.png")
        return self.mailer.send(
            student["email"],
            f"{student['firstName']} {student['lastName']}",
            subject,
            html,
            attachments=[("qr-code-cours-essai.png", self.qr_png(token))],
        )

    # ----- conservation des donnees -----

    def purge_expired(self) -> int:
        """Supprime les eleves sans activite (inscription ou cours) depuis
        RETENTION_DAYS jours. Retourne le nombre d'eleves supprimes."""
        limit = (today() - timedelta(days=self.RETENTION_DAYS)).isoformat()
        with self.db.connect() as connection:
            rows = connection.execute(
                "SELECT id, medical_certificate_file, created_at, course1_date, course2_date FROM trial_students"
            ).fetchall()
            expired = [
                row
                for row in rows
                if max(filter(None, (row["created_at"][:10], row["course1_date"], row["course2_date"]))) < limit
            ]
            connection.executemany("DELETE FROM trial_students WHERE id = ?", [(row["id"],) for row in expired])
        for row in expired:
            self._delete_certificate(row["medical_certificate_file"])
        return len(expired)
