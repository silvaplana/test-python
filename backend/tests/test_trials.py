"""Tests des eleves en cours d'essai (trials) : regles des cours/QR code et
routes REST. Lancer depuis backend/ : PYTHONPATH=src venv/bin/python -m pytest tests"""

from datetime import date, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from database import Database
from trials import Trials, TrialsReceiver
from trials.trials import TrialCoursesFullError, TrialStudentNotFoundError, today


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
