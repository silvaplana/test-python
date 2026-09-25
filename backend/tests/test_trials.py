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
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1


def test_add_student_computes_age_and_cleans_fields(trials):
    birth = today().replace(year=today().year - 12) + timedelta(days=1)
    student = trials.add_student(" Léa ", "Martin", birth, "F", " Lea@Example.COM ", "")
    assert student["firstName"] == "Léa"
    assert student["email"] == "lea@example.com"
    assert student["phone"] is None
    assert student["age"] == 11
    assert student["qrGenerated"] is False
    assert student["source"] == "manual"


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


def adult_form(**overrides):
    form = {
        "first_name": "Hugo",
        "last_name": "Blanc",
        "birth_date": "1990-01-15",
        "gender": "M",
        "email": "hugo@example.com",
        "phone": "",
        "parent_name": "",
        "medical_attestation": True,
        "parental_consent": False,
        "waiver_accepted": True,
        "terms_version": "2026-09-26",
    }
    form.update(overrides)
    return form


class FakeMailer:
    enabled = True

    def __init__(self):
        self.sent = []

    def send(self, to_email, to_name, subject, html, attachments=None):
        self.sent.append((to_email, subject, html, attachments))
        return True


def test_register_creates_student_with_qr(trials):
    result = trials.register(adult_form(), png_bytes(), None, "1.2.3.4")
    assert result["status"] == "created"
    student = result["student"]
    assert student["source"] == "web" and student["qrGenerated"] and student["hasSignature"]
    assert student["parentName"] is None
    assert trials.qr_png(result["token"]).startswith(b"\x89PNG")
    # le QR code contient l'URL de l'appli : le scan accepte l'URL complete
    assert trials.check_in(f"https://silvaplana.cloud/sambo-admin/?essai={result['token']}")["status"] == "added"


def test_register_twice_returns_existing_same_token(trials):
    first = trials.register(adult_form(), png_bytes(), None, None)
    again = trials.register(adult_form(first_name="HUGO", email="Hugo@Example.com"), png_bytes(), None, None)
    assert again["status"] == "existing" and again["token"] == first["token"]
    sibling = trials.register(adult_form(first_name="Léo"), png_bytes(), None, None)
    assert sibling["status"] == "created" and sibling["token"] != first["token"]


def test_register_completes_manual_student(trials):
    manual = trials.add_student("Hugo", "Blanc", email="hugo@example.com")
    result = trials.register(adult_form(), png_bytes(), None, None)
    assert result["status"] == "created" and result["student"]["id"] == manual["id"]
    assert result["student"]["qrGenerated"] and len(trials.list_students()) == 1


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"birth_date": ""}, "date de naissance"),
        ({"email": "pas-un-mail"}, "e-mail"),
        ({"medical_attestation": False}, "attestation"),
        ({"waiver_accepted": False}, "décharge"),
        ({"birth_date": "2015-03-01"}, "parent"),
        ({"birth_date": "2015-03-01", "parent_name": "Paul Blanc"}, "autorisation parentale"),
    ],
)
def test_register_validation(trials, overrides, message):
    with pytest.raises(RegistrationError, match=message):
        trials.register(adult_form(**overrides), png_bytes(), None, None)


def test_register_minor_and_signature_required(trials):
    with pytest.raises(RegistrationError, match="Signature"):
        trials.register(adult_form(), b"pas une image", None, None)
    minor = adult_form(birth_date="2015-03-01", parent_name="Paul Blanc", parental_consent=True)
    assert trials.register(minor, png_bytes(), None, None)["student"]["parentName"] == "Paul Blanc"


def test_certificate_photo_converted_and_deleted_with_student(trials):
    result = trials.register(adult_form(), png_bytes(), ("certif.png", png_bytes((3000, 1000))), None)
    path, media_type = trials.get_certificate(result["student"]["id"])
    assert media_type == "image/jpeg" and path.exists()
    assert Image.open(path).size == (2000, 667)
    trials.delete_student(result["student"]["id"])
    assert not path.exists()


def test_certificate_pdf_kept_and_garbage_refused(trials):
    result = trials.register(adult_form(), png_bytes(), ("certif.pdf", b"%PDF-1.4 test"), None)
    path, media_type = trials.get_certificate(result["student"]["id"])
    assert media_type == "application/pdf" and path.read_bytes() == b"%PDF-1.4 test"
    with pytest.raises(RegistrationError, match="illisible"):
        trials.register(adult_form(first_name="Léo"), png_bytes(), ("x.doc", b"n'importe quoi"), None)


def test_confirmation_email(trials):
    trials.mailer = FakeMailer()
    result = trials.register(adult_form(), png_bytes(), None, None)
    assert trials.send_confirmation(result["student"], result["token"]) is True
    to_email, subject, html, attachments = trials.mailer.sent[0]
    assert to_email == "hugo@example.com" and "cours d'essai" in subject
    assert f"{result['token']}.png" in html and "Hugo Blanc" in html
    assert attachments[0][1].startswith(b"\x89PNG")


def test_public_routes(trials):
    trials.mailer = FakeMailer()
    app = FastAPI()
    TrialsPublicReceiver(client=trials, app=app)
    client = TestClient(app)
    assert client.get("/public/trials/info").json()["termsVersion"]
    signature = "data:image/png;base64," + base64.b64encode(png_bytes()).decode()
    data = {
        "firstName": "Léa", "lastName": "Martin", "birthDate": "2000-05-03", "gender": "F",
        "email": "lea@example.com", "medicalAttestation": "true", "waiverAccepted": "true",
        "signature": signature,
    }
    created = client.post("/public/trials/register", data=data, files={"certificate": ("c.pdf", b"%PDF-1.4", "application/pdf")})
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["status"] == "created" and body["emailSent"] and base64.b64decode(body["qrPng"]).startswith(b"\x89PNG")
    again = client.post("/public/trials/register", data=data).json()
    assert again == {"status": "existing", "emailSent": True}
    assert len(trials.mailer.sent) == 2
    incomplete = client.post("/public/trials/register", data={**data, "waiverAccepted": "false"})
    assert incomplete.status_code == 422 and "décharge" in incomplete.json()["detail"]
    bot = client.post("/public/trials/register", data={**data, "firstName": "Bot", "website": "spam"})
    assert bot.status_code == 200 and len(trials.list_students()) == 1
    token = trials.register(adult_form(), png_bytes(), None, None)["token"]
    assert client.get(f"/public/trials/qr/{token}.png").headers["content-type"] == "image/png"
    assert client.get("/public/trials/qr/inconnu.png").status_code == 404


def test_public_register_rate_limited(trials):
    app = FastAPI()
    receiver = TrialsPublicReceiver(client=trials, app=app)
    receiver.limiter.limit = 2
    client = TestClient(app)
    codes = [client.post("/public/trials/register", data={"firstName": "x"}).status_code for _ in range(3)]
    assert codes == [422, 422, 429]
