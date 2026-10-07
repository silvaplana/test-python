"""Verification par IA du dossier des adherents (helloasso/verification.py),
avec une IA simulee."""

import io
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from auth import require_accounts_auth
from database import Database
from helloasso import HelloAsso, HelloAssoReceiver
from helloasso.verification import InspectionError, MemberChecks, Verdict, to_images

TODAY = date(2026, 10, 7)
URL = "https://docs.helloasso.com/customFieldsAnswer/"


def jpeg(color="white"):
    buffer = io.BytesIO()
    Image.new("RGB", (40, 30), color).save(buffer, format="JPEG")
    return buffer.getvalue()


def member(item_id, first, birth, files=("photo", "certificat"), state="Processed"):
    names = {"photo": "photo d'identité", "certificat": "Certificat médical d'aptitude", "autorisation": "Autorisation parentale (pour un mineur)"}
    fields = [{"name": "date de naissance", "type": "Date", "answer": birth}, {"name": "Ville", "type": "TextInput", "answer": "La Ciotat"}]
    fields += [{"name": names[key], "type": "File", "answer": f"{URL}{item_id}{index}"} for index, key in enumerate(files)]
    return {"id": item_id, "firstName": first, "lastName": "Martin", "state": state, "orderDate": "2026-09-01", "payer": {"firstName": "Alice", "lastName": "Martin"}, "fields": fields}


class FakeInspector:
    """IA simulee : refuse ce qu'on lui dit de refuser."""

    def __init__(self):
        self.calls = []
        self.refuse = {}
        self.error = None

    def inspect(self, model, answers, documents, today):
        self.calls.append((answers["prenom"], sorted(documents)))
        if self.error:
            raise InspectionError(self.error, cost=0.01)
        results = {key: {"ok": True, "raison": ""} for key in ("photo", "certificat", "autorisation", "donnees")}
        for key, reason in self.refuse.get(answers["prenom"], {}).items():
            results[key] = {"ok": False, "raison": reason}
        return Verdict(results=results, cost=0.02)


@pytest.fixture
def setup(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.migrate()
    people = {
        1: member(1, "Léo", "01/02/1990"),  # majeur, dossier complet
        2: member(2, "Zoé", "01/02/2015", files=("photo", "certificat", "autorisation")),  # mineure complete
        3: member(3, "Tom", "01/02/2015"),  # mineur sans autorisation
        4: member(4, "Ana", "01/02/1990", files=()),  # aucun document
        5: member(5, "Max", "01/02/1990", state="Canceled"),  # adhesion resiliee
    }
    inspector, notified, costs = FakeInspector(), [], []
    checks = MemberChecks(
        db=db,
        members=lambda: [{"id": m["id"], "firstName": m["firstName"], "lastName": m["lastName"], "state": m["state"]} for m in people.values()],
        member=people.get,
        document=lambda url: (jpeg(), "image/jpeg"),
        inspector=inspector,
        notify=lambda detail, issues: notified.append((detail["firstName"], issues)),
        add_cost=costs.append,
        today=lambda: TODAY,
        background=False,
    )
    return checks, inspector, notified, costs, people


def test_complete_file_is_ok_and_never_checked_again(setup):
    checks, inspector, _, costs, _ = setup
    assert checks.check(1) == {"status": "ok", "issues": [], "firstName": "Léo", "lastName": "Martin"}
    assert inspector.calls == [("Léo", ["certificat", "photo"])]
    assert costs == [0.02]

    run = checks.run()
    states = {item["name"]: item["state"] for item in run["items"]}
    # Leo, deja bon, n'est pas reverifie ; l'adhesion resiliee n'apparait pas.
    assert states == {"Léo Martin": "deja", "Zoé Martin": "ok", "Tom Martin": "probleme", "Ana Martin": "probleme"}
    assert [name for name, _ in inspector.calls] == ["Léo", "Zoé", "Tom"]
    assert run["running"] is False


def test_missing_documents_need_no_ai(setup):
    checks, inspector, *_ = setup
    result = checks.check(4)
    assert result["status"] == "probleme"
    assert result["issues"] == ["Photo d'identité manquante", "Certificat médical manquant"]
    assert inspector.calls == []
    # Mineur sans autorisation : signale, et ses autres documents sont controles.
    assert "Autorisation parentale manquante (adhérent mineur)" in checks.check(3)["issues"]
    # L'autorisation d'un majeur n'est pas envoyee a l'IA.
    assert inspector.calls == [("Tom", ["certificat", "photo"])]


def test_ai_reasons_cost_and_manual_ok(setup):
    checks, inspector, _, costs, _ = setup
    inspector.refuse["Léo"] = {"photo": "On ne voit aucune personne sur l'image.", "certificat": "Certificat daté de plus d'un an."}
    assert checks.check(1)["issues"] == [
        "Photo d'identité : On ne voit aucune personne sur l'image.",
        "Certificat médical : Certificat daté de plus d'un an.",
    ]
    checks.check(1)  # relance : le cout s'ajoute
    state = checks.state()
    assert state["checks"][1]["status"] == "probleme" and state["totalCost"] == pytest.approx(0.04)
    assert costs == [0.02, 0.02]

    checks.mark_ok(1)
    assert checks.state()["checks"][1] == {"status": "ok", "issues": [], "manual": True, "checkedAt": checks.state()["checks"][1]["checkedAt"]}
    assert checks.state()["totalCost"] == pytest.approx(0.04)  # le cout deja depense reste compte
    assert {item["name"]: item["state"] for item in checks.run()["items"]}["Léo Martin"] == "deja"


def test_ai_failure_is_an_error_to_retry(setup):
    checks, inspector, _, costs, _ = setup
    inspector.error = "L'appel à l'IA a échoué : quota"
    result = checks.check(1)
    assert (result["status"], result["issues"]) == ("erreur", ["L'appel à l'IA a échoué : quota"])
    assert costs == [0.01]
    inspector.error = None
    assert {item["name"]: item["state"] for item in checks.run()["items"]}["Léo Martin"] == "ok"


def test_new_member_with_a_problem_is_reported(setup):
    checks, _, notified, *_ = setup
    assert checks.check_new_member(1)["status"] == "ok"
    assert notified == []
    checks.check_new_member(4)
    assert notified == [("Ana", ["Photo d'identité manquante", "Certificat médical manquant"])]


def test_unreadable_file(setup):
    checks, inspector, *_ = setup
    checks.document = lambda url: (b"pas une image", "application/octet-stream")
    issues = checks.check(1)["issues"]
    assert len(issues) == 2 and all("fichier illisible" in issue for issue in issues)
    assert inspector.calls == []
    with pytest.raises(ValueError):
        to_images(b"")
    assert len(to_images(jpeg())) == 1


def test_api(setup):
    checks, *_ = setup
    client = HelloAsso(client_id="x", client_secret="y", organization_slug="club")
    app = FastAPI()
    app.dependency_overrides[require_accounts_auth] = lambda: "test"
    receiver = HelloAssoReceiver(client=client, app=app, form_slug="club")
    receiver.enable_member_checks(checks)
    http = TestClient(app)

    assert http.get("/helloasso/checks").json()["checks"] == {}
    run = http.post("/helloasso/checks/run").json()
    assert len(run["items"]) == 4
    state = http.get("/helloasso/checks").json()
    assert state["checks"]["4"]["status"] == "probleme" and state["totalCost"] == pytest.approx(0.06)
    assert http.put("/helloasso/checks/4/ok").json() == {"status": "ok"}
    assert http.get("/helloasso/checks").json()["checks"]["4"]["manual"] is True
    assert http.put("/helloasso/checks/99/ok").status_code == 404

    # Mail recapitulatif a l'association : les dossiers a regarder, sans
    # celui valide a la main ni ceux qui sont bons.
    class FakeMailer:
        enabled = True
        sender = "club@example.org"

        def __init__(self):
            self.sent = []

        def send(self, to_email, to_name, subject, html, text, **options):
            self.sent.append((to_email, subject, text, options))

    mailer = FakeMailer()
    receiver.enable_member_mail(mailer, contact="contact@example.org", sender="sambo-admin@silvaplana.cloud")
    report = http.post("/helloasso/checks/report").json()
    assert report == {"sent": True, "to": "contact@example.org", "count": 1}
    to, subject, text, options = mailer.sent[0]
    assert (to, subject, options["sender"]) == ("contact@example.org", "Adhérents : 1 dossier d'adhérent à vérifier", "sambo-admin@silvaplana.cloud")
    assert "Tom Martin\n- Autorisation parentale manquante (adhérent mineur)" in text and "Ana" not in text
    http.put("/helloasso/checks/3/ok")
    assert http.post("/helloasso/checks/report").status_code == 400  # plus rien a signaler
