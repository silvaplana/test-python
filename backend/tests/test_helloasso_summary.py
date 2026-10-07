"""Chiffres des adherents (helloasso/summary.py)."""

from datetime import date

import pytest

from helloasso.summary import members_summary

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
