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
