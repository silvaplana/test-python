"""Saisons du club (onglet Finances > Saisons) : l'unite de temps d'un
club, du 1er juillet au 30 juin (ex : "2026-2027").

Une saison est une fiche en base (table seasons, voir database.py) creee,
modifiee et supprimee a la main. Ce qu'elle contient :
- licencies : repris de FFST pour la saison en cours (voir
  set_current_licences), saisis a la main pour les saisons passees ;
- solde de fin de saison, compte courant + Livret Bleu cumules : calcule
  depuis l'historique des comptes (bankstatements) tant qu'il n'est pas
  saisi a la main ; pour la saison en cours, solde a ce jour ;
- cout de l'IA : cout cumule de l'API sur la saison, saisi a la main.

Supprimer une saison n'efface que sa fiche : les operations bancaires de la
periode restent dans l'historique des comptes.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from database import Database

PARIS = ZoneInfo("Europe/Paris")


def today() -> date:
    return datetime.now(PARIS).date()


class SeasonError(ValueError):
    """Donnees de saison invalides (message affichable tel quel)."""


class SeasonNotFoundError(LookupError):
    pass


def _cents(euros: float | None) -> int | None:
    return None if euros is None else round(euros * 100)


def _euros(cents: int | None) -> float | None:
    return None if cents is None else cents / 100


def _fr(iso: str) -> str:
    year, month, day = iso.split("-")
    return f"{day}/{month}/{year}"


class Seasons:
    def __init__(self, db: Database, ledger: Callable[[], dict], today: Callable[[], date] = today) -> None:
        """ledger : historique de tous les comptes ensemble (voir
        BankStatements.get_ledger), pour les soldes calcules et la courbe."""
        self.db = db
        self.ledger = ledger
        self.today = today

    # ----- lecture -----

    def get_seasons(self) -> dict:
        """Toutes les saisons (la plus ancienne en premier) et la courbe du
        solde total (un point par jour d'operation, pour le graphique
        "Compte detaille").

        Retour : {"seasons": [{"id", "name", "startDate", "endDate",
        "current", "licences", "aiCost", "balance": {"total", "asOf", "auto",
        "computed"}}], "series": [{"date", "total"}], "today"} (montants en euros).
        """
        with self.db.connect() as connection:
            rows = connection.execute("SELECT * FROM seasons ORDER BY start_date").fetchall()
        ledger = self.ledger()
        # Lignes de l'historique, la plus ancienne en premier, solde total connu.
        history = [r for r in reversed(ledger["rows"]) if r["total"] is not None]
        today_iso = self.today().isoformat()

        def total_at(day: str) -> tuple[float | None, str | None]:
            """Solde total en fin de journee `day` : celui de la derniere
            operation ce jour-la ou avant, et sa date."""
            last = None
            for row in history:
                if row["date"] > day:
                    break
                last = row
            if last is None:
                return None, None
            return last["total"], last["date"]

        seasons = []
        for row in rows:
            current = row["start_date"] <= today_iso <= row["end_date"]
            # Saison a venir : pas encore de solde.
            computed, as_of = (None, None) if row["start_date"] > today_iso else total_at(min(row["end_date"], today_iso))
            manual = row["end_balance"] is not None
            seasons.append(
                {
                    "id": row["id"],
                    "name": row["name"],
                    "startDate": row["start_date"],
                    "endDate": row["end_date"],
                    "current": current,
                    "licences": row["licences"],
                    "aiCost": _euros(row["ai_cost"]),
                    "balance": {
                        "total": _euros(row["end_balance"]) if manual else computed,
                        # Date du dernier mouvement connu pris en compte (le
                        # solde calcule d'une saison en cours ou dont la fin
                        # n'est pas encore couverte par les releves).
                        "asOf": None if manual else as_of,
                        "auto": not manual,
                        "computed": computed,
                    },
                }
            )

        series: list[dict] = []
        for row in history:
            if series and series[-1]["date"] == row["date"]:
                series[-1]["total"] = row["total"]
            else:
                series.append({"date": row["date"], "total": row["total"]})
        return {"seasons": seasons, "series": series, "today": today_iso}

    # ----- ecriture -----

    def create(self, data: dict) -> dict:
        values = self._validate(data)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.db.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO seasons (name, start_date, end_date, licences, end_balance, ai_cost, created_at,
                   updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (*values, now, now),
            )
        return self._get(cursor.lastrowid)

    def update(self, season_id: int, data: dict) -> dict:
        self._get(season_id)
        values = self._validate(data, season_id)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.db.connect() as connection:
            connection.execute(
                """UPDATE seasons SET name = ?, start_date = ?, end_date = ?, licences = ?, end_balance = ?,
                   ai_cost = ?, updated_at = ? WHERE id = ?""",
                (*values, now, season_id),
            )
        return self._get(season_id)

    def delete(self, season_id: int) -> None:
        with self.db.connect() as connection:
            if connection.execute("DELETE FROM seasons WHERE id = ?", (season_id,)).rowcount == 0:
                raise SeasonNotFoundError(season_id)

    def set_current_licences(self, count: int) -> dict | None:
        """Nombre de licencies FFST de la saison en cours (celle qui contient
        la date du jour), s'il y en a une."""
        today_iso = self.today().isoformat()
        with self.db.connect() as connection:
            row = connection.execute(
                "SELECT id FROM seasons WHERE start_date <= ? AND end_date >= ?", (today_iso, today_iso)
            ).fetchone()
            if row is None:
                return None
            connection.execute("UPDATE seasons SET licences = ? WHERE id = ?", (count, row["id"]))
        return self._get(row["id"])

    def _get(self, season_id: int) -> dict:
        season = next((s for s in self.get_seasons()["seasons"] if s["id"] == season_id), None)
        if season is None:
            raise SeasonNotFoundError(season_id)
        return season

    def _validate(self, data: dict, season_id: int | None = None) -> tuple:
        name = (data.get("name") or "").strip()
        if not name:
            raise SeasonError("Le nom de la saison est obligatoire")
        try:
            start = date.fromisoformat(data.get("startDate") or "")
            end = date.fromisoformat(data.get("endDate") or "")
        except ValueError as exc:
            raise SeasonError("Dates de début et de fin obligatoires") from exc
        if start >= end:
            raise SeasonError("La date de fin doit être après la date de début")
        licences = data.get("licences")
        if licences is not None and licences < 0:
            raise SeasonError("Le nombre de licenciés ne peut pas être négatif")
        with self.db.connect() as connection:
            others = connection.execute(
                "SELECT name, start_date, end_date FROM seasons WHERE id IS NOT ?", (season_id,)
            ).fetchall()
        for other in others:
            if other["name"] == name:
                raise SeasonError(f"La saison {name} existe déjà")
            if other["start_date"] <= end.isoformat() and start.isoformat() <= other["end_date"]:
                raise SeasonError(
                    f"Ces dates chevauchent la saison {other['name']} "
                    f"(du {_fr(other['start_date'])} au {_fr(other['end_date'])})"
                )
        return (
            name,
            start.isoformat(),
            end.isoformat(),
            licences,
            _cents(data.get("endBalance")),
            _cents(data.get("aiCost")),
        )
