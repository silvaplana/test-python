import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from database import Database
from helloasso import HelloAssoReceiver
from helloasso.mails import MessageTemplates, TemplateError


@pytest.fixture
def templates(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    database.migrate()
    return MessageTemplates(database)


def test_mail_and_sms_templates_are_separate(templates):
    assert templates.list("mail") == []
    templates.save("mail", "  Certificat   médical ", "Bonjour {prénom},\nil manque votre certificat.\n")
    templates.save("mail", "Certificat médical", "Bonjour {prénom},\nil manque votre certificat.")  # doublon ignore
    mails = templates.save("mail", "Reprise", "Les cours reprennent lundi.")
    assert [(t["subject"], t["body"]) for t in mails] == [
        ("Reprise", "Les cours reprennent lundi."),
        ("Certificat médical", "Bonjour {prénom},\nil manque votre certificat."),
    ]
    # SMS : pas d'objet, liste a part.
    sms = templates.save("sms", "ignoré", "Bonjour {prénom}, cours annulé ce soir.")
    assert [(t["subject"], t["body"]) for t in sms] == [("", "Bonjour {prénom}, cours annulé ce soir.")]
    assert len(templates.list("mail")) == 2

    # Supprimer : seulement dans son genre.
    assert len(templates.delete("sms", mails[0]["id"])) == 1
    assert len(templates.list("mail")) == 2
    assert [t["subject"] for t in templates.delete("mail", mails[0]["id"])] == ["Certificat médical"]


def test_template_validation(templates):
    with pytest.raises(TemplateError):
        templates.save("mail", "", "Corps")
    with pytest.raises(TemplateError):
        templates.save("mail", "Objet", "   ")
    with pytest.raises(TemplateError):
        templates.save("sms", "", "")
    with pytest.raises(TemplateError):
        templates.list("courrier")


def test_template_routes(templates):
    app = FastAPI()
    receiver = HelloAssoReceiver(client=None, app=app, form_slug="test")
    receiver.enable_member_mail(mailer=None, contact=None, sender=None, templates=templates)
    client = TestClient(app)
    saved = client.post("/helloasso/templates", json={"kind": "mail", "subject": "Objet", "body": "Corps"}).json()
    assert [t["subject"] for t in saved["templates"]] == ["Objet"]
    assert client.get("/helloasso/templates", params={"kind": "mail"}).json() == saved
    assert client.post("/helloasso/templates", json={"kind": "mail", "subject": "", "body": "Corps"}).status_code == 400
    assert client.get("/helloasso/templates", params={"kind": "autre"}).status_code == 400
    removed = client.delete(f"/helloasso/templates/{saved['templates'][0]['id']}", params={"kind": "mail"}).json()
    assert removed == {"templates": []}
