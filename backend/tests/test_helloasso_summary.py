"""Chiffres des adherents (helloasso/summary.py)."""

from datetime import date

import pytest

from helloasso.summary import bank_cash_outs, members_summary

TODAY = date(2026, 10, 6)


def member(birth, amount):
    return {"amount": amount, "customFields": {"date de naissance": birth}}


def payment(amount, state, day):
    return {"amount": amount, "state": state, "date": f"{day}T10:00:00+02:00"}


def test_adults_minors_and_average_price():
    members = [
        member("06/10/2008", 250.0),  # 18 ans aujourd'hui : majeur
        member("07/10/2008", 180.0),  # 18 ans demain : mineur
        member("15/03/2015", 180.0),
        member("01/01/1980", 0.0),  # licence offerte
        member("", 250.0),
        member("31/02/2000", 250.0),  # date impossible
    ]

    summary = members_summary(members, [], TODAY)

    assert (summary["members"], summary["adults"], summary["minors"], summary["unknownAge"]) == (6, 2, 2, 2)
    assert summary["totalPrice"] == 1110.0
    assert summary["averagePrice"] == 185.0
    assert summary["freeMembers"] == 1


def test_remaining_by_month():
    payments = [
        {
            "payments": [
                payment(83.34, "Authorized", "2026-09-05"),
                payment(83.33, "Pending", "2026-10-05"),
                payment(83.33, "Pending", "2026-11-05"),
            ]
        },
        {
            "payments": [
                payment(60.0, "Authorized", "2026-09-10"),
                payment(60.0, "Refused", "2026-10-10"),
                payment(60.0, "Waiting", "2026-11-10"),
            ]
        },
        {"payments": [payment(180.0, "Refunded", "2026-09-01")]},
    ]

    summary = members_summary([], payments, TODAY)

    assert summary["remaining"] == [
        {"month": "2026-10", "amount": 83.33, "payments": 1},
        {"month": "2026-11", "amount": 143.33, "payments": 2},
    ]
    assert summary["remainingTotal"] == pytest.approx(226.66)
    assert summary["unpaidTotal"] == 60.0


def test_cash_from_account_to_upcoming_installments():
    def paid(amount, cash_out, cash_out_date=None, means="Card"):
        return {"amount": amount, "state": "Authorized", "date": "2026-09-01T10:00:00+02:00", "paymentMeans": means,
                "cashOutState": cash_out, "cashOutDate": cash_out_date}

    payments = [
        {"payments": [
            paid(200, "CashedOut", "2026-09-03T08:00:00+02:00"),
            paid(100.5, "CashedOut", "2026-09-03T08:00:00+02:00"),
            paid(100, "CashedOut", "2026-09-08T08:00:00+02:00"),
            paid(150, "WaitingForCashOutConfirmation", "2026-10-07T08:00:00+02:00"),
            paid(120, "Transfered"),
            paid(30, "MoneyIn"),
            paid(60, None, means="Check"),          # cheque : jamais passe par HelloAsso
            paid(999, "Refunded"),                   # rembourse : nulle part
            payment(80, "Pending", "2026-11-30T00:00:00+01:00"),
            payment(80, "Pending", "2026-11-30T00:00:00+01:00"),
            payment(70, "Pending", "2026-12-13T00:00:00+01:00"),
            payment(50, "Refused", "2026-10-01T00:00:00+02:00"),  # impaye : compte a part
        ]},
    ]
    cash = members_summary([], payments, TODAY)["cash"]
    assert cash["onAccount"] == {"total": 400.5, "payments": 3, "rows": [
        {"date": "2026-09-03", "amount": 300.5, "payments": 2},
        {"date": "2026-09-08", "amount": 100.0, "payments": 1},
    ]}
    assert cash["inTransit"] == {"total": 150.0, "payments": 1, "rows": [{"date": "2026-10-07", "amount": 150.0, "payments": 1}]}
    assert cash["held"] == {"total": 150.0, "payments": 2}
    assert cash["offline"] == {"total": 60.0, "payments": 1}
    assert cash["upcoming"] == {"total": 230.0, "payments": 3, "rows": [
        {"date": "2026-11-30", "amount": 160.0, "payments": 2},
        {"date": "2026-12-13", "amount": 70.0, "payments": 1},
    ]}
    # Encore a recevoir sur le compte courant : en cours + chez HelloAsso + a venir.
    assert cash["toReceive"] == 530.0


def test_bank_decides_what_has_arrived():
    """HelloAsso garde "en attente de confirmation" apres l'arrivee de
    l'argent : c'est le virement vu a la banque qui compte."""
    def paid(amount, cash_out, cash_out_date):
        return {"amount": amount, "state": "Authorized", "date": "2026-09-01T10:00:00+02:00", "paymentMeans": "Card",
                "cashOutState": cash_out, "cashOutDate": cash_out_date}

    payments = [{"payments": [
        paid(300, "CashedOut", "2026-09-03T08:00:00+02:00"),
        paid(6000, "WaitingForCashOutConfirmation", "2026-10-07T08:00:00+02:00"),
        paid(746.2, "WaitingForCashOutConfirmation", "2026-10-07T08:00:00+02:00"),
        paid(50, "CashedOut", "2026-10-08T08:00:00+02:00"),  # verse selon HelloAsso, pas encore vu a la banque
        paid(120, "Transfered", None),
    ]}]
    ledger = {"rows": [
        {"date": "2026-09-07", "amount": 300.0, "label": "VIR HELLOASSOPAY R4WOXYY6WK2XP0Q HELLOASSO 3591881 03-09-2026"},
        {"date": "2026-10-08", "amount": 6746.2, "label": "VIR HELLOASSOPAY DVMQXO4Y7VJX70Y HELLOASSO 3711911 07-10-2026"},
        {"date": "2026-10-08", "amount": -45.0, "label": "PRLV HELLOASSO 01-10-2026"},   # un debit n'est pas un versement
        {"date": "2026-10-09", "amount": 20.0, "label": "VIR M DUPONT COTISATION"},
    ]}
    bank = bank_cash_outs(ledger)
    assert bank == {"asOf": "2026-10-09", "received": {
        "2026-09-03": {"date": "2026-09-07", "amount": 300.0},
        "2026-10-07": {"date": "2026-10-08", "amount": 6746.2},
    }}
    cash = members_summary([], payments, TODAY, bank)["cash"]
    assert cash["onAccount"] == {"total": 7046.2, "payments": 3, "rows": [
        {"date": "2026-09-07", "requested": "2026-09-03", "amount": 300.0, "payments": 1},
        {"date": "2026-10-08", "requested": "2026-10-07", "amount": 6746.2, "payments": 2},
    ]}
    assert cash["inTransit"]["rows"] == [{"date": "2026-10-08", "amount": 50.0, "payments": 1}]
    assert (cash["held"]["total"], cash["toReceive"], cash["bankAsOf"]) == (120.0, 170.0, "2026-10-09")

    # Sans les comptes : on se fie a HelloAsso.
    alone = members_summary([], payments, TODAY)["cash"]
    assert (alone["onAccount"]["total"], alone["inTransit"]["total"], alone["bankAsOf"]) == (350.0, 6746.2, None)


def test_no_members():
    summary = members_summary([], [], TODAY)

    assert summary["averagePrice"] is None
    assert summary["remaining"] == []
    assert summary["remainingTotal"] == 0


def test_canceled_members_do_not_count():
    members = [member("01/01/1990", 300.0), {**member("01/01/2015", 0.0), "state": "Canceled"}]

    summary = members_summary(members, [], TODAY)

    assert (summary["members"], summary["adults"], summary["minors"], summary["freeMembers"]) == (1, 1, 0, 0)


def test_cancellation_preview():
    from helloasso.summary import cancellation_preview

    order = {
        "id": 7,
        "date": "2026-09-01T10:00:00+02:00",
        "payer": {"firstName": "Alice", "lastName": "Martin"},
        "items": [
            {"type": "Membership", "state": "Processed", "amount": 30000, "user": {"firstName": "Léo", "lastName": "Martin"}},
            {"type": "Membership", "state": "Processed", "amount": 0, "discount": {"code": "BUREAU"}, "user": {}},
            {"type": "Donation", "state": "Processed", "amount": 500},
        ],
        "payments": [
            {"amount": 10000, "state": "Authorized"},
            {"amount": 10000, "state": "Pending"},
            {"amount": 10000, "state": "Pending"},
            {"amount": 500, "state": "Refused"},
        ],
    }

    preview = cancellation_preview(order)

    assert [(m["firstName"], m["lastName"], m["amount"], m["promoCode"]) for m in preview["members"]] == [
        ("Léo", "Martin", 300.0, None),
        ("Alice", "Martin", 0.0, "BUREAU"),
    ]
    assert (preview["paid"], preview["scheduled"], preview["scheduledCount"], preview["unpaid"]) == (100.0, 200.0, 2, 5.0)
    assert preview["payer"] == "Alice Martin" and preview["canceled"] is False
    for item in order["items"]:
        item["state"] = "Canceled"
    assert cancellation_preview(order)["canceled"] is True


def test_cancel_order_api():
    """Routes de resiliation : apercu, appel a HelloAsso, refus d'une
    commande d'un autre formulaire ou deja resiliee."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from auth import require_accounts_auth
    from helloasso import HelloAssoReceiver

    class FakeHelloAsso:
        def __init__(self):
            self.canceled = []
            self.orders = [
                {"id": 7, "payer": {"firstName": "A", "lastName": "B"}, "payments": [], "items": [{"type": "Membership", "state": "Processed", "amount": 0, "user": {}}]}
            ]

        def get_form_orders(self, form_slug, form_type):
            return self.orders

        def cancel_order(self, order_id):
            self.canceled.append(order_id)
            self.orders[0]["items"][0]["state"] = "Canceled"

    fake = FakeHelloAsso()
    app = FastAPI()
    app.dependency_overrides[require_accounts_auth] = lambda: "test"
    HelloAssoReceiver(client=fake, app=app, form_slug="club")
    http = TestClient(app)

    assert http.get("/helloasso/orders/7/cancellation").json()["members"][0]["lastName"] == "B"
    assert http.post("/helloasso/orders/99/cancel").status_code == 404
    assert http.post("/helloasso/orders/7/cancel").json()["canceled"] is True
    assert fake.canceled == [7]
    assert http.post("/helloasso/orders/7/cancel").status_code == 400
    assert fake.canceled == [7]


def test_member_detail_and_document_api(monkeypatch):
    """Fiche d'un adherent (toutes ses informations HelloAsso) et relais de
    ses documents, limite aux fichiers heberges par HelloAsso."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from helloasso import HelloAsso, HelloAssoReceiver

    order = {
        "id": 7,
        "date": "2026-09-01T10:00:00+02:00",
        "payer": {"firstName": "Alice", "lastName": "Martin", "email": "alice@example.org", "city": "La Ciotat"},
        "payments": [
            {"id": 1, "date": "2026-09-01", "state": "Authorized", "paymentMeans": "Card", "installmentNumber": 1},
            {"id": 2, "date": "2026-10-01", "state": "Pending", "paymentMeans": "Card", "installmentNumber": 2},
        ],
        "items": [
            {
                "id": 42,
                "type": "Membership",
                "state": "Processed",
                "name": "Cotisation annuelle",
                "amount": 20000,
                "initialAmount": 30000,
                "discount": {"code": "ANCIEN_2"},
                "user": {"firstName": "Léo", "lastName": "Martin"},
                "payments": [{"id": 1, "shareAmount": 10000}, {"id": 2, "shareAmount": 10000}],
                "customFields": [
                    {"name": "date de naissance", "type": "Date", "answer": "01/02/2015"},
                    {"name": "Certificat médical d'aptitude", "type": "File", "answer": "https://docs.helloasso.com/customFieldsAnswer/123"},
                ],
            }
        ],
    }
    client = HelloAsso(client_id="x", client_secret="y", organization_slug="club")
    monkeypatch.setattr(client, "get_form_orders", lambda form_slug, form_type="Membership": [order])
    fetched = []
    monkeypatch.setattr(client, "get_document", lambda url: fetched.append(url) or (b"%PDF-1.4", "application/pdf"))
    app = FastAPI()
    HelloAssoReceiver(client=client, app=app, form_slug="club")
    http = TestClient(app)

    member = http.get("/helloasso/members/42").json()
    assert (member["firstName"], member["tierName"], member["amount"], member["initialAmount"], member["promoCode"]) == (
        "Léo",
        "Cotisation annuelle",
        200.0,
        300.0,
        "ANCIEN_2",
    )
    assert member["payer"]["email"] == "alice@example.org" and member["orderId"] == 7
    assert [(p["installmentNumber"], p["amount"], p["state"]) for p in member["payments"]] == [(1, 100.0, "Authorized"), (2, 100.0, "Pending")]
    assert member["fields"][1] == {"name": "Certificat médical d'aptitude", "type": "File", "answer": "https://docs.helloasso.com/customFieldsAnswer/123"}
    assert http.get("/helloasso/members/999").status_code == 404

    document = http.get("/helloasso/document", params={"url": "https://docs.helloasso.com/customFieldsAnswer/123"})
    assert document.status_code == 200 and document.headers["content-type"] == "application/pdf"
    assert "no-store" in document.headers["cache-control"]
    # Jamais une autre adresse : le relais porte les identifiants du club.
    for url in ("https://example.org/customFieldsAnswer/123", "https://docs.helloasso.com/autre/123", "http://docs.helloasso.com/customFieldsAnswer/123"):
        assert http.get("/helloasso/document", params={"url": url}).status_code == 400
    assert fetched == ["https://docs.helloasso.com/customFieldsAnswer/123"]


def test_member_mail(monkeypatch, tmp_path):
    """Mail a un adherent : destinataire relu chez HelloAsso, association en
    copie et en adresse de reponse, expediteur dedie."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from helloasso import HelloAsso, HelloAssoReceiver

    class FakeMailer:
        enabled = True
        sender = "club@example.org"

        def __init__(self):
            self.sent = []

        def send(self, to_email, to_name, subject, html, text, **options):
            self.sent.append({"to": to_email, "name": to_name, "subject": subject, "html": html, "text": text, **options})
            return True

    order = {
        "id": 7,
        "payer": {"firstName": "Alice", "lastName": "Martin", "email": "alice@example.org"},
        "payments": [],
        "items": [{"id": 42, "type": "Membership", "state": "Processed", "amount": 0, "user": {"firstName": "Léo", "lastName": "Martin"}, "customFields": []}],
    }
    client = HelloAsso(client_id="x", client_secret="y", organization_slug="club")
    monkeypatch.setattr(client, "get_form_orders", lambda form_slug, form_type="Membership": [order])
    mailer = FakeMailer()
    app = FastAPI()
    receiver = HelloAssoReceiver(client=client, app=app, form_slug="club")
    from database import Database
    from helloasso.mails import MemberMails

    db = Database(str(tmp_path / "test.db"))
    db.migrate()
    receiver.enable_member_mail(mailer, contact="contact@example.org", sender="sambo-admin@silvaplana.cloud", journal=MemberMails(db))
    http = TestClient(app)

    assert http.get("/helloasso/mail-settings").json() == {"enabled": True, "sender": "sambo-admin@silvaplana.cloud", "contact": "contact@example.org"}
    sent = http.post("/helloasso/members/42/mail", json={"subject": "Certificat", "message": "Bonjour,\nil manque <le> certificat.\n\nMerci"})
    assert sent.json() == {"sent": True, "to": "alice@example.org", "cc": "contact@example.org"}
    mail = mailer.sent[0]
    assert (mail["to"], mail["name"], mail["subject"]) == ("alice@example.org", "Léo Martin", "Certificat")
    assert (mail["cc"], mail["reply_to"], mail["sender"]) == ("contact@example.org", "contact@example.org", "sambo-admin@silvaplana.cloud")
    assert mail["html"] == "<p>Bonjour,<br>il manque &lt;le&gt; certificat.</p><p>Merci</p>"

    assert http.post("/helloasso/members/42/mail", json={"subject": " ", "message": "x"}).status_code == 400
    assert http.post("/helloasso/members/42/mail", json={"subject": "a\nBcc: x@y.z", "message": "x"}).status_code == 400
    assert http.post("/helloasso/members/999/mail", json={"subject": "a", "message": "x"}).status_code == 404
    mailer.enabled = False
    assert http.post("/helloasso/members/42/mail", json={"subject": "a", "message": "x"}).status_code == 503
    assert len(mailer.sent) == 1

    # Trace en base : le mail envoye, puis un echec d'envoi.
    journal = http.get("/helloasso/members/42/mails").json()
    assert [(m["subject"], m["to"], m["cc"], m["sender"], m["sent"]) for m in journal] == [
        ("Certificat", "alice@example.org", "contact@example.org", "sambo-admin@silvaplana.cloud", True)
    ]
    assert journal[0]["body"].startswith("Bonjour,") and (journal[0]["firstName"], journal[0]["lastName"]) == ("Léo", "Martin")
    from mailer import MailError

    mailer.enabled = True

    def refuse(*args, **options):
        raise MailError("Envoi du mail impossible : quota dépassé")

    mailer.send = refuse
    assert http.post("/helloasso/members/42/mail", json={"subject": "Relance", "message": "x"}).status_code == 502
    everything = http.get("/helloasso/mails").json()
    assert [(m["subject"], m["sent"], m["error"]) for m in everything] == [
        ("Relance", False, "Envoi du mail impossible : quota dépassé"),
        ("Certificat", True, None),
    ]
    assert http.get("/helloasso/members/7/mails").json() == []
    # Pastille du bouton Mail : seuls les mails vraiment partis comptent.
    assert http.get("/helloasso/mail-counts").json() == {"42": 1}


def test_mailer_headers(monkeypatch):
    """Copie, adresse de reponse et expediteur propres a un mail."""
    from mailer import Mailer

    sent = []

    class FakeSmtp:
        def __init__(self, *args, **kwargs): ...
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def starttls(self, context=None): ...
        def login(self, user, password): ...
        def send_message(self, message): sent.append(message)

    monkeypatch.setattr("mailer.mailer.smtplib.SMTP", FakeSmtp)
    mailer = Mailer("smtp.example.org", 587, "user", "secret", "club@example.org", "Le club", reply_to="defaut@example.org")
    mailer.send("a@example.org", "A", "Objet", "<p>x</p>", "x", cc="c@example.org", reply_to="r@example.org", sender="sambo-admin@silvaplana.cloud")
    mailer.send("a@example.org", "A", "Objet", "<p>x</p>", "x")
    assert (sent[0]["Cc"], sent[0]["Reply-To"]) == ("c@example.org", "r@example.org") and "sambo-admin@silvaplana.cloud" in sent[0]["From"]
    assert (sent[1]["Cc"], sent[1]["Reply-To"]) == (None, "defaut@example.org") and "club@example.org" in sent[1]["From"]


@pytest.mark.parametrize(
    "value, expected",
    [
        ("05/11/0017", "05/11/2017"),  # annee saisie "17" : un enfant, pas l'an 17
        ("05/11/0026", "05/11/2026"),
        ("05/11/0027", "05/11/1927"),  # dans le futur : siecle precedent
        ("05/11/0085", "05/11/1985"),
        ("05/11/2017", "05/11/2017"),
        ("Oui", "Oui"),
        ("", ""),
        (None, None),
    ],
)
def test_fix_short_year(value, expected):
    from helloasso.helloasso import fix_short_year

    assert fix_short_year(value, TODAY) == expected


def test_members_get_a_usable_birth_date(monkeypatch):
    """La date corrigee est celle transmise a la FFST et utilisee pour l'age."""
    from helloasso import HelloAsso

    order = {
        "id": 1,
        "payer": {},
        "items": [
            {
                "id": 5,
                "type": "Membership",
                "state": "Processed",
                "amount": 30000,
                "user": {"firstName": "Nils", "lastName": "Test"},
                "customFields": [{"name": "date de naissance", "type": "Date", "answer": "05/11/0017"}, {"name": "Ville", "answer": "La Ciotat"}],
            }
        ],
    }
    client = HelloAsso(client_id="x", client_secret="y", organization_slug="club")
    monkeypatch.setattr(client, "get_form_orders", lambda form_slug, form_type="Membership": [order])

    member = client.get_members("club")[0]
    assert member["customFields"] == {"date de naissance": "05/11/2017", "Ville": "La Ciotat"}
    assert client.get_member_detail("club", 5)["fields"][0]["answer"] == "05/11/2017"
    assert members_summary([member], [], TODAY)["minors"] == 1


@pytest.mark.parametrize(
    "value, expected",
    [
        ("06 12 34 56 78", "+33612345678"),
        ("0612345678", "+33612345678"),
        ("06.12.34.56.78", "+33612345678"),
        ("+33 6 12 34 56 78", "+33612345678"),
        ("0033612345678", "+33612345678"),
        ("612345678", "+33612345678"),
        ("+41 79 123 45 67", "+41791234567"),
        ("", None),
        ("non", None),
        (None, None),
    ],
)
def test_normalize_phone(value, expected):
    from helloasso.mails import normalize_phone

    assert normalize_phone(value) == expected


def test_member_sms_journal(monkeypatch, tmp_path):
    """SMS prepare : numero relu chez HelloAsso, trace en base, compteur."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from database import Database
    from helloasso import HelloAsso, HelloAssoReceiver
    from helloasso.mails import MemberSms

    def item(item_id, phone):
        fields = [{"name": "Numéro de téléphone", "type": "Phone", "answer": phone}] if phone else []
        return {"id": item_id, "type": "Membership", "state": "Processed", "amount": 0, "user": {"firstName": "Léo", "lastName": "Martin"}, "customFields": fields}

    order = {"id": 7, "payer": {}, "payments": [], "items": [item(42, "06 12 34 56 78"), item(43, None)]}
    client = HelloAsso(client_id="x", client_secret="y", organization_slug="club")
    monkeypatch.setattr(client, "get_form_orders", lambda form_slug, form_type="Membership": [order])
    db = Database(str(tmp_path / "test.db"))
    db.migrate()
    app = FastAPI()
    receiver = HelloAssoReceiver(client=client, app=app, form_slug="club")

    class NoMailer:
        enabled = False
        sender = ""

    receiver.enable_member_mail(NoMailer(), contact=None, sender=None, sms_journal=MemberSms(db))
    http = TestClient(app)

    saved = http.post("/helloasso/members/42/sms", json={"message": " Cours annulé ce soir. "}).json()
    assert (saved["phone"], saved["body"], saved["firstName"]) == ("+33612345678", "Cours annulé ce soir.", "Léo")
    assert http.post("/helloasso/members/43/sms", json={"message": "x"}).status_code == 400  # pas de numero
    assert http.post("/helloasso/members/42/sms", json={"message": "  "}).status_code == 400
    assert http.post("/helloasso/members/99/sms", json={"message": "x"}).status_code == 404
    assert [s["body"] for s in http.get("/helloasso/members/42/sms").json()] == ["Cours annulé ce soir."]
    assert http.get("/helloasso/sms-counts").json() == {"42": 1}
    assert len(http.get("/helloasso/sms").json()) == 1
