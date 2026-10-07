"""Chiffres des adherents de la campagne en cours (panneau "Chiffres des
adhérents" du menu de l'onglet HelloAsso > Adherents) : majeurs et mineurs,
prix moyen de la licence, et ce qui reste a encaisser mois par mois
(echeances a venir des paiements en plusieurs fois).
"""

from __future__ import annotations

import re
from datetime import date

# Etats d'un paiement HelloAsso (PaymentState).
# Refuse ou en echec definitif : un impaye (voir GET /helloasso/unpaid). A
# distinguer des etats "a venir" (Pending, Waiting*, Init) : une adhesion
# payee en plusieurs fois a des echeances dans cet etat le temps qu'elles
# arrivent a echeance, ce n'est pas un impaye.
FAILED_PAYMENT_STATES = {
    "Refused",
    "Error",
    "Canceled",
    "Abandoned",
    "Deleted",
    "Inconsistent",
    "NoDonation",
}
# Encaisse.
PAID_PAYMENT_STATES = {"Authorized", "Registered", "Corrected"}
# Rembourse ou conteste : ni encaisse, ni a venir.
REFUNDED_PAYMENT_STATES = {"Refunded", "Refunding", "Contested"}
# Tout autre etat (Pending, Waiting...) : echeance a venir.

# Etats d'une adhesion (item) resiliee : elle reste dans HelloAsso, mais ne
# compte plus parmi les adherents.
CANCELED_ITEM_STATES = {"Canceled", "Refunded", "Refunding", "Abandoned"}

ADULT_AGE = 18
_BIRTH_DATE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")


def _age(birth: str | None, today: date) -> int | None:
    """Age en annees revolues, depuis la date de naissance du formulaire
    (JJ/MM/AAAA) ; None si elle est absente ou mal formee."""
    match = _BIRTH_DATE.match((birth or "").strip())
    if not match:
        return None
    day, month, year = (int(part) for part in match.groups())
    try:
        born = date(year, month, day)
    except ValueError:
        return None
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def members_summary(members: list[dict], member_payments: list[dict], today: date) -> dict:
    """members : HelloAsso.get_members ; member_payments :
    HelloAsso.get_member_payments.

    Retour : {"members", "adults", "minors", "unknownAge", "averagePrice",
    "totalPrice", "freeMembers", "remaining": [{"month": "AAAA-MM", "amount",
    "payments"}], "remainingTotal", "unpaidTotal"} (montants en euros).
    """
    members = [m for m in members if m.get("state") not in CANCELED_ITEM_STATES]
    ages = [_age(m.get("customFields", {}).get("date de naissance"), today) for m in members]
    total_cents = sum(round(m.get("amount", 0) * 100) for m in members)

    by_month: dict[str, list[int]] = {}
    unpaid_cents = 0
    for member in member_payments:
        for payment in member["payments"]:
            cents = round(payment["amount"] * 100)
            state = payment["state"]
            if state in FAILED_PAYMENT_STATES:
                unpaid_cents += cents
            elif state not in PAID_PAYMENT_STATES and state not in REFUNDED_PAYMENT_STATES:
                # Mois de l'echeance : debut de la date ISO "AAAA-MM-JJT...".
                by_month.setdefault((payment["date"] or "")[:7], []).append(cents)
    remaining = [
        {"month": month, "amount": sum(amounts) / 100, "payments": len(amounts)}
        for month, amounts in sorted(by_month.items())
    ]
    return {
        "members": len(members),
        "adults": sum(1 for age in ages if age is not None and age >= ADULT_AGE),
        "minors": sum(1 for age in ages if age is not None and age < ADULT_AGE),
        "unknownAge": sum(1 for age in ages if age is None),
        "averagePrice": round(total_cents / len(members)) / 100 if members else None,
        "totalPrice": total_cents / 100,
        "freeMembers": sum(1 for m in members if not m.get("amount")),
        "remaining": remaining,
        "remainingTotal": sum(r["amount"] * 100 for r in remaining) / 100,
        "unpaidTotal": unpaid_cents / 100,
    }


def cancellation_preview(order: dict) -> dict:
    """Ce que resilier une commande HelloAsso (HelloAsso.cancel_order)
    changerait, a afficher avant de confirmer : ses adherents (tous resilies
    ensemble), ce qui a deja ete encaisse (non rembourse par la resiliation)
    et les echeances a venir (annulees).

    Retour : {"orderId", "date", "payer", "members": [{"firstName",
    "lastName", "amount", "promoCode", "state"}], "paid", "scheduled",
    "scheduledCount", "unpaid", "canceled"} (montants en euros).
    """
    payer = order.get("payer", {})
    members = []
    for item in order.get("items", []):
        if item.get("type") != "Membership":
            continue
        user = item.get("user", {})
        members.append(
            {
                "firstName": user.get("firstName") or payer.get("firstName"),
                "lastName": user.get("lastName") or payer.get("lastName"),
                "amount": item.get("amount", 0) / 100,
                "promoCode": (item.get("discount") or {}).get("code"),
                "state": item.get("state"),
            }
        )
    paid = scheduled = unpaid = scheduled_count = 0
    for payment in order.get("payments", []):
        cents, state = payment.get("amount", 0), payment.get("state")
        if state in PAID_PAYMENT_STATES:
            paid += cents
        elif state in FAILED_PAYMENT_STATES:
            unpaid += cents
        elif state not in REFUNDED_PAYMENT_STATES:
            scheduled += cents
            scheduled_count += 1
    return {
        "orderId": order.get("id"),
        "date": order.get("date"),
        "payer": " ".join(part for part in (payer.get("firstName"), payer.get("lastName")) if part),
        "members": members,
        "paid": paid / 100,
        "scheduled": scheduled / 100,
        "scheduledCount": scheduled_count,
        "unpaid": unpaid / 100,
        # Deja resiliee : plus rien a faire.
        "canceled": bool(members) and all(m["state"] in CANCELED_ITEM_STATES for m in members),
    }
