"""Tests des eleves en cours d'essai (trials) : regles des cours/QR code et
routes REST. Lancer depuis backend/ : PYTHONPATH=src venv/bin/python -m pytest tests"""

import base64
import io
from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from database import Database
from database.database import MIGRATIONS
from mailer import Mailer
from trials import Trials, TrialsPublicReceiver, TrialsReceiver
from trials.trials import RegistrationError, TrialCoursesFullError, TrialStudentNotFoundError, today


@pytest.fixture
def trials(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.migrate()
    return Trials(db=db, certificates_dir=str(tmp_path / "certificates"))


def give_qr(trials, student_id):
    """Simule l'inscription en ligne (etape 2) : attribue un QR code."""
    token = trials.new_qr_token()
    with trials.db.connect() as connection:
        connection.execute("UPDATE trial_students SET qr_token = ? WHERE id = ?", (token, student_id))
    return token


def test_migrate_is_idempotent(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.migrate()
    db.migrate()
    with db.connect() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)


def test_add_student_computes_age_and_cleans_fields(trials):
    birth = today().replace(year=today().year - 12) + timedelta(days=1)
    student = trials.add_student(
        " Léa ", "Martin", birth_date=birth, gender="F", email=" Lea@Example.COM ", phone=""
    )
    assert student["firstName"] == "Léa"
    assert student["email"] == "lea@example.com"
    assert student["phone"] is None
    assert student["age"] == 11
    assert student["qrGenerated"] is False
    assert student["source"] == "manual"
    # age saisi : prioritaire sur la date de naissance
    assert trials.update_student(student["id"], {"age": "14"})["age"] == 14
    with pytest.raises(ValueError, match="Âge"):
        trials.update_student(student["id"], {"age": 2})


def test_add_student_requires_names(trials):
    with pytest.raises(ValueError):
        trials.add_student("", "Martin")


def test_manual_courses_fill_first_free_slot_then_full(trials):
    student = trials.add_student("Hugo", "Blanc")
    trials.add_course(student["id"], "2026-10-02")
    student = trials.add_course(student["id"])
    assert [c["date"] for c in student["courses"]] == ["2026-10-02", today().isoformat()]
    assert [c["mode"] for c in student["courses"]] == ["manual", "manual"]
    with pytest.raises(TrialCoursesFullError):
        trials.add_course(student["id"])


def test_set_course_clears_and_keeps_mode(trials):
    student = trials.add_student("Hugo", "Blanc")
    token = give_qr(trials, student["id"])
    trials.check_in(token)
    student = trials.set_course(student["id"], 1, "2026-10-01")
    assert student["courses"][0] == {"number": 1, "date": "2026-10-01", "mode": "qr"}
    student = trials.set_course(student["id"], 1, None)
    assert student["courses"][0] == {"number": 1, "date": None, "mode": None}


def test_check_in_is_single_use(trials):
    student = trials.add_student("Léa", "Martin")
    token = give_qr(trials, student["id"])
    assert trials.check_in("inconnu") == {"status": "unknown"}
    assert trials.check_in("") == {"status": "unknown"}
    result = trials.check_in(token)
    assert result["status"] == "added" and result["course"] == 1
    again = trials.check_in(token)
    assert again["status"] == "used" and again["date"] == today().isoformat()


def test_check_in_after_manual_first_course_fills_second(trials):
    student = trials.add_student("Léa", "Martin")
    token = give_qr(trials, student["id"])
    trials.add_course(student["id"], "2026-10-02")
    result = trials.check_in(token)
    assert result["status"] == "added" and result["course"] == 2
    assert result["student"]["courses"][1]["mode"] == "qr"


def test_check_in_when_both_courses_manual(trials):
    student = trials.add_student("Léa", "Martin")
    token = give_qr(trials, student["id"])
    trials.add_course(student["id"], "2026-10-02")
    trials.add_course(student["id"], "2026-10-09")
    assert trials.check_in(token)["status"] == "full"


def test_update_and_delete(trials, tmp_path):
    student = trials.add_student("Léa", "Martin")
    student = trials.update_student(student["id"], {"comment": "Très motivée", "phone": "0600000000"})
    assert student["comment"] == "Très motivée" and student["phone"] == "0600000000"
    with pytest.raises(ValueError):
        trials.update_student(student["id"], {"qr_token": "x"})
    trials.delete_student(student["id"])
    with pytest.raises(TrialStudentNotFoundError):
        trials.get_student(student["id"])


def test_purge_expired_keeps_recent_activity(trials):
    old = trials.add_student("Ancien", "Élève")
    active = trials.add_student("Actif", "Élève")
    with trials.db.connect() as connection:
        connection.execute("UPDATE trial_students SET created_at = '2020-01-01T10:00:00+00:00'")
    trials.set_course(active["id"], 1, today() - timedelta(days=30))
    assert trials.purge_expired() == 1
    assert [s["id"] for s in trials.list_students()] == [active["id"]]
    assert old["id"] != active["id"]


def test_rest_routes(trials):
    app = FastAPI()
    TrialsReceiver(client=trials, app=app)
    client = TestClient(app)

    response = client.post("/trials/students", json={"firstName": "Léa", "lastName": "Martin", "birthDate": "2014-05-03"})
    assert response.status_code == 200
    student_id = response.json()["id"]

    assert client.post(f"/trials/students/{student_id}/courses", json={}).json()["courses"][0]["mode"] == "manual"
    assert client.post(f"/trials/students/{student_id}/courses", json={"date": "2026-10-09"}).status_code == 200
    assert client.post(f"/trials/students/{student_id}/courses", json={}).status_code == 409
    assert client.put(f"/trials/students/{student_id}/courses/2", json={"date": None}).json()["courses"][1]["date"] is None
    assert client.put(f"/trials/students/{student_id}/courses/3", json={"date": None}).status_code == 422
    assert client.patch(f"/trials/students/{student_id}", json={"comment": "ok"}).json()["comment"] == "ok"
    assert client.post("/trials/checkin", json={"token": "nope"}).json() == {"status": "unknown"}
    assert len(client.get("/trials/students").json()) == 1
    assert client.delete(f"/trials/students/{student_id}").status_code == 200
    assert client.delete(f"/trials/students/{student_id}").status_code == 404
    assert client.post("/trials/students", json={"firstName": "Léa", "lastName": "Martin", "gender": "X"}).status_code == 422


# ----- inscription en ligne (page publique) -----


def png_bytes(size=(40, 20), fmt="PNG"):
    buffer = io.BytesIO()
    Image.new("RGB", size, "white").save(buffer, format=fmt)
    return buffer.getvalue()


# Certificat medical (obligatoire pour chaque personne).
CERT = ("certif.pdf", b"%PDF-1.4 test")


def person(first_name="Hugo", last_name="Blanc", age=None, certificate=CERT, waiver_accepted=True, minor=None):
    """Adulte par defaut ; age donne -> mineur (sauf minor explicite)."""
    return {
        "first_name": first_name,
        "last_name": last_name,
        "minor": age is not None if minor is None else minor,
        "age": age,
        "waiver_accepted": waiver_accepted,
        "certificate": certificate,
    }


def form(**overrides):
    fields = {
        "email": "hugo@example.com",
        "parent_name": "",
        "parental_consent": False,
        "terms_version": "2026-09-29b",
    }
    fields.update(overrides)
    return fields


def register(trials, people=None, signature=None, **overrides):
    return trials.register(form(**overrides), people or [person()], signature or png_bytes(), "1.2.3.4")


class FakeMailer:
    enabled = True

    def __init__(self):
        self.sent = []

    def send(self, to_email, to_name, subject, html, text, inline_images=None, attachments=None):
        self.sent.append((to_email, subject, html, inline_images))
        self.attachments = attachments
        self.text = text
        return True


def test_register_creates_student_with_qr(trials):
    [result] = register(trials)
    assert result["status"] == "created"
    student = result["student"]
    assert student["source"] == "web" and student["qrGenerated"] and student["hasSignature"]
    assert student["age"] is None and student["parentName"] is None and student["familyId"] is None
    assert student["hasMedicalCertificate"]
    assert trials.qr_png(result["token"]).startswith(b"\x89PNG")
    # le QR code contient l'URL de l'appli : le scan accepte l'URL complete
    assert trials.check_in(f"https://silvaplana.cloud/sambo-admin/?essai={result['token']}")["status"] == "added"


def test_register_family_one_qr_per_person(trials):
    people = [person("Paul", "Martin"), person("Léa", "Martin", 12), person("Tom", "Martin", 9)]
    results = register(trials, people, email="paul@example.com", parent_name="Paul Martin", parental_consent=True)
    assert [r["status"] for r in results] == ["created"] * 3
    tokens = {r["token"] for r in results}
    families = {r["student"]["familyId"] for r in results}
    assert len(tokens) == 3 and len(families) == 1 and None not in families
    # parent et autorisation parentale : seulement sur les lignes des mineurs
    assert [r["student"]["parentName"] for r in results] == [None, "Paul Martin", "Paul Martin"]
    assert [r["student"]["parentalConsent"] for r in results] == [False, True, True]
    assert [r["student"]["age"] for r in results] == [None, 12, 9]
    # chaque QR code est independant
    assert trials.check_in(results[1]["token"])["status"] == "added"
    assert trials.check_in(results[2]["token"])["status"] == "added"
    assert trials.check_in(results[1]["token"])["status"] == "used"


def test_register_twice_returns_existing_same_token(trials):
    [first] = register(trials)
    [again] = register(trials, [person("HUGO", "Blanc")], email="Hugo@Example.com")
    assert again["status"] == "existing" and again["token"] == first["token"]
    # meme demande : Hugo deja inscrit, Léo nouveau
    results = register(trials, [person(), person("Léo", "Blanc", 8)], parent_name="Anne Blanc", parental_consent=True)
    assert [r["status"] for r in results] == ["existing", "created"]
    assert results[1]["token"] != first["token"]


def test_register_completes_manual_student(trials):
    manual = trials.add_student("Hugo", "Blanc", email="hugo@example.com")
    [result] = register(trials)
    assert result["status"] == "created" and result["student"]["id"] == manual["id"]
    assert result["student"]["qrGenerated"] and len(trials.list_students()) == 1


@pytest.mark.parametrize(
    "people, overrides, message",
    [
        ([person(first_name="")], {}, "prénom"),
        ([person()], {"email": ""}, "e-mail"),
        ([person()], {"email": "pas-un-mail"}, "e-mail"),
        ([person(minor=True)], {}, "âge"),
        ([person(age=2)], {}, "Âge invalide"),
        ([person(age="douze")], {}, "Âge invalide"),
        ([person(age=25)], {}, "moins de 18 ans"),
        ([person(certificate=None)], {}, "certificat médical"),
        ([person(waiver_accepted=False)], {}, "décharge"),
        ([person(), person("Léa", certificate=None)], {}, r"certificat médical \(personne 2\)"),
        ([person(), person("Léa", waiver_accepted=False)], {}, r"décharge de responsabilité \(personne 2\)"),
        ([person(), person("hugo", "BLANC")], {}, "deux fois"),
        ([person()] * 4, {}, "de 1 à 3"),
        ([person(age=12)], {}, "parent"),
        ([person(age=12)], {"parent_name": "Paul Blanc"}, "autorisation parentale"),
    ],
)
def test_register_validation(trials, people, overrides, message):
    with pytest.raises(RegistrationError, match=message):
        register(trials, people, **overrides)
    assert trials.list_students() == []


def test_register_signature_required_and_adult_parent_ignored(trials):
    with pytest.raises(RegistrationError, match="Signature"):
        register(trials, signature=b"pas une image")
    [result] = register(trials, parent_name="X")
    assert result["student"]["parentName"] is None and not result["student"]["parentalConsent"]


def test_certificate_photo_converted_and_deleted_with_student(trials):
    [result] = register(trials, [person(certificate=("certif.png", png_bytes((3000, 1000))))])
    path, media_type = trials.get_certificate(result["student"]["id"])
    assert media_type == "image/jpeg" and path.exists()
    assert Image.open(path).size == (2000, 667)
    trials.delete_student(result["student"]["id"])
    assert not path.exists()


def test_certificate_pdf_kept_and_garbage_refused(trials):
    [result] = register(trials)
    path, media_type = trials.get_certificate(result["student"]["id"])
    assert media_type == "application/pdf" and path.read_bytes() == CERT[1]
    with pytest.raises(RegistrationError, match="illisible"):
        register(trials, [person("Léo", certificate=("x.doc", b"n'importe quoi"))])


def test_confirmation_email_one_qr_per_person(trials):
    trials.mailer = FakeMailer()
    results = register(trials, [person(), person("Léo", "Blanc", 8)], parent_name="Anne Blanc", parental_consent=True)
    assert trials.send_confirmation(results) is True
    [(to_email, subject, html, inline_images)] = trials.mailer.sent
    assert to_email == "hugo@example.com" and "cours d'essai" in subject
    assert "Hugo Blanc et Léo Blanc" in html
    assert 'src="cid:qrcode-0"' in html and 'src="cid:qrcode-1"' in html
    assert all(png.startswith(b"\x89PNG") for png in inline_images.values()) and len(inline_images) == 3
    # recapitulatif des donnees saisies + certificats en pieces jointes
    assert "Informations renseignées par Hugo Blanc" in html and "8 ans (mineur)" in html and "Anne Blanc" in html
    assert 'src="cid:signature"' in html and "Signée le" in html
    assert inline_images["signature"] == png_bytes()
    assert "Autorisation parentale : donnée" in trials.mailer.text
    assert trials.mailer.text.count("Décharge de responsabilité : acceptée par Hugo Blanc") == 2
    assert [(name, mime) for name, _, mime in trials.mailer.attachments] == [
        ("certificat-Hugo-Blanc.pdf", "application/pdf"),
        ("certificat-Léo-Blanc.pdf", "application/pdf"),
    ]


def test_mailer_builds_smtp_message(monkeypatch):
    """Le mail reellement envoye (faux serveur SMTP) : STARTTLS + login,
    expediteur, reponse, version texte et QR code integre (cid)."""
    sent = {}

    class FakeSmtp:
        def __init__(self, host, port, timeout):
            sent["server"] = (host, port)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def starttls(self, context):
            sent["tls"] = True

        def login(self, user, password):
            sent["login"] = (user, password)

        def send_message(self, message):
            sent["message"] = message

    monkeypatch.setattr("mailer.mailer.smtplib.SMTP", FakeSmtp)
    mailer = Mailer("smtp.gmail.com", 587, "club@gmail.com", "app-password", "", "Club", "club@outlook.fr")
    assert mailer.send(
        "lea@example.com", "Léa Martin", "Sujet", '<img src="cid:qrcode">', "texte", {"qrcode": png_bytes()},
        [("certificat-Lea.pdf", b"%PDF-1.4", "application/pdf")],
    )
    message = sent["message"]
    assert sent["server"] == ("smtp.gmail.com", 587) and sent["tls"] and sent["login"][0] == "club@gmail.com"
    assert message["From"] == "Club <club@gmail.com>" and message["Reply-To"] == "club@outlook.fr"
    image = next(part for part in message.walk() if part.get_content_type() == "image/png")
    assert image["Content-ID"] == "<qrcode>"
    assert message.get_body(("plain",)).get_content().strip() == "texte"
    [attachment] = list(message.iter_attachments())
    assert attachment.get_filename() == "certificat-Lea.pdf" and attachment.get_content() == b"%PDF-1.4"


def test_mailer_disabled_without_credentials():
    assert Mailer("smtp.gmail.com", 587, "", "", "", "Club").send("a@b.fr", "A", "S", "h", "t") is False


def test_public_routes(trials):
    trials.mailer = FakeMailer()
    app = FastAPI()
    TrialsPublicReceiver(client=trials, app=app)
    client = TestClient(app)
    assert client.get("/public/trials/info").json()["termsVersion"]
    signature = "data:image/png;base64," + base64.b64encode(png_bytes()).decode()
    data = {
        "email": "martin@example.com", "parentName": "Paul Martin", "parentalConsent": "true",
        "signature": signature,
        "firstName0": "Léa", "lastName0": "Martin", "minor0": "true", "age0": "12", "waiverAccepted0": "true",
        "firstName1": "Tom", "lastName1": "Martin", "minor1": "false", "age1": "", "waiverAccepted1": "true",
    }
    files = {
        "certificate0": ("c0.pdf", b"%PDF-1.4", "application/pdf"),
        "certificate1": ("c1.pdf", b"%PDF-1.4", "application/pdf"),
    }
    missing = client.post("/public/trials/register", data=data, files={"certificate0": files["certificate0"]})
    assert missing.status_code == 422 and "certificat" in missing.json()["detail"]
    created = client.post("/public/trials/register", data=data, files=files)
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["emailSent"] and [p["status"] for p in body["people"]] == ["created", "created"]
    assert base64.b64decode(body["people"][1]["qrPng"]).startswith(b"\x89PNG")
    again = client.post("/public/trials/register", data=data, files=files).json()
    assert [p["status"] for p in again["people"]] == ["existing", "existing"]
    assert "qrPng" not in again["people"][0] and again["emailSent"]
    assert len(trials.mailer.sent) == 2
    incomplete = client.post("/public/trials/register", data={**data, "waiverAccepted1": "false"}, files=files)
    assert incomplete.status_code == 422 and "décharge" in incomplete.json()["detail"]
    bot = client.post("/public/trials/register", data={**data, "firstName0": "Bot", "website": "spam"}, files=files)
    assert bot.json() == {"people": [], "emailSent": False} and len(trials.list_students()) == 2


def test_public_register_rate_limited(trials):
    app = FastAPI()
    receiver = TrialsPublicReceiver(client=trials, app=app)
    receiver.limiter.limit = 2
    client = TestClient(app)
    codes = [client.post("/public/trials/register", data={"firstName0": "x"}).status_code for _ in range(3)]
    assert codes == [422, 422, 429]
