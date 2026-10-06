"""Bilans financiers d'une saison (onglet Finances > Bilan financier).

Un bilan est un calcul enregistre (table financial_reports) : nom, saison,
etat (brouillon, valide, officiel : un seul officiel par saison), prompt
donne a l'IA, dernier modele utilise, cout de l'IA cumule et resultat du
dernier calcul.

Executer un calcul (voir run) :
1. l'appli calcule le compte d'exploitation de la saison au centime (voir
   report.py) et celui des saisons precedentes ;
2. l'IA (voir ai.py) classe les operations "Autres" et ecrit l'analyse ;
3. l'appli recalcule le tableau avec ce classement et verifie que solde au
   debut + recettes - depenses = solde reel a la fin.
Le calcul tourne en arriere-plan (jusqu'a quelques minutes selon le
modele) : l'ecran relit le bilan jusqu'a ce qu'il soit termine. Son cout
s'ajoute a celui du bilan et a celui de la saison (voir Seasons.add_ai_cost).
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from bankstatements.categories import CATEGORY_NAMES, INTERNAL_TRANSFER, OTHER
from database import Database

from .ai import DEFAULT_MODEL, MODELS, Analysis, AnalysisError, Analyst
from .report import compute_report, unclassified

STATES = {"brouillon": "Brouillon", "valide": "Validé", "officiel": "Officiel"}
# Nombre de saisons precedentes comparees par l'IA.
PREVIOUS_SEASONS = 3
# Calcul "en cours" depuis plus longtemps : le serveur a redemarre entre-temps.
RUN_TIMEOUT = timedelta(minutes=20)


class ReportError(ValueError):
    """Donnees de bilan invalides (message affichable tel quel)."""


class ReportNotFoundError(LookupError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class FinancialReports:
    def __init__(
        self,
        db: Database,
        ledger: Callable[[], dict],
        seasons: Callable[[], list[dict]],
        add_season_ai_cost: Callable[[int, float], None],
        analyst: Analyst | None = None,
        background: bool = True,
    ) -> None:
        """ledger : historique des comptes (BankStatements.get_ledger) ;
        seasons : les saisons, la plus ancienne en premier (fiches de
        Seasons.get_seasons) ; add_season_ai_cost : Seasons.add_ai_cost.
        background=False : calcul execute directement (tests)."""
        self.db = db
        self.ledger = ledger
        self.seasons = seasons
        self.add_season_ai_cost = add_season_ai_cost
        self.analyst = analyst or Analyst()
        self.background = background

    # ----- lecture -----

    def models(self) -> dict:
        return {
            "models": [{"id": key, "label": spec["label"]} for key, spec in MODELS.items()],
            "defaultModel": DEFAULT_MODEL,
            "states": [{"id": key, "label": label} for key, label in STATES.items()],
        }

    def list(self, season_id: int) -> list[dict]:
        with self.db.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM financial_reports WHERE season_id = ? ORDER BY updated_at DESC, id DESC", (season_id,)
            ).fetchall()
        return [self._summary(row) for row in rows]

    def get(self, report_id: int) -> dict:
        row = self._row(report_id)
        return {**self._summary(row), "prompt": row["prompt"], "result": json.loads(row["result"]) if row["result"] else None}

    def _row(self, report_id: int):
        with self.db.connect() as connection:
            row = connection.execute("SELECT * FROM financial_reports WHERE id = ?", (report_id,)).fetchone()
        if row is None:
            raise ReportNotFoundError(report_id)
        return row

    def _summary(self, row) -> dict:
        status, error = row["status"], row["error"]
        if status == "running" and datetime.fromisoformat(row["run_started_at"]) < datetime.now(timezone.utc) - RUN_TIMEOUT:
            status, error = "error", "Calcul interrompu (serveur redémarré) : relance-le."
        return {
            "id": row["id"],
            "seasonId": row["season_id"],
            "name": row["name"],
            "state": row["state"],
            "model": row["model"],
            "modelLabel": MODELS.get(row["model"], {}).get("label", row["model"]),
            "aiCost": row["ai_cost"],
            "status": status,
            "error": error,
            "hasResult": row["result"] is not None,
            "updatedAt": row["updated_at"],
        }

    # ----- ecriture -----

    def create(self, data: dict) -> dict:
        season_id = data.get("seasonId")
        if not any(s["id"] == season_id for s in self.seasons()):
            raise ReportError("Saison inconnue")
        name, state, prompt, model = self._validate(data)
        now = _now()
        with self.db.connect() as connection:
            if state == "officiel":
                self._demote_official(connection, season_id)
            cursor = connection.execute(
                """INSERT INTO financial_reports (season_id, name, state, prompt, model, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (season_id, name, state, prompt, model, now, now),
            )
        return self.get(cursor.lastrowid)

    def update(self, report_id: int, data: dict) -> dict:
        row = self._row(report_id)
        name, state, prompt, model = self._validate(data)
        with self.db.connect() as connection:
            if state == "officiel":
                self._demote_official(connection, row["season_id"], report_id)
            connection.execute(
                "UPDATE financial_reports SET name = ?, state = ?, prompt = ?, model = ?, updated_at = ? WHERE id = ?",
                (name, state, prompt, model, _now(), report_id),
            )
        return self.get(report_id)

    def delete(self, report_id: int) -> None:
        with self.db.connect() as connection:
            if connection.execute("DELETE FROM financial_reports WHERE id = ?", (report_id,)).rowcount == 0:
                raise ReportNotFoundError(report_id)

    @staticmethod
    def _demote_official(connection, season_id: int, keep: int | None = None) -> None:
        """Un seul bilan officiel par saison : l'ancien repasse en valide."""
        connection.execute(
            "UPDATE financial_reports SET state = 'valide' WHERE season_id = ? AND state = 'officiel' AND id IS NOT ?",
            (season_id, keep),
        )

    @staticmethod
    def _validate(data: dict) -> tuple[str, str, str, str]:
        name = (data.get("name") or "").strip()
        if not name:
            raise ReportError("Le nom du bilan est obligatoire")
        state = data.get("state") or "brouillon"
        if state not in STATES:
            raise ReportError(f"État inconnu : {state}")
        model = data.get("model") or DEFAULT_MODEL
        if model not in MODELS:
            raise ReportError(f"Modèle inconnu : {model}")
        return name, state, (data.get("prompt") or "").strip(), model

    # ----- calcul -----

    def run(self, report_id: int, data: dict) -> dict:
        """Enregistre le prompt et le modele, puis lance le calcul (en
        arriere-plan). Retourne le bilan, "status": "running"."""
        row = self._row(report_id)
        if self._summary(row)["status"] == "running":
            raise ReportError("Un calcul est déjà en cours pour ce bilan")
        name, state, prompt, model = self._validate({**dict(row), **{k: v for k, v in data.items() if v is not None}})
        with self.db.connect() as connection:
            connection.execute(
                """UPDATE financial_reports SET name = ?, state = ?, prompt = ?, model = ?, status = 'running',
                   error = NULL, run_started_at = ?, updated_at = ? WHERE id = ?""",
                (name, state, prompt, model, _now(), _now(), report_id),
            )
        if self.background:
            threading.Thread(target=self._execute, args=(report_id,), daemon=True).start()
        else:
            self._execute(report_id)
        return self.get(report_id)

    def _execute(self, report_id: int) -> None:
        row = self._row(report_id)
        cost = 0.0
        try:
            seasons = self.seasons()
            index = next(i for i, s in enumerate(seasons) if s["id"] == row["season_id"])
            season = seasons[index]
            previous = seasons[max(0, index - PREVIOUS_SEASONS) : index]
            ledger = self.ledger()
            base = compute_report(ledger, season["startDate"], season["endDate"])
            history = [self._season_summary(ledger, s) for s in previous]
            analysis: Analysis = self.analyst.analyze(
                row["model"], self._ai_data(season, base, history), row["prompt"]
            )
            cost = analysis.cost
            # Seules les operations "Autres" peuvent changer de categorie.
            allowed = {op["id"] for op in unclassified(base)}
            classifications = {i: c for i, c in analysis.classifications.items() if i in allowed and c != INTERNAL_TRANSFER}
            table = compute_report(ledger, season["startDate"], season["endDate"], classifications)
            result = {
                **table,
                "seasonName": season["name"],
                "licences": season.get("licences"),
                "previous": history[-1] if history else None,
                "analysis": analysis.analysis,
                "classifications": {str(i): c for i, c in classifications.items()},
                "model": analysis.model,
                "modelLabel": MODELS[analysis.model]["label"],
                "servedBy": analysis.served_by,
                "cost": cost,
                "generatedAt": _now(),
            }
            with self.db.connect() as connection:
                connection.execute(
                    """UPDATE financial_reports SET result = ?, status = 'idle', error = NULL,
                       ai_cost = ai_cost + ?, updated_at = ? WHERE id = ?""",
                    (json.dumps(result, ensure_ascii=False), cost, _now(), report_id),
                )
        except Exception as exc:  # noqa: BLE001 - tout echec doit sortir le bilan de l'etat "en cours"
            cost = exc.cost if isinstance(exc, AnalysisError) else cost
            message = str(exc) if isinstance(exc, AnalysisError) else f"Le calcul a échoué : {exc}"
            with self.db.connect() as connection:
                connection.execute(
                    "UPDATE financial_reports SET status = 'error', error = ?, ai_cost = ai_cost + ?, updated_at = ? WHERE id = ?",
                    (message, cost, _now(), report_id),
                )
        if cost:
            self.add_season_ai_cost(row["season_id"], cost)

    def _official_classifications(self, season_id: int) -> dict[int, str]:
        """Classement des operations "Autres" du bilan officiel de la saison,
        s'il y en a un (pour comparer avec les memes categories)."""
        with self.db.connect() as connection:
            row = connection.execute(
                "SELECT result FROM financial_reports WHERE season_id = ? AND state = 'officiel' AND result IS NOT NULL",
                (season_id,),
            ).fetchone()
        if row is None:
            return {}
        return {int(i): c for i, c in json.loads(row["result"]).get("classifications", {}).items()}

    def _season_summary(self, ledger: dict, season: dict) -> dict:
        """Chiffres d'une saison precedente, pour la comparaison."""
        table = compute_report(
            ledger, season["startDate"], season["endDate"], self._official_classifications(season["id"])
        )
        return {
            "season": season["name"],
            "licences": season.get("licences"),
            "opening": table["opening"],
            "closing": table["closing"],
            "totalIncome": table["totalIncome"],
            "totalExpense": table["totalExpense"],
            "result": table["result"],
            "net": table["net"],
            "complete": table["opening"] is not None and table["cutoff"] == season["endDate"],
        }

    @staticmethod
    def _ai_data(season: dict, table: dict, history: list[dict]) -> dict:
        """Chiffres envoyes a l'IA (noms de champs en francais : ils sont lus
        par l'IA, pas par du code)."""
        return {
            "saison": season["name"],
            "debutSaison": season["startDate"],
            "finSaison": season["endDate"],
            "dateArret": table["cutoff"],
            "saisonTerminee": table["cutoff"] >= season["endDate"],
            "licencies": season.get("licences"),
            "soldeDebut": table["opening"],
            "soldeFin": table["closing"],
            "recettes": {r["category"]: r["amount"] for r in table["income"]},
            "depenses": {r["category"]: r["amount"] for r in table["expense"]},
            "totalRecettes": table["totalIncome"],
            "totalDepenses": table["totalExpense"],
            "resultat": table["result"],
            "parMois": [
                {
                    "mois": m["month"],
                    "recettes": round(sum(v for v in m["amounts"].values() if v > 0), 2),
                    "depenses": round(-sum(v for v in m["amounts"].values() if v < 0), 2),
                    "soldeFinDeMois": m["closing"],
                }
                for m in table["months"]
            ],
            "saisonsPrecedentes": [
                {
                    "saison": h["season"],
                    "licencies": h["licences"],
                    "soldeDebut": h["opening"],
                    "soldeFin": h["closing"],
                    "recettesEtDepensesNettesParCategorie": h["net"],
                    "resultat": h["result"],
                    "releveComplet": h["complete"],
                }
                for h in history
            ],
            "categoriesExistantes": [c for c in CATEGORY_NAMES if c not in (OTHER, INTERNAL_TRANSFER)],
            "operationsAClasser": [
                {"operationId": op["id"], "date": op["date"], "libelle": op["label"], "details": op["details"], "montant": op["amount"]}
                for op in unclassified(table)
            ],
        }
