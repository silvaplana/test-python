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

# Ou en est l'argent d'un paiement encaisse (cashOutState) :
# - verse sur le compte courant du club ;
CASHED_OUT_STATES = {"CashedOut"}
# - versement vers le compte courant lance, pas encore arrive (cashOutDate :
#   date de la demande) ;
CASH_OUT_PENDING_STATES = {"WaitingForCashOutConfirmation", "TransferInProgress"}
# - tout autre etat (Transfered, MoneyIn...) : chez HelloAsso, versement pas
#   encore lance, donc sans date connue.
# Paiements par carte ou prelevement : les seuls qui passent par HelloAsso
# (un cheque ou des especes arrivent au club directement).
ONLINE_PAYMENT_MEANS = {"Card", "Sepa", None}

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


def members_summary(members: list[dict], member_payments: list[dict], today: date, bank: dict | None = None) -> dict:
    """members : HelloAsso.get_members ; member_payments :
    HelloAsso.get_member_payments ; bank : virements HelloAsso vus a la banque
    (bank_cash_outs), pour savoir ce qui est reellement arrive sur le compte.

    Retour : {"members", "adults", "minors", "unknownAge", "averagePrice",
    "totalPrice", "freeMembers", "remaining": [{"month": "AAAA-MM", "amount",
    "payments"}], "remainingTotal", "unpaidTotal", "cash": voir
    cash_summary} (montants en euros).
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
        # Detail des encaissements : compte courant, HelloAsso, a venir.
        "cash": cash_summary(member_payments, bank),
    }


def _by_date(rows: dict[str, list[int]]) -> list[dict]:
    """{"AAAA-MM-JJ": [centimes]} -> lignes triees par date."""
    return [
        {"date": day, "amount": sum(amounts) / 100, "payments": len(amounts)}
        for day, amounts in sorted(rows.items())
    ]


# Virement HelloAsso recu a la banque : son libelle se termine par la date du
# versement ("VIR HELLOASSOPAY ... HELLOASSO 3711911 07-10-2026").
_BANK_CASH_OUT = re.compile(r"(\d{2})-(\d{2})-(\d{4})\s*$")


def bank_cash_outs(ledger: dict) -> dict:
    """Virements HelloAsso arrives sur les comptes (ledger :
    BankStatements.get_ledger), reperes par leur libelle.

    Retour : {"received": {date du versement "AAAA-MM-JJ": {"date": jour
    d'arrivee a la banque, "amount": montant recu}}, "asOf": date de la
    derniere operation connue des comptes, ou None}.
    """
    rows = ledger.get("rows", [])
    received: dict[str, dict] = {}
    for row in rows:
        label = str(row.get("label") or "")
        match = _BANK_CASH_OUT.search(label)
        if "HELLOASSO" not in label.upper() or not match or (row.get("amount") or 0) <= 0:
            continue
        day, month, year = match.groups()
        entry = received.setdefault(f"{year}-{month}-{day}", {"date": row["date"], "amount": 0})
        entry["date"] = min(entry["date"], row["date"])
        entry["amount"] = round((entry["amount"] + row["amount"]) * 100) / 100
    return {"received": received, "asOf": max((row["date"] for row in rows), default=None)}


def cash_summary(member_payments: list[dict], bank: dict | None = None) -> dict:
    """Ou en est l'argent des adhesions (member_payments :
    HelloAsso.get_member_payments), du compte courant du club aux echeances
    a venir.

    bank : virements HelloAsso vus a la banque (bank_cash_outs). C'est la
    banque qui dit si un versement est arrive : HelloAsso garde l'etat "en
    attente de confirmation" bien apres l'arrivee de l'argent. Sans bank
    (comptes indisponibles), on se fie a l'etat declare par HelloAsso.

    Retour (montants en euros, dates "AAAA-MM-JJ") : {
      "onAccount": arrive sur le compte courant ; lignes par versement, "date"
        = jour d'arrivee a la banque, "requested" = date du versement chez
        HelloAsso ;
      "inTransit": versement lance par HelloAsso ("date"), pas encore vu sur
        le compte ;
      "held": encaisse par HelloAsso, versement pas encore lance ;
      "offline": paye hors HelloAsso (cheque, especes...) ;
      "upcoming": echeances a venir, par jour de prelevement ;
      "toReceive": ce qui doit encore arriver sur le compte courant
        (inTransit + held + upcoming) ;
      "bankAsOf": date de la derniere operation connue des comptes (None si
        les comptes n'ont pas ete consultes) }
    onAccount, inTransit, upcoming : {"total", "payments", "rows": [{"date",
    "amount", "payments"}]} ; held, offline : {"total", "payments"}.
    """
    received = bank["received"] if bank else None
    on_account: dict[str, list[int]] = {}
    in_transit: dict[str, list[int]] = {}
    upcoming: dict[str, list[int]] = {}
    held: list[int] = []
    offline: list[int] = []
    for member in member_payments:
        for payment in member["payments"]:
            cents = round(payment["amount"] * 100)
            state = payment["state"]
            if state in FAILED_PAYMENT_STATES or state in REFUNDED_PAYMENT_STATES:
                continue
            if state not in PAID_PAYMENT_STATES:
                upcoming.setdefault((payment["date"] or "")[:10], []).append(cents)
                continue
            cash_out = payment.get("cashOutState")
            if cash_out in REFUNDED_PAYMENT_STATES:
                continue
            day = (payment.get("cashOutDate") or "")[:10]
            launched = cash_out in CASHED_OUT_STATES or cash_out in CASH_OUT_PENDING_STATES
            if payment.get("paymentMeans") not in ONLINE_PAYMENT_MEANS:
                offline.append(cents)
            elif not launched:
                held.append(cents)
            elif (day in received) if received is not None else (cash_out in CASHED_OUT_STATES):
                on_account.setdefault(day, []).append(cents)
            else:
                in_transit.setdefault(day, []).append(cents)

    def dated(rows: dict[str, list[int]]) -> dict:
        return {
            "total": sum(sum(amounts) for amounts in rows.values()) / 100,
            "payments": sum(len(amounts) for amounts in rows.values()),
            "rows": _by_date(rows),
        }

    result = {
        "onAccount": dated(on_account),
        "inTransit": dated(in_transit),
        "held": {"total": sum(held) / 100, "payments": len(held)},
        "offline": {"total": sum(offline) / 100, "payments": len(offline)},
        "upcoming": dated(upcoming),
        "bankAsOf": bank["asOf"] if bank else None,
    }
    if received is not None:
        # Jour d'arrivee a la banque, a la place de la date du versement.
        for row in result["onAccount"]["rows"]:
            row["requested"], row["date"] = row["date"], received[row["date"]]["date"]
        result["onAccount"]["rows"].sort(key=lambda row: row["date"])
    result["toReceive"] = round(
        (result["inTransit"]["total"] + result["held"]["total"] + result["upcoming"]["total"]) * 100
    ) / 100
    return result


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
