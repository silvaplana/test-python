"""Previsionnels d'une saison (onglet Finances > Prévisionnel).

Un previsionnel est un calcul enregistre (table forecasts) : nom, saison,
etat (brouillon, valide, officiel ; plusieurs par saison), date de depart
(vide : dernier jour connu des comptes), prompt donne a l'IA, dernier
modele utilise, cout de l'IA cumule, resultat du dernier calcul et derniere
position des curseurs.

Executer un calcul (voir run) :
1. l'appli prepare les donnees (voir data.py) : solde reel a la date de
   depart, moyennes mensuelles par categorie, adherents et echeances
   HelloAsso a venir ;
2. l'IA (voir ai.py) ecrit une formule Python prevoir(donnees, p) et
   declare ses parametres (curseurs) ;
3. l'appli verifie et execute la formule a part (voir sandbox.py).
Ensuite, bouger un curseur rejoue la formule (voir set_params), sans
rappeler l'IA. Le calcul tourne en arriere-plan ; son cout s'ajoute a celui
du previsionnel et a celui de la saison EN COURS (pas a celle du
previsionnel, qui peut etre passee).
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone

from financialreports.ai import AnalysisError

from database import ordering
from database import prompts as saved_prompts

from . import data as forecast_data
from . import exports
from .ai import DEFAULT_MODEL, MODELS, Coder, Formula, defaults
from .sandbox import FormulaError, run as run_formula

STATES = {"brouillon": "Brouillon", "valide": "Validé", "officiel": "Officiel"}
# Calcul "en cours" depuis plus longtemps : le serveur a redemarre entre-temps.
RUN_TIMEOUT = timedelta(minutes=20)


class ForecastError(ValueError):
    """Donnees de previsionnel invalides (message affichable tel quel)."""


class ForecastNotFoundError(LookupError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Forecasts:
    def __init__(
        self,
        db,
        ledger: Callable[[], dict],
        seasons: Callable[[], list[dict]],
        add_ai_cost: Callable[[float], object],
        members: Callable[[], dict] | None = None,
        today: Callable[[], date] = date.today,
        coder: Coder | None = None,
        background: bool = True,
    ) -> None:
        """ledger : BankStatements.get_ledger ; seasons : fiches de
        Seasons.get_seasons, la plus ancienne en premier ; add_ai_cost(euros) :
        ajoute un cout d'IA a la saison en cours (Seasons.add_current_ai_cost) ;
        members : chiffres
        des adherents HelloAsso (HelloAssoReceiver.getSummary), lus seulement
        pour une date de depart recente. background=False : calcul execute
        directement (tests)."""
        self.db = db
        self.ledger = ledger
        self.seasons = seasons
        self.add_ai_cost = add_ai_cost
        self.members = members
        self.today = today
        self.coder = coder or Coder()
        self.background = background

    # ----- lecture -----

    def models(self) -> dict:
        return {
            "models": [{"id": key, "label": spec["label"]} for key, spec in MODELS.items()],
            "defaultModel": DEFAULT_MODEL,
            "states": [{"id": key, "label": label} for key, label in STATES.items()],
        }

    def reorder(self, season_id: int, ids: list[int]) -> list[dict]:
        """Range les cartes de la saison dans l'ordre de `ids` (poignee de
        l'ecran) ; simple reglage d'affichage, la date de modification ne
        change pas."""
        with self.db.connect() as connection:
            ordering.reorder(connection, "forecasts", season_id, ids)
        return self.list(season_id)

    def counts(self) -> dict[int, int]:
        """Nombre de previsionnels par saison (affiche dans le choix de la saison)."""
        with self.db.connect() as connection:
            rows = connection.execute("SELECT season_id, COUNT(*) FROM forecasts GROUP BY season_id").fetchall()
        return {row[0]: row[1] for row in rows}

    def list(self, season_id: int) -> list[dict]:
        with self.db.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM forecasts WHERE season_id = ? ORDER BY position, id DESC", (season_id,)
            ).fetchall()
        return [self._summary(row) for row in rows]

    def get(self, forecast_id: int) -> dict:
        row = self._row(forecast_id)
        return {
            **self._summary(row),
            "prompt": row["prompt"],
            "result": json.loads(row["result"]) if row["result"] else None,
            # Derniere position des curseurs.
            "params": json.loads(row["params"]) if row["params"] else {},
            # Zone "Explication du résultat de l'IA" depliee dans l'ecran.
            "explanationOpen": bool(row["explanation_open"]),
            # Zone "Réglages de l'IA" (prompt, modele, cout) depliee.
            "settingsOpen": bool(row["settings_open"]),
            "savedPrompts": self.saved_prompts(forecast_id),
        }

    # ----- prompts enregistres du calcul -----

    def saved_prompts(self, forecast_id: int) -> list[dict]:
        return saved_prompts.saved(self.db, "forecast_prompts", "forecast_id", forecast_id)

    def save_prompt(self, forecast_id: int, prompt: str) -> list[dict]:
        """Ajoute ce prompt a ceux du calcul (disquette de l'ecran)."""
        prompt = (prompt or "").strip()
        if not prompt:
            raise ForecastError("Le prompt est vide")
        self._row(forecast_id)
        return saved_prompts.save(self.db, "forecast_prompts", "forecast_id", forecast_id, prompt)

    def delete_prompt(self, forecast_id: int, prompt_id: int) -> list[dict]:
        return saved_prompts.delete(self.db, "forecast_prompts", "forecast_id", forecast_id, prompt_id)

    def set_settings_open(self, forecast_id: int, is_open: bool) -> dict:
        """Retient si la zone "Réglages de l'IA" est depliee dans l'ecran
        (simple reglage d'affichage : la date de modification ne change pas)."""
        with self.db.connect() as connection:
            updated = connection.execute(
                "UPDATE forecasts SET settings_open = ? WHERE id = ?", (1 if is_open else 0, forecast_id)
            ).rowcount
        if updated == 0:
            raise ForecastNotFoundError(forecast_id)
        return {"settingsOpen": bool(is_open)}

    def set_explanation_open(self, forecast_id: int, is_open: bool) -> dict:
        """Retient si la zone "Explication du résultat de l'IA" est depliee
        (simple reglage d'affichage : la date de modification ne change pas)."""
        with self.db.connect() as connection:
            updated = connection.execute(
                "UPDATE forecasts SET explanation_open = ? WHERE id = ?", (1 if is_open else 0, forecast_id)
            ).rowcount
        if updated == 0:
            raise ForecastNotFoundError(forecast_id)
        return {"explanationOpen": bool(is_open)}

    def _row(self, forecast_id: int):
        with self.db.connect() as connection:
            row = connection.execute("SELECT * FROM forecasts WHERE id = ?", (forecast_id,)).fetchone()
        if row is None:
            raise ForecastNotFoundError(forecast_id)
        return row

    def _summary(self, row) -> dict:
        status, error = row["status"], row["error"]
        if status == "running" and datetime.fromisoformat(row["run_started_at"]) < datetime.now(timezone.utc) - RUN_TIMEOUT:
            status, error = "error", "Calcul interrompu (serveur redémarré) : relance-le."
        result = json.loads(row["result"]) if row["result"] else None
        return {
            "id": row["id"],
            "seasonId": row["season_id"],
            "name": row["name"],
            "state": row["state"],
            "startDate": row["start_date"],
            "model": row["model"],
            "modelLabel": MODELS.get(row["model"], {}).get("label", row["model"]),
            "aiCost": row["ai_cost"],
            "status": status,
            "error": error,
            "hasResult": result is not None,
            # Solde prevu en fin de saison, avec les curseurs enregistres.
            "endBalance": result["points"][-1]["solde"] if result and result.get("points") else None,
            "updatedAt": row["updated_at"],
        }

    # ----- ecriture -----

    def create(self, data: dict) -> dict:
        season = self._season(data.get("seasonId"))
        name, state, prompt, model, start = self._validate(data, season)
        now = _now()
        with self.db.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO forecasts (season_id, name, state, prompt, model, start_date, created_at, updated_at, position)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (season["id"], name, state, prompt, model, start, now, now, ordering.top_position(connection, "forecasts", season["id"])),
            )
        return self.get(cursor.lastrowid)

    def update(self, forecast_id: int, data: dict) -> dict:
        row = self._row(forecast_id)
        name, state, prompt, model, start = self._validate(data, self._season(row["season_id"]))
        with self.db.connect() as connection:
            connection.execute(
                "UPDATE forecasts SET name = ?, state = ?, prompt = ?, model = ?, start_date = ?, updated_at = ? WHERE id = ?",
                (name, state, prompt, model, start, _now(), forecast_id),
            )
        return self.get(forecast_id)

    def delete(self, forecast_id: int) -> None:
        with self.db.connect() as connection:
            if connection.execute("DELETE FROM forecasts WHERE id = ?", (forecast_id,)).rowcount == 0:
                raise ForecastNotFoundError(forecast_id)

    def _season(self, season_id) -> dict:
        season = next((s for s in self.seasons() if s["id"] == season_id), None)
        if season is None:
            raise ForecastError("Saison inconnue")
        return season

    @staticmethod
    def _validate(data: dict, season: dict) -> tuple[str, str, str, str, str | None]:
        name = (data.get("name") or "").strip()
        if not name:
            raise ForecastError("Le nom du prévisionnel est obligatoire")
        state = data.get("state") or "brouillon"
        if state not in STATES:
            raise ForecastError(f"État inconnu : {state}")
        model = data.get("model") or DEFAULT_MODEL
        if model not in MODELS:
            raise ForecastError(f"Modèle inconnu : {model}")
        start = data.get("startDate") or None
        if start is not None:
            try:
                date.fromisoformat(start)
            except ValueError as exc:
                raise ForecastError(f"Date de départ invalide : {start}") from exc
            if not season["startDate"] <= start < season["endDate"]:
                raise ForecastError("La date de départ doit être dans la saison, avant son dernier jour")
        return name, state, (data.get("prompt") or "").strip(), model, start

    # ----- calcul -----

    def start_date(self, season: dict, start: str | None) -> str:
        """Date de depart effective : celle du previsionnel, sinon le dernier
        jour connu des comptes (au plus aujourd'hui), ramenee dans la saison."""
        if start:
            return start
        known = forecast_data.last_known_day(self.ledger()) or self.today().isoformat()
        day = min(known, self.today().isoformat())
        if day >= season["endDate"]:
            raise ForecastError("Saison terminée : choisissez une date de départ pour tester le prévisionnel")
        return max(day, season["startDate"])

    def run(self, forecast_id: int, data: dict) -> dict:
        """Enregistre le prompt et le modele, puis lance le calcul (en
        arriere-plan). Retourne le previsionnel, "status": "running"."""
        row = self._row(forecast_id)
        if self._summary(row)["status"] == "running":
            raise ForecastError("Un calcul est déjà en cours pour ce prévisionnel")
        season = self._season(row["season_id"])
        merged = {
            "name": row["name"], "state": row["state"], "prompt": row["prompt"], "model": row["model"],
            "startDate": row["start_date"], **{k: v for k, v in data.items() if v is not None},
        }
        name, state, prompt, model, start = self._validate(merged, season)
        self.start_date(season, start)  # saison terminee sans date : refuse tout de suite
        with self.db.connect() as connection:
            connection.execute(
                """UPDATE forecasts SET name = ?, state = ?, prompt = ?, model = ?, start_date = ?, status = 'running',
                   error = NULL, run_started_at = ?, updated_at = ? WHERE id = ?""",
                (name, state, prompt, model, start, _now(), _now(), forecast_id),
            )
        if self.background:
            threading.Thread(target=self._execute, args=(forecast_id,), daemon=True).start()
        else:
            self._execute(forecast_id)
        return self.get(forecast_id)

    def _members(self, start: str) -> dict | None:
        """Adherents HelloAsso, seulement pour une date de depart recente :
        ils decrivent la campagne d'aujourd'hui."""
        if self.members is None or start < (self.today() - timedelta(days=31)).isoformat():
            return None
        try:
            return self.members()
        except Exception:  # noqa: BLE001 - HelloAsso indisponible : on fait sans
            return None

    def _execute(self, forecast_id: int) -> None:
        row = self._row(forecast_id)
        cost = 0.0
        try:
            season = self._season(row["season_id"])
            start = self.start_date(season, row["start_date"])
            data = forecast_data.build(self.ledger(), season, start, self._members(start))
            if not data["semaines"]:
                raise ForecastError("Rien à prévoir : la date de départ est le dernier jour de la saison")
            formula: Formula = self.coder.write(row["model"], data, row["prompt"])
            cost = formula.cost
            # Curseurs : position enregistree si le parametre existe toujours
            # (et reste dans ses bornes), sinon sa valeur par defaut.
            saved = json.loads(row["params"]) if row["params"] else {}
            params = {
                p["name"]: min(p["max"], max(p["min"], float(saved[p["name"]]))) if p["name"] in saved else p["default"]
                for p in formula.parameters
            }
            balances = formula.balances if params == defaults(formula.parameters) else run_formula(formula.code, data, params)
            result = {
                "code": formula.code,
                "explanation": formula.explanation,
                "parameters": formula.parameters,
                "data": data,
                "points": self._points(data, balances),
                "seasonName": season["name"],
                "model": formula.model,
                "modelLabel": MODELS[formula.model]["label"],
                "servedBy": formula.served_by,
                "cost": cost,
                "generatedAt": _now(),
            }
            with self.db.connect() as connection:
                connection.execute(
                    """UPDATE forecasts SET result = ?, params = ?, status = 'idle', error = NULL,
                       ai_cost = ai_cost + ?, updated_at = ? WHERE id = ?""",
                    (json.dumps(result, ensure_ascii=False), json.dumps(params), cost, _now(), forecast_id),
                )
        except Exception as exc:  # noqa: BLE001 - tout echec doit sortir le previsionnel de l'etat "en cours"
            cost = exc.cost if isinstance(exc, AnalysisError) else cost
            known = isinstance(exc, (AnalysisError, ForecastError, FormulaError, ValueError))
            message = str(exc) if known else f"Le calcul a échoué : {exc}"
            with self.db.connect() as connection:
                connection.execute(
                    "UPDATE forecasts SET status = 'error', error = ?, ai_cost = ai_cost + ?, updated_at = ? WHERE id = ?",
                    (message, cost, _now(), forecast_id),
                )
        if cost:
            self.add_ai_cost(cost)

    @staticmethod
    def _points(data: dict, balances: list[float]) -> list[dict]:
        """Courbe prevue : le solde reel a la date de depart puis une valeur
        par semaine."""
        return [{"date": data["dateDepart"], "solde": data["soldeDepart"]}] + [
            {"date": week["date"], "solde": value} for week, value in zip(data["semaines"], balances)
        ]

    def set_params(self, forecast_id: int, values: dict) -> dict:
        """Rejoue la formule avec de nouvelles positions des curseurs et les
        enregistre. Retourne le previsionnel complet."""
        row = self._row(forecast_id)
        if not row["result"]:
            raise ForecastError("Ce prévisionnel n'a pas encore été calculé")
        result = json.loads(row["result"])
        params = {}
        for p in result["parameters"]:
            value = values.get(p["name"], p["default"])
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ForecastError(f"Valeur invalide pour {p['label']}")
            params[p["name"]] = min(p["max"], max(p["min"], float(value)))
        balances = run_formula(result["code"], result["data"], params)
        result["points"] = self._points(result["data"], balances)
        with self.db.connect() as connection:
            connection.execute(
                "UPDATE forecasts SET result = ?, params = ?, updated_at = ? WHERE id = ?",
                (json.dumps(result, ensure_ascii=False), json.dumps(params), _now(), forecast_id),
            )
        return self.get(forecast_id)

    def export(self, forecast_id: int, file_format: str, season_ids: list[int] | None = None) -> tuple[bytes, str, str]:
        """Resultat en image (png) ou PDF : (contenu, type, nom du fichier).
        season_ids : saisons superposees pour comparer, celles choisies a
        l'ecran (None : la saison precedente)."""
        forecast = self.get(forecast_id)
        if forecast["result"] is None:
            raise ForecastError("Ce prévisionnel n'a pas encore été calculé")
        if file_format not in ("png", "pdf"):
            raise ForecastError("Format inconnu (png ou pdf)")
        seasons = self.seasons()
        index = next((i for i, s in enumerate(seasons) if s["id"] == forecast["seasonId"]), None)
        earlier = seasons[:index] if index else []
        if season_ids is None:
            season_ids = [s["id"] for s in earlier[-1:]]
        # Seules les saisons d'avant se comparent ; couleur selon le rang de
        # la saison, comme a l'ecran.
        compared = [
            {**s, "color": exports.SEASON_COLORS[i % len(exports.SEASON_COLORS)]}
            for i, s in enumerate(earlier)
            if s["id"] in season_ids
        ]
        ledger = self.ledger()
        name = f"previsionnel-{forecast['result']['seasonName']}-{forecast['id']}.{file_format}"
        if file_format == "png":
            return exports.to_png(exports.chart_svg(forecast, ledger, compared)), "image/png", name
        chart = exports.to_png(exports.chart_svg(forecast, ledger, compared, header=False))
        return exports.to_pdf(forecast, chart), "application/pdf", name
