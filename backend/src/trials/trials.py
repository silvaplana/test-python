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
from .emails import confirmation_email, qr_cid, signature_cid

# Photos d'iPhone (HEIC) : lisibles par Pillow une fois ce module enregistre.
pillow_heif.register_heif_opener()

PARIS = ZoneInfo("Europe/Paris")
COURSE_MODES = ("qr", "manual")
GENDERS = ("M", "F")
# Champs modifiables depuis l'onglet (voir update_student).
EDITABLE_FIELDS = (
    "first_name",
    "last_name",
    "age",
    "birth_date",
    "gender",
    "email",
    "phone",
    "parent_name",
    "comment",
)


class TrialStudentNotFoundError(LookupError):
    """Levee quand l'eleve demande n'existe pas (ou plus)."""


class TrialCoursesFullError(ValueError):
    """Levee quand on ajoute un cours a un eleve qui a deja ses 2 cours."""


class RegistrationError(ValueError):
    """Levee quand une inscription en ligne est incomplete ou invalide (le
    message est affiche tel quel sur la page publique)."""


EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_SIGNATURE_BYTES = 500_000
MAX_CERTIFICATE_BYTES = 15_000_000
# Pieces jointes du mail de confirmation (Gmail : 25 Mo max, encodage compris).
MAX_ATTACHMENTS_BYTES = 15_000_000
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
ADULT_AGE = 18
MIN_AGE, MAX_AGE = 3, 100
# Age d'un mineur inscrit en ligne (cours ouverts a partir de 9 ans).
MIN_MINOR_AGE = 9
# Personnes d'une meme famille inscrites en une seule demande.
MAX_FAMILY_SIZE = 3


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
        mailer: Mailer | None = None,
    ) -> None:
        """checkin_url : debut de l'URL contenue dans le QR code, suivie du
        jeton -- scanne avec l'appareil photo du telephone, il ouvre
        directement l'onglet Essai de l'appli."""
        self.db = db
        self.certificates_dir = Path(certificates_dir)
        self.checkin_url = checkin_url
        self.mailer = mailer

    # ----- lecture -----

    def _to_dict(self, row) -> dict:
        """Format expose a l'onglet (sans la signature, lue a part)."""
        return {
            "id": row["id"],
            "firstName": row["first_name"],
            "lastName": row["last_name"],
            "birthDate": row["birth_date"],
            # Age declare a l'inscription ; a defaut (anciennes inscriptions,
            # ajouts a la main), calcule depuis la date de naissance.
            "age": row["age"] if row["age"] is not None else _age(row["birth_date"], today()),
            "familyId": row["family_id"],
            "gender": row["gender"],
            "email": row["email"],
            "phone": row["phone"],
            "parentName": row["parent_name"],
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
        if cleaned.get("age") is not None:
            try:
                cleaned["age"] = int(cleaned["age"])
            except (TypeError, ValueError) as exc:
                raise ValueError("Âge invalide") from exc
            if not MIN_AGE <= cleaned["age"] <= MAX_AGE:
                raise ValueError("Âge invalide")
        for key in ("first_name", "last_name"):
            if key in cleaned and not cleaned[key]:
                raise ValueError("Le prénom et le nom sont obligatoires")
        return cleaned

    def add_student(
        self,
        first_name: str,
        last_name: str,
        age: int | None = None,
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
                "age": age,
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
            self._delete_orphan_signatures(connection)
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
        """Image PNG du QR code d'un eleve."""
        buffer = io.BytesIO()
        segno.make(self.checkin_url + token, error="m").save(buffer, kind="png", scale=10, border=4)
        return buffer.getvalue()

    # ----- inscription en ligne (page publique) -----

    def register(
        self,
        form: dict,
        people: list[dict],
        signature_png: bytes,
        parent_signatures: list[tuple[str, bytes]],
        ip: str | None,
    ) -> list[dict]:
        """Inscription depuis la page publique, pour 1 a 3 personnes d'une
        meme famille, toutes avec l'e-mail de la 1re personne. Chaque
        personne : prenom, nom, mineur (+ age), certificat medical
        (obligatoire), decharge ; pour un mineur, son parent ou representant
        legal (par defaut la 1re personne inscrite, sinon quelqu'un d'autre,
        nomme). Signatures : la 1re personne, et chaque representant legal
        exterieur -- sa signature vaut autorisation parentale.

        form : email, terms_version. people : [{first_name, last_name, minor,
        age, waiver_accepted, certificate, parent_is_first,
        parent_first_name, parent_last_name}], certificate = (nom du fichier,
        contenu). signature_png : signature de la 1re personne.
        parent_signatures : [(nom du parent, PNG)].

        Personne deja inscrite (meme e-mail, nom et prenom) : rien n'est
        modifie et son QR code lui est renvoye par mail -- jamais affiche a
        l'ecran, sinon n'importe qui connaissant son nom et son e-mail le
        recupererait. Personne ajoutee a la main sans QR code : son
        inscription est completee.

        Retourne, par personne et dans l'ordre : {"status": "created" |
        "existing", "student", "token", "familyId"} (familyId : la demande,
        pour retrouver ses signatures). Leve RegistrationError si le
        formulaire est incomplet (rien n'est alors enregistre)."""
        email, people, signatures = self._validate_registration(form, people, signature_png, parent_signatures)
        now = _now_iso()
        family_id = secrets.token_hex(8)
        terms_version = form.get("terms_version") or content.TERMS_VERSION
        results = []
        with self.db.connect() as connection:
            for name, role, png in signatures:
                connection.execute(
                    "INSERT INTO trial_signatures (family_id, signer_name, role, png, signed_at, signed_ip) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (family_id, name, role, png, now, ip),
                )
            for person in people:
                certificate = person.pop("certificate")
                fields = {**person, "email": email, "terms_version": terms_version}
                existing = self._find_existing(connection, fields)
                if existing is not None and existing["qr_token"]:
                    results.append(
                        {
                            "status": "existing",
                            "student": self._to_dict(existing),
                            "token": existing["qr_token"],
                            "familyId": family_id,
                        }
                    )
                    continue
                token = self.new_qr_token()
                fields.update(
                    {
                        "family_id": family_id,
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
                self._store_certificate(connection, student_id, *certificate)
                results.append(
                    {
                        "status": "created",
                        "student": self._to_dict(self._get_row(connection, student_id)),
                        "token": token,
                        "familyId": family_id,
                    }
                )
        return results

    @staticmethod
    def _valid_png(png: bytes | None) -> bool:
        return bool(png) and png.startswith(PNG_MAGIC) and len(png) <= MAX_SIGNATURE_BYTES

    def _validate_registration(
        self, form: dict, people: list[dict], signature_png: bytes, parent_signatures: list[tuple[str, bytes]]
    ) -> tuple[str, list[dict], list[tuple[str, str, bytes]]]:
        """Verifie le formulaire, dans l'ordre de la page (le 1er manque est
        signale). Retourne (e-mail, champs par personne, signatures [(nom,
        role, PNG)]). La signature enregistree sur la ligne d'un eleve est
        celle de la personne qui s'engage pour lui : son parent s'il est
        mineur, la 1re personne sinon."""
        if not 1 <= len(people) <= MAX_FAMILY_SIZE:
            raise RegistrationError(f"Une demande concerne de 1 à {MAX_FAMILY_SIZE} personnes")
        cleaned_people, first_name, first_minor = [], "", False
        for number, person in enumerate(people, start=1):
            label = f" (personne {number})" if len(people) > 1 else ""
            minor = bool(person.get("minor"))
            try:
                fields = self._clean(
                    {
                        "first_name": person.get("first_name"),
                        "last_name": person.get("last_name"),
                        "age": person.get("age") if minor else None,
                    }
                )
            except ValueError as exc:
                raise RegistrationError(f"{exc}{label}") from exc
            full_name = f"{fields['first_name']} {fields['last_name']}"
            if number == 1:
                first_name, first_minor = full_name, minor
            parent_name, parent_external = None, False
            if minor:
                if number > 1 and person.get("parent_is_first"):
                    if first_minor:
                        raise RegistrationError(
                            f"Le parent ou représentant légal ne peut pas être une personne mineure{label}"
                        )
                    parent_name = first_name
                else:
                    try:
                        parent = self._clean(
                            {"first_name": person.get("parent_first_name"), "last_name": person.get("parent_last_name")}
                        )
                    except ValueError as exc:
                        raise RegistrationError(
                            f"Merci d'indiquer le prénom et le nom du parent ou représentant légal{label}"
                        ) from exc
                    parent_name, parent_external = f"{parent['first_name']} {parent['last_name']}", True
            if number == 1:
                try:
                    email = self._clean({"email": form.get("email")}).get("email")
                except ValueError as exc:
                    raise RegistrationError(str(exc)) from exc
                if not email:
                    raise RegistrationError("Merci d'indiquer l'e-mail")
                if not EMAIL_PATTERN.match(email):
                    raise RegistrationError("Adresse e-mail invalide")
            if minor:
                if fields["age"] is None:
                    raise RegistrationError(f"Merci d'indiquer l'âge{label}")
                if not MIN_MINOR_AGE <= fields["age"] < ADULT_AGE:
                    raise RegistrationError(
                        f"L'âge d'un mineur doit être compris entre {MIN_MINOR_AGE} et {ADULT_AGE - 1} ans{label}"
                    )
            if person.get("certificate") is None:
                raise RegistrationError(f"Merci de joindre le certificat médical{label}")
            if not person.get("waiver_accepted"):
                raise RegistrationError(f"Merci d'accepter la décharge de responsabilité{label}")
            fields.update(
                {
                    "parent_name": parent_name,
                    # Autorisation parentale : donnee par la signature du parent.
                    "parental_consent": 1 if minor else 0,
                    "waiver_accepted": 1,
                    "parent_external": parent_external,
                    "certificate": person["certificate"],
                }
            )
            cleaned_people.append(fields)
        names = [(p["first_name"].casefold(), p["last_name"].casefold()) for p in cleaned_people]
        if len(set(names)) != len(names):
            raise RegistrationError("La même personne apparaît deux fois dans la demande")

        # Signatures : la 1re personne, puis chaque representant legal
        # exterieur (une seule fois meme s'il est le parent de 2 enfants).
        if not self._valid_png(signature_png):
            raise RegistrationError(f"Merci de faire signer {first_name}")
        received = {name.strip().casefold(): png for name, png in parent_signatures}
        signatures = [(first_name, "first", signature_png)]
        by_signer = {first_name.casefold(): signature_png}
        for p in cleaned_people:
            if p.pop("parent_external"):
                key = p["parent_name"].casefold()
                if key not in by_signer:
                    png = received.get(key)
                    if not self._valid_png(png):
                        raise RegistrationError(f"Merci de faire signer {p['parent_name']}")
                    signatures.append((p["parent_name"], "parent", png))
                    by_signer[key] = png
            p["signature_png"] = by_signer[(p["parent_name"] or first_name).casefold()]
        return email, cleaned_people, signatures

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

    def get_family_signatures(self, family_id: str | None) -> list[dict]:
        """Signatures d'une demande d'inscription, dans l'ordre (1re personne
        puis representants legaux) : [{"name", "role", "png", "signedAt"}]."""
        if not family_id:
            return []
        with self.db.connect() as connection:
            rows = connection.execute(
                "SELECT signer_name, role, png, signed_at FROM trial_signatures WHERE family_id = ? ORDER BY id",
                (family_id,),
            ).fetchall()
        return [{"name": r["signer_name"], "role": r["role"], "png": r["png"], "signedAt": r["signed_at"]} for r in rows]

    @staticmethod
    def _delete_orphan_signatures(connection) -> None:
        """Signatures des demandes dont plus aucun eleve n'existe."""
        connection.execute(
            "DELETE FROM trial_signatures WHERE family_id NOT IN "
            "(SELECT family_id FROM trial_students WHERE family_id IS NOT NULL)"
        )

    # ----- mail de confirmation -----

    def send_confirmation(self, registrations: list[dict]) -> bool:
        """Envoie (ou renvoie) le mail avec le QR code de chaque personne
        de la demande (voir register), les modalites du cours d'essai, les
        informations saisies, les signatures et les certificats. False si le
        mailer n'est pas configure ; MailError si l'envoi echoue."""
        students = [r["student"] for r in registrations]
        email = students[0].get("email") if students else None
        if self.mailer is None or not email:
            return False
        signatures = self.get_family_signatures(registrations[0].get("familyId"))
        subject, html, text = confirmation_email(students, signatures)
        return self.mailer.send(
            email,
            f"{students[0]['firstName']} {students[0]['lastName']}",
            subject,
            html,
            text,
            inline_images={
                **{qr_cid(i): self.qr_png(r["token"]) for i, r in enumerate(registrations)},
                **{signature_cid(i): sig["png"] for i, sig in enumerate(signatures)},
            },
            attachments=self._certificate_attachments(students),
        )

    def _certificate_attachments(self, students: list[dict]) -> list[tuple[str, bytes, str]]:
        """Certificats medicaux des personnes, en pieces jointes du mail de
        confirmation : "certificat-Lea-Martin.jpg"... Au plus
        MAX_ATTACHMENTS_BYTES au total (Gmail refuse les mails de plus de
        25 Mo) : un certificat qui ferait depasser est laisse de cote (il
        reste consultable dans l'onglet Essai)."""
        attachments, total = [], 0
        for student in students:
            if not student["hasMedicalCertificate"]:
                continue
            path, media_type = self.get_certificate(student["id"])
            if not path.exists():
                continue
            data = path.read_bytes()
            if total + len(data) > MAX_ATTACHMENTS_BYTES:
                print(f"send_confirmation: certificat de l'élève {student['id']} trop volumineux pour le mail")
                continue
            total += len(data)
            name = re.sub(r"[^\w-]+", "-", f"{student['firstName']}-{student['lastName']}").strip("-")
            attachments.append((f"certificat-{name}{path.suffix}", data, media_type))
        return attachments

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
            self._delete_orphan_signatures(connection)
        for row in expired:
            self._delete_certificate(row["medical_certificate_file"])
        return len(expired)
