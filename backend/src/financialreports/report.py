"""Calcul du compte d'exploitation d'une saison, a partir de l'historique des
comptes (courant + Livret Bleu, voir BankStatements.get_ledger).

Calcul exact, au centime, sans IA : recettes et depenses nettes par
categorie (categories de Comptes, voir bankstatements/categories.py, ou
celles choisies par l'IA pour les operations "Autres"), detail par mois, et
la verification demandee par le tresorier : solde au debut + recettes -
depenses = solde reel a la fin. Les virements entre les comptes du club ne
sont ni des recettes ni des depenses.

Saison en cours (ou pas encore couverte par les releves) : arretee au
dernier jour connu des comptes.
"""

from __future__ import annotations

from bankstatements.categories import OTHER


def _cents(euros: float) -> int:
    return round(euros * 100)


def _euros(cents: int | None) -> float | None:
    return None if cents is None else cents / 100


def _months(start: str, end: str) -> list[str]:
    """["2025-07", "2025-08", ...] de la date start a la date end comprises."""
    year, month = int(start[:4]), int(start[5:7])
    last = (int(end[:4]), int(end[5:7]))
    months = []
    while (year, month) <= last:
        months.append(f"{year:04d}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months


def compute_report(ledger: dict, start: str, end: str, classifications: dict[int, str] | None = None) -> dict:
    """Compte d'exploitation du start au end (dates AAAA-MM-JJ comprises).

    classifications : categorie choisie (par l'IA) pour certaines operations,
    par identifiant d'operation ; les autres gardent celle de Comptes.

    Retour (montants en euros) : {"start", "end", "cutoff", "opening",
    "closing", "income": [{"category", "amount"}], "expense": [...],
    "totalIncome", "totalExpense", "result", "net": {categorie: montant},
    "verification": {"expected", "actual", "gap", "ok"}, "categories",
    "months": [{"month", "opening", "closing", "amounts"}], "operations",
    "issues"}. Recettes et depenses nettes : une categorie est une recette si
    son total sur la periode est positif (ex : licences remboursees par la
    federation deduites des licences payees).
    """
    classifications = classifications or {}
    rows = list(reversed(ledger["rows"]))  # la plus ancienne en premier
    as_of = max((a["asOf"] for a in ledger["accounts"] if a.get("asOf")), default=None)
    cutoff = min(end, as_of) if as_of else end

    period = [r for r in rows if start <= r["date"] <= cutoff]
    operations = [r for r in period if not r["transfer"]]

    def balance_before(day: str) -> int | None:
        """Solde total reel (courant + Bleu) a la fin de la veille de day."""
        known = [r for r in rows if r["date"] < day and r["total"] is not None]
        return _cents(known[-1]["total"]) if known else None

    def balance_at(day: str) -> int | None:
        """Solde total reel a la fin de la journee day."""
        known = [r for r in rows if r["date"] <= day and r["total"] is not None]
        return _cents(known[-1]["total"]) if known else None

    opening = balance_before(start)
    if opening is None:
        # Historique qui commence pendant la saison : solde de la 1re ligne
        # connue moins les operations qui y menent.
        first = next((i for i, r in enumerate(period) if r["total"] is not None), None)
        if first is not None:
            opening = _cents(period[first]["total"]) - sum(
                _cents(r["amount"]) for r in period[: first + 1] if not r["transfer"]
            )
    closing = balance_at(cutoff)
    if closing is None and not period:
        closing = opening

    net: dict[str, int] = {}
    by_month: dict[str, dict[str, int]] = {}
    detailed = []
    for r in operations:
        category = classifications.get(r["id"], r["category"])
        amount = _cents(r["amount"])
        net[category] = net.get(category, 0) + amount
        month = by_month.setdefault(r["date"][:7], {})
        month[category] = month.get(category, 0) + amount
        detailed.append(
            {
                "id": r["id"],
                "date": r["date"],
                "label": r["label"],
                "details": r["details"],
                "amount": r["amount"],
                "category": category,
                "bankCategory": r["category"],
                "provisional": r.get("provisional", False),
            }
        )

    income = sorted(((c, v) for c, v in net.items() if v > 0), key=lambda cv: -cv[1])
    expense = sorted(((c, -v) for c, v in net.items() if v < 0), key=lambda cv: -cv[1])
    total_income = sum(v for _, v in income)
    total_expense = sum(v for _, v in expense)
    expected = None if opening is None else opening + total_income - total_expense
    gap = None if expected is None or closing is None else closing - expected

    months = []
    running = opening
    for month in _months(start, cutoff):
        amounts = by_month.get(month, {})
        month_opening = running
        running = None if running is None else running + sum(amounts.values())
        months.append(
            {
                "month": month,
                "opening": _euros(month_opening),
                "closing": _euros(running),
                "amounts": {c: _euros(v) for c, v in amounts.items()},
            }
        )

    return {
        "start": start,
        "end": end,
        "cutoff": cutoff,
        "opening": _euros(opening),
        "closing": _euros(closing),
        "income": [{"category": c, "amount": _euros(v)} for c, v in income],
        "expense": [{"category": c, "amount": _euros(v)} for c, v in expense],
        "totalIncome": _euros(total_income),
        "totalExpense": _euros(total_expense),
        "result": _euros(total_income - total_expense),
        "net": {c: _euros(v) for c, v in net.items()},
        "verification": {
            "expected": _euros(expected),
            "actual": _euros(closing),
            "gap": _euros(gap),
            "ok": gap == 0,
        },
        # Colonnes du detail par mois : recettes puis depenses.
        "categories": [c for c, _ in income] + [c for c, _ in expense],
        "months": months,
        "operations": detailed,
        "issues": ledger.get("issues", []),
    }


def unclassified(report: dict) -> list[dict]:
    """Operations de la categorie "Autres" (a classer par l'IA)."""
    return [op for op in report["operations"] if op["bankCategory"] == OTHER]
