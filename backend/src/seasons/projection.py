"""Projection des salaires et cotisations jusqu'a la fin de la saison
(panneau "Statistiques des adhérents de la saison"), a partir des operations
des comptes : sans IA, donc reproductible et explicable ligne a ligne.

Pour chaque categorie (salaires, URSSAF, mutuelle) :
- montant mensuel retenu : celui des 3 derniers mois payes s'ils sont
  identiques (depense reguliere) ; sinon la moyenne des 6 derniers mois
  complets, sans remonter avant le premier paiement (depense irreguliere :
  mois sautes puis doubles) ;
- mois restants : du mois en cours s'il n'est pas encore paye (sinon du mois
  suivant) jusqu'au mois de fin de saison compris.
"""

from __future__ import annotations

from datetime import date

# Categories des operations (voir bankstatements/categories.py) projetees.
PAYROLL_CATEGORIES = ("Salaires", "URSSAF", "Mutuelle")
REGULAR_MONTHS = 3
AVERAGE_MONTHS = 6


def _add_months(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def _key(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def payroll_projection(rows: list[dict], season_end: date, today: date) -> dict:
    """rows : operations des comptes (BankStatements.get_ledger()["rows"]).

    Retour (montants en euros, depenses en positif) : {"seasonEnd", "total",
    "lines": [{"category", "monthly", "basis": "regular" ou "average",
    "basisMonths": [{"month": "AAAA-MM", "amount"}] (mois qui ont servi au
    calcul), "months" (nombre de mois restants), "firstMonth", "lastMonth"
    ("AAAA-MM", None si plus rien a payer), "paidThisMonth", "amount"}]}.
    Une categorie sans aucune operation n'apparait pas.
    """
    current = (today.year, today.month)
    last = (season_end.year, season_end.month)
    lines = []
    for category in PAYROLL_CATEGORIES:
        by_month: dict[str, float] = {}
        for row in rows:
            if row.get("category") == category:
                month = row["date"][:7]
                by_month[month] = by_month.get(month, 0) - row["amount"]
        if not by_month:
            continue
        cents = {month: round(amount * 100) for month, amount in by_month.items()}
        paid_months = sorted(month for month in cents if month <= _key(*current))
        recent = paid_months[-REGULAR_MONTHS:]
        if len(recent) == REGULAR_MONTHS and len({cents[month] for month in recent}) == 1:
            basis, used = "regular", recent
            monthly_cents = cents[recent[-1]]
        else:
            # 6 derniers mois complets (le mois en cours n'est pas fini), sans
            # remonter avant le premier paiement connu : un historique de 2
            # mois se moyenne sur 2 mois, pas sur 6.
            used = [_key(*_add_months(*current, -offset)) for offset in range(AVERAGE_MONTHS, 0, -1)]
            used = [month for month in used if month >= paid_months[0]] if paid_months else []
            if not used:  # seul le mois en cours est paye
                used = paid_months[-1:] or sorted(cents)[-1:]
            basis = "average"
            monthly_cents = round(sum(cents.get(month, 0) for month in used) / len(used))
        paid_this_month = _key(*current) in cents
        first = _add_months(*current, 1) if paid_this_month else current
        months = max(0, (last[0] * 12 + last[1]) - (first[0] * 12 + first[1]) + 1)
        lines.append({
            "category": category,
            "monthly": monthly_cents / 100,
            "basis": basis,
            "basisMonths": [{"month": month, "amount": cents.get(month, 0) / 100} for month in used],
            "months": months,
            "firstMonth": _key(*first) if months else None,
            "lastMonth": _key(*last) if months else None,
            "paidThisMonth": paid_this_month,
            "amount": monthly_cents * months / 100,
        })
    return {
        "seasonEnd": season_end.isoformat(),
        "total": round(sum(line["amount"] * 100 for line in lines)) / 100,
        "lines": lines,
    }
