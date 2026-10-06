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
