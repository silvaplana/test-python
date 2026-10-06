"""Donnees preparees par l'appli pour la formule d'un previsionnel (le
dictionnaire "donnees" passe a prevoir(donnees, p), voir sandbox.py).

L'IA ne lit pas les releves bruts : elle recoit ces chiffres (et leur
description dans ses consignes, voir ai.py), puis ecrit une formule qui les
utilise. Noms de champs en francais : ils sont lus par l'IA.

Solde = compte courant + Livret Bleu (comme dans Saisons) ; les virements
entre les comptes du club ne sont ni des recettes ni des depenses.
"""

from __future__ import annotations

from datetime import date, timedelta

from bankstatements.categories import INTERNAL_TRANSFER

# Une valeur prevue par semaine.
STEP_DAYS = 7


def _iso(day: date) -> str:
    return day.isoformat()


def history(ledger: dict) -> list[dict]:
    """Operations la plus ancienne en premier, solde total connu."""
    return [r for r in reversed(ledger["rows"]) if r["total"] is not None]


def last_known_day(ledger: dict) -> str | None:
    """Dernier jour connu des comptes (fin du dernier releve ou derniere
    operation lue a la banque)."""
    return max((a["asOf"] for a in ledger["accounts"] if a.get("asOf")), default=None)


def balance_at(rows: list[dict], day: str) -> float | None:
    """Solde total en fin de journee `day`."""
    value = None
    for row in rows:
        if row["date"] > day:
            break
        value = row["total"]
    return value


def realized(rows: list[dict], start: str, end: str) -> list[dict]:
    """Solde total jour par jour d'operation, du start au end compris
    (premier point : solde en fin de journee start - 1)."""
    before = balance_at(rows, _iso(date.fromisoformat(start) - timedelta(days=1)))
    points = [{"date": start, "solde": before}] if before is not None else []
    for row in rows:
        if start <= row["date"] <= end:
            if points and points[-1]["date"] == row["date"]:
                points[-1]["solde"] = row["total"]
            else:
                points.append({"date": row["date"], "solde": row["total"]})
    return points


def weeks(start: str, end: str) -> list[dict]:
    """Dates des valeurs prevues : une par semaine apres start, la derniere
    le end. mois_commences : mois ("AAAA-MM") dont le 1er jour tombe dans la
    semaine (apres la valeur precedente, jusqu'a celle-ci comprise)."""
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    result = []
    previous = first
    day = first + timedelta(days=STEP_DAYS)
    while previous < last:
        day = min(day, last)
        months = []
        cursor = date(previous.year, previous.month, 1)
        while cursor <= day:
            if cursor > previous:
                months.append(cursor.strftime("%Y-%m"))
            cursor = date(cursor.year + (cursor.month == 12), cursor.month % 12 + 1, 1)
        result.append({"date": _iso(day), "mois_commences": months})
        previous = day
        day = day + timedelta(days=STEP_DAYS)
    return result


def _net_by_category(rows: list[dict], start: str, end: str) -> dict[str, float]:
    """Montant net par categorie du start au end compris (virements internes
    exclus)."""
    totals: dict[str, int] = {}
    for row in rows:
        if start <= row["date"] <= end and not row["transfer"] and row["category"] != INTERNAL_TRANSFER:
            totals[row["category"]] = totals.get(row["category"], 0) + round(row["amount"] * 100)
    return {category: cents / 100 for category, cents in sorted(totals.items())}


def build(ledger: dict, season: dict, start: str, members: dict | None) -> dict:
    """Donnees de la formule pour la saison `season` (fiche de Seasons), a
    partir de la date de depart `start` (AAAA-MM-JJ).

    members : chiffres des adherents HelloAsso (helloasso.summary.members_summary),
    ou None (indisponibles, ou date de depart passee : ils ne decrivent que
    la campagne d'aujourd'hui)."""
    rows = history(ledger)
    opening = balance_at(rows, start)
    if opening is None:
        raise ValueError(f"Solde inconnu au {start} : importez les relevés de cette période dans Comptes")
    start_day = date.fromisoformat(start)
    year_before = _iso(start_day - timedelta(days=365))
    month_first = _iso(start_day.replace(day=1))

    # 12 derniers mois avant la date de depart : par mois et en moyenne.
    months = []
    cursor = date.fromisoformat(year_before).replace(day=1)
    while cursor.strftime("%Y-%m") < start[:7]:
        nxt = date(cursor.year + (cursor.month == 12), cursor.month % 12 + 1, 1)
        months.append(
            {
                "mois": cursor.strftime("%Y-%m"),
                "parCategorie": _net_by_category(rows, _iso(cursor), _iso(nxt - timedelta(days=1))),
            }
        )
        cursor = nxt
    averages: dict[str, float] = {}
    for month in months:
        for category, value in month["parCategorie"].items():
            averages[category] = averages.get(category, 0) + value
    count = len(months) or 1

    data = {
        "saison": season["name"],
        "debutSaison": season["startDate"],
        "finSaison": season["endDate"],
        "dateDepart": start,
        "soldeDepart": opening,
        "semaines": weeks(start, season["endDate"]),
        "moisEnCours": {"mois": start[:7], "dejaPasseParCategorie": _net_by_category(rows, month_first, start)},
        "moyennesMensuelles": {c: round(v / count, 2) for c, v in sorted(averages.items())},
        "douzeDerniersMois": months,
        "soldeDebutSaison": balance_at(rows, _iso(date.fromisoformat(season["startDate"]) - timedelta(days=1))),
        "adherents": None,
    }
    if members is not None:
        data["adherents"] = {
            "nombre": members.get("members"),
            "majeurs": members.get("adults"),
            "mineurs": members.get("minors"),
            "prixMoyenAdhesion": members.get("averagePrice"),
            "totalAdhesions": members.get("totalPrice"),
            # Echeances des paiements en plusieurs fois pas encore encaissees.
            "echeancesAVenir": {r["month"]: r["amount"] for r in members.get("remaining", []) if r.get("month")},
            "impayes": members.get("unpaidTotal"),
        }
    return data
