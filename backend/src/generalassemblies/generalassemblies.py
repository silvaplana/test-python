"""Assemblees generales (onglet Finances > Assemblées générales) : base du
PowerPoint de l'AG d'une saison.

Un calcul d'AG (table general_assemblies) a un nom, une saison, un etat
(brouillon, valide, officiel : un seul officiel par saison), un prompt, un
modele d'IA et un cout de l'IA cumule. Il garde au plus 3 PPT (voir KINDS),
un par sorte :
- "modele" : le PPT d'exemple dont l'IA reprend la mise en page, envoye
  depuis l'ordinateur ou copie d'un PPT d'un autre calcul ;
- "genere" : le PPT produit par le dernier calcul ;
- "modifie" : le PPT retouche par le tresorier, renvoye dans l'appli.
Un nouveau PPT remplace celui de la meme sorte. Ils sont enregistres dans la
table general_assembly_versions (origin "modele", "genere" ou "envoye" ; la
derniere ligne de chaque origin compte ; source : d'ou vient le PPT), fichiers
storage_dir/<id>/v<n>.pptx (volume Docker).

Executer un calcul (voir run), en arriere-plan :
1. bilan financier de la saison : l'officiel, sinon le valide, sinon le
   brouillon le plus recent (onglet Bilan financier) ; aucun : refuse ;
2. PPT modele : celui du calcul ; s'il n'en a pas, le PPT final de l'AG
   officielle de la saison precedente, sinon le modele general de l'onglet
   (storage_dir/modele.pptx) -- il devient alors le modele du calcul ;
3. l'IA ecrit le texte des diapos du tresorier (voir ai.py) ;
4. l'appli place ce texte dans le modele (voir slides.fill) et verifie que
   chaque montant ecrit vient bien du bilan.
Le cout s'ajoute a celui du calcul et a celui de la saison EN COURS (pas a
celle du calcul, qui peut etre passee).
"""

from __future__ import annotations

import json
import shutil
import threading
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path

from database import Database, ordering
from database import prompts as saved_prompts

from .ai import DEFAULT_MODEL, MODELS, AnalysisError, Draft, Writer
from .slides import (
    SlidesError,
    amounts_in,
    check_amounts,
    fill,
    open_presentation,
    outline,
    texts,
    thumbnails,
)

STATES = {"brouillon": "Brouillon", "valide": "Validé", "officiel": "Officiel"}
STATE_RANK = {"officiel": 0, "valide": 1, "brouillon": 2}
RUN_TIMEOUT = timedelta(minutes=20)
MAX_UPLOAD = 50 * 1024 * 1024
# Les 3 PPT d'un calcul : sorte -> origin en base (voir le haut du fichier).
KINDS = {"modele": "modele", "genere": "genere", "modifie": "envoye"}
KIND_LABELS = {"modele": "modèle", "genere": "produit par l'IA", "modifie": "modifié"}
# PPT final d'un calcul : le modifie s'il existe, sinon celui de l'IA.
FINAL_KINDS = ("modifie", "genere")


class AssemblyError(ValueError):
    """Donnees invalides (message affichable tel quel)."""


class AssemblyNotFoundError(LookupError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class GeneralAssemblies:
    def __init__(
        self,
        db: Database,
        storage_dir: str,
        seasons: Callable[[], list[dict]],
        reports: Callable[[int], list[dict]],
        report: Callable[[int], dict],
        add_ai_cost: Callable[[float], object],
        writer: Writer | None = None,
        background: bool = True,
    ) -> None:
        """seasons : les saisons, la plus ancienne en premier (Seasons) ;
        reports / report : liste des bilans d'une saison et bilan complet
        (FinancialReports.list / get) ; add_ai_cost(euros) : ajoute un cout d'IA a la saison en cours
        (Seasons.add_current_ai_cost).
        background=False : calcul execute directement (tests)."""
        self.db = db
        self.storage = Path(storage_dir)
        self.seasons = seasons
        self.reports = reports
        self.report = report
        self.add_ai_cost = add_ai_cost
        self.writer = writer or Writer()
        self.background = background

    @property
    def template_path(self) -> Path:
        return self.storage / "modele.pptx"

    # ----- lecture -----

    def options(self, season_id: int | None) -> dict:
        """Modeles d'IA, etats, et pour la saison : bilan et PPT modele que
        prendrait un calcul maintenant."""
        sources = {"report": None, "template": None}
        if season_id is not None:
            report = self._source_report(season_id)
            sources["report"] = report and {"id": report["id"], "name": report["name"], "state": report["state"]}
            template = self._template(season_id)
            sources["template"] = template and template[1]
        return {
            "models": [{"id": key, "label": spec["label"]} for key, spec in MODELS.items()],
            "defaultModel": DEFAULT_MODEL,
            "states": [{"id": key, "label": label} for key, label in STATES.items()],
            "templateUploaded": self.template_path.exists(),
            **sources,
        }

    def reorder(self, season_id: int, ids: list[int]) -> list[dict]:
        """Range les cartes de la saison dans l'ordre de `ids` (poignee de
        l'ecran) ; simple reglage d'affichage, la date de modification ne
        change pas."""
        with self.db.connect() as connection:
            ordering.reorder(connection, "general_assemblies", season_id, ids)
        return self.list(season_id)

    def counts(self) -> dict[int, int]:
        """Nombre de calculs d'AG par saison (affiche dans le choix de la saison)."""
        with self.db.connect() as connection:
            rows = connection.execute("SELECT season_id, COUNT(*) FROM general_assemblies GROUP BY season_id").fetchall()
        return {row[0]: row[1] for row in rows}

    def list(self, season_id: int) -> list[dict]:
        with self.db.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM general_assemblies WHERE season_id = ? ORDER BY position, id DESC", (season_id,)
            ).fetchall()
        return [self._summary(row) for row in rows]

    def get(self, assembly_id: int) -> dict:
        row = self._row(assembly_id)
        return {
            **self._summary(row),
            "prompt": row["prompt"],
            "result": json.loads(row["result"]) if row["result"] else None,
            "files": self.files(assembly_id),
            # Zone "Réglages de l'IA" depliee dans l'ecran.
            "settingsOpen": bool(row["settings_open"]),
            "savedPrompts": self.saved_prompts(assembly_id),
        }

    # ----- prompts enregistres du calcul -----

    def saved_prompts(self, assembly_id: int) -> list[dict]:
        return saved_prompts.saved(self.db, "general_assembly_prompts", "assembly_id", assembly_id)

    def save_prompt(self, assembly_id: int, prompt: str) -> list[dict]:
        """Ajoute ce prompt a ceux du calcul (disquette de l'ecran)."""
        prompt = (prompt or "").strip()
        if not prompt:
            raise AssemblyError("Le prompt est vide")
        self._row(assembly_id)
        return saved_prompts.save(self.db, "general_assembly_prompts", "assembly_id", assembly_id, prompt)

    def delete_prompt(self, assembly_id: int, prompt_id: int) -> list[dict]:
        return saved_prompts.delete(self.db, "general_assembly_prompts", "assembly_id", assembly_id, prompt_id)

    def set_settings_open(self, assembly_id: int, is_open: bool) -> dict:
        """Retient si la zone "Réglages de l'IA" est depliee dans l'ecran
        (simple reglage d'affichage : la date de modification ne change pas)."""
        with self.db.connect() as connection:
            updated = connection.execute(
                "UPDATE general_assemblies SET settings_open = ? WHERE id = ?", (1 if is_open else 0, assembly_id)
            ).rowcount
        if updated == 0:
            raise AssemblyNotFoundError(assembly_id)
        return {"settingsOpen": bool(is_open)}

    def files(self, assembly_id: int) -> dict:
        """Les 3 PPT du calcul : {"modele", "genere", "modifie"}, chacun
        {"kind", "filename", "source", "createdAt"} ou None. source : d'ou
        vient le PPT, en clair (None si inconnu)."""
        with self.db.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM general_assembly_versions WHERE assembly_id = ? ORDER BY number", (assembly_id,)
            ).fetchall()
        latest = {row["origin"]: row for row in rows}
        return {
            kind: {
                "kind": kind,
                "filename": latest[origin]["filename"],
                "source": latest[origin]["source"],
                "createdAt": latest[origin]["created_at"],
            }
            if origin in latest
            else None
            for kind, origin in KINDS.items()
        }

    def _row(self, assembly_id: int):
        with self.db.connect() as connection:
            row = connection.execute("SELECT * FROM general_assemblies WHERE id = ?", (assembly_id,)).fetchone()
        if row is None:
            raise AssemblyNotFoundError(assembly_id)
        return row

    def _summary(self, row) -> dict:
        status, error = row["status"], row["error"]
        if status == "running" and datetime.fromisoformat(row["run_started_at"]) < datetime.now(timezone.utc) - RUN_TIMEOUT:
            status, error = "error", "Calcul interrompu (serveur redémarré) : relance-le."
        with self.db.connect() as connection:
            ready = connection.execute(
                "SELECT 1 FROM general_assembly_versions WHERE assembly_id = ? AND origin IN ('genere', 'envoye')",
                (row["id"],),
            ).fetchone()
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
            # Un PPT d'AG existe (produit par l'IA ou modifie).
            "hasPpt": ready is not None,
            "updatedAt": row["updated_at"],
        }

    # ----- ecriture -----

    def create(self, data: dict) -> dict:
        season_id = data.get("seasonId")
        if not any(s["id"] == season_id for s in self.seasons()):
            raise AssemblyError("Saison inconnue")
        name, state, prompt, model = self._validate(data)
        now = _now()
        with self.db.connect() as connection:
            if state == "officiel":
                self._demote_official(connection, season_id)
            cursor = connection.execute(
                """INSERT INTO general_assemblies (season_id, name, state, prompt, model, created_at, updated_at, position)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (season_id, name, state, prompt, model, now, now, ordering.top_position(connection, "general_assemblies", season_id)),
            )
        return self.get(cursor.lastrowid)

    def update(self, assembly_id: int, data: dict) -> dict:
        row = self._row(assembly_id)
        name, state, prompt, model = self._validate(data)
        with self.db.connect() as connection:
            if state == "officiel":
                self._demote_official(connection, row["season_id"], assembly_id)
            connection.execute(
                "UPDATE general_assemblies SET name = ?, state = ?, prompt = ?, model = ?, updated_at = ? WHERE id = ?",
                (name, state, prompt, model, _now(), assembly_id),
            )
        return self.get(assembly_id)

    def delete(self, assembly_id: int) -> None:
        with self.db.connect() as connection:
            if connection.execute("DELETE FROM general_assemblies WHERE id = ?", (assembly_id,)).rowcount == 0:
                raise AssemblyNotFoundError(assembly_id)
        shutil.rmtree(self.storage / str(assembly_id), ignore_errors=True)

    @staticmethod
    def _demote_official(connection, season_id: int, keep: int | None = None) -> None:
        """Une seule AG officielle par saison : l'ancienne repasse en valide."""
        connection.execute(
            "UPDATE general_assemblies SET state = 'valide' WHERE season_id = ? AND state = 'officiel' AND id IS NOT ?",
            (season_id, keep),
        )

    @staticmethod
    def _validate(data: dict) -> tuple[str, str, str, str]:
        name = (data.get("name") or "").strip()
        if not name:
            raise AssemblyError("Le nom est obligatoire")
        state = data.get("state") or "brouillon"
        if state not in STATES:
            raise AssemblyError(f"État inconnu : {state}")
        model = data.get("model") or DEFAULT_MODEL
        if model not in MODELS:
            raise AssemblyError(f"Modèle inconnu : {model}")
        return name, state, (data.get("prompt") or "").strip(), model

    # ----- fichiers -----

    def file_path(self, assembly_id: int, kind: str | None = None) -> tuple[Path, str]:
        """Fichier d'un des 3 PPT du calcul et son nom de telechargement.
        kind None : le PPT final (voir FINAL_KINDS)."""
        if kind is not None and kind not in KINDS:
            raise AssemblyNotFoundError(kind)
        with self.db.connect() as connection:
            for candidate in (kind,) if kind else FINAL_KINDS:
                row = connection.execute(
                    """SELECT * FROM general_assembly_versions WHERE assembly_id = ? AND origin = ?
                       ORDER BY number DESC LIMIT 1""",
                    (assembly_id, KINDS[candidate]),
                ).fetchone()
                if row is not None:
                    return self.storage / str(assembly_id) / f"v{row['number']}.pptx", row["filename"]
        raise AssemblyNotFoundError(assembly_id)

    def _set_file(self, assembly_id: int, kind: str, source: Path | bytes, filename: str, origin_text: str) -> None:
        """Enregistre un PPT du calcul, a la place de celui de la meme sorte.
        origin_text : d'ou il vient, en clair (affiche dans l'ecran)."""
        origin = KINDS[kind]
        folder = self.storage / str(assembly_id)
        folder.mkdir(parents=True, exist_ok=True)
        with self.db.connect() as connection:
            number = (
                connection.execute(
                    "SELECT COALESCE(MAX(number), 0) FROM general_assembly_versions WHERE assembly_id = ?", (assembly_id,)
                ).fetchone()[0]
                + 1
            )
            target = folder / f"v{number}.pptx"
            if isinstance(source, bytes):
                target.write_bytes(source)
            else:
                shutil.move(str(source), target)
            replaced = [
                r["number"]
                for r in connection.execute(
                    "SELECT number FROM general_assembly_versions WHERE assembly_id = ? AND origin = ?",
                    (assembly_id, origin),
                )
            ]
            connection.execute(
                "DELETE FROM general_assembly_versions WHERE assembly_id = ? AND origin = ?", (assembly_id, origin)
            )
            connection.execute(
                """INSERT INTO general_assembly_versions (assembly_id, number, origin, filename, source, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (assembly_id, number, origin, filename, origin_text, _now()),
            )
            connection.execute("UPDATE general_assemblies SET updated_at = ? WHERE id = ?", (_now(), assembly_id))
        # Fichiers et images des diapos des PPT remplaces.
        for old in replaced:
            (folder / f"v{old}.pptx").unlink(missing_ok=True)
            shutil.rmtree(folder / f"v{old}-apercu", ignore_errors=True)

    @staticmethod
    def _check_pptx(content: bytes, path: Path) -> None:
        if len(content) > MAX_UPLOAD:
            raise AssemblyError("Fichier trop gros (50 Mo au plus)")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        try:
            open_presentation(path)
        except SlidesError as exc:
            path.unlink(missing_ok=True)
            raise AssemblyError(str(exc)) from exc

    def upload(self, assembly_id: int, content: bytes, filename: str) -> dict:
        """PPT modifie par le tresorier (remplace le precedent)."""
        self._row(assembly_id)
        tmp = self.storage / str(assembly_id) / "envoi.tmp"
        self._check_pptx(content, tmp)
        self._set_file(assembly_id, "modifie", tmp, filename or "ag.pptx", "Importé de ton ordinateur")
        return self.get(assembly_id)

    def set_model(self, assembly_id: int, content: bytes, filename: str) -> dict:
        """PPT modele du calcul, envoye depuis l'ordinateur."""
        self._row(assembly_id)
        tmp = self.storage / str(assembly_id) / "modele.tmp"
        self._check_pptx(content, tmp)
        self._set_file(assembly_id, "modele", tmp, filename or "modele.pptx", "Importé de ton ordinateur")
        return self.get(assembly_id)

    def copy_model(self, assembly_id: int, source_id: int | None, kind: str) -> dict:
        """PPT modele du calcul, copie d'un PPT d'un autre calcul (source_id,
        kind : une sorte de KINDS) ou du modele general de l'onglet
        (kind "general")."""
        self._row(assembly_id)
        if kind == "general":
            if not self.template_path.exists():
                raise AssemblyError("Il n'y a pas de modèle général")
            path, filename, origin_text = self.template_path, "Modèle général.pptx", "Copie du modèle général"
        else:
            if source_id is None or source_id == assembly_id or kind not in KINDS:
                raise AssemblyError("Choisis un PPT d'un autre calcul")
            try:
                path, filename = self.file_path(source_id, kind)
            except AssemblyNotFoundError as exc:
                raise AssemblyError("Ce PPT n'existe plus") from exc
            source = self._row(source_id)
            season = next((s["name"] for s in self.seasons() if s["id"] == source["season_id"]), "?")
            origin_text = f"Copie du PPT {KIND_LABELS[kind]} du calcul « {source['name']} » ({season})"
        self._set_file(assembly_id, "modele", path.read_bytes(), filename, origin_text)
        return self.get(assembly_id)

    def model_sources(self, exclude: int | None = None) -> list[dict]:
        """PPT qui peuvent servir de modele a un calcul : ceux de tous les
        autres calculs (toutes saisons, le plus recent d'abord), puis le
        modele general de l'onglet s'il existe."""
        names = {s["id"]: s["name"] for s in self.seasons()}
        with self.db.connect() as connection:
            rows = connection.execute(
                """SELECT v.*, a.name AS assembly_name, a.season_id, a.state FROM general_assembly_versions v
                   JOIN general_assemblies a ON a.id = v.assembly_id
                   WHERE a.id IS NOT ? ORDER BY v.number""",
                (exclude,),
            ).fetchall()
        kinds = {origin: kind for kind, origin in KINDS.items()}
        latest = {(row["assembly_id"], row["origin"]): row for row in rows if row["origin"] in kinds}
        sources = [
            {
                "assemblyId": row["assembly_id"],
                "kind": kinds[row["origin"]],
                "label": f"{names.get(row['season_id'], '?')}, {row['assembly_name']} : PPT {KIND_LABELS[kinds[row['origin']]]}",
                "filename": row["filename"],
                "createdAt": row["created_at"],
            }
            for row in sorted(latest.values(), key=lambda r: (r["created_at"], r["number"]), reverse=True)
        ]
        if self.template_path.exists():
            sources.append(
                {"assemblyId": None, "kind": "general", "label": "Modèle général", "filename": "modele.pptx", "createdAt": None}
            )
        return sources

    def set_template(self, content: bytes) -> dict:
        """Modele general : utilise par un calcul sans modele, quand la
        saison precedente n'a pas d'AG officielle."""
        tmp = self.storage / "modele.tmp"
        self._check_pptx(content, tmp)
        tmp.replace(self.template_path)
        return {"templateUploaded": True}

    def _preview(self, assembly_id: int, kind: str) -> tuple[Path, Path]:
        path, _ = self.file_path(assembly_id, kind)
        return path, path.with_name(f"{path.stem}-apercu")

    def slides(self, assembly_id: int, kind: str) -> dict:
        """Apercu d'un des 3 PPT : textes de chaque diapo et, si LibreOffice
        est installe, numero de l'image de chaque diapo affichee."""
        path, folder = self._preview(assembly_id, kind)
        images = thumbnails(path, folder)
        result, index = [], 0
        for slide in texts(path):
            image = None
            if not slide["hidden"]:
                index += 1
                image = index if images and index <= len(images) else None
            result.append({**slide, "image": image})
        return {"slides": result, "thumbnails": images is not None}

    def thumbnail(self, assembly_id: int, kind: str, image: int) -> Path:
        images = thumbnails(*self._preview(assembly_id, kind)) or []
        if not 1 <= image <= len(images):
            raise AssemblyNotFoundError(image)
        return images[image - 1]

    # ----- sources du calcul -----

    def _source_report(self, season_id: int) -> dict | None:
        """Bilan de la saison : l'officiel, sinon le valide, sinon le
        brouillon le plus recent (liste deja triee du plus recent)."""
        candidates = [r for r in self.reports(season_id) if r["hasResult"]]
        return min(candidates, key=lambda r: STATE_RANK[r["state"]], default=None)

    def _template(self, season_id: int) -> tuple[Path, dict] | None:
        """PPT modele par defaut d'un calcul qui n'en a pas : le PPT final de
        l'AG officielle de la saison precedente, sinon le modele general."""
        seasons = self.seasons()
        index = next((i for i, s in enumerate(seasons) if s["id"] == season_id), None)
        if index:
            previous = seasons[index - 1]
            with self.db.connect() as connection:
                row = connection.execute(
                    """SELECT a.id, a.name FROM general_assemblies a
                       WHERE a.season_id = ? AND a.state = 'officiel'
                       AND EXISTS (SELECT 1 FROM general_assembly_versions v
                                   WHERE v.assembly_id = a.id AND v.origin IN ('genere', 'envoye'))""",
                    (previous["id"],),
                ).fetchone()
            if row is not None:
                path, _ = self.file_path(row["id"])
                return path, {"kind": "previous", "name": f"AG officielle {previous['name']} ({row['name']})"}
        if self.template_path.exists():
            return self.template_path, {"kind": "uploaded", "name": "Modèle général"}
        return None

    def _model(self, assembly_id: int, season_id: int) -> tuple[Path, dict] | None:
        """PPT modele d'un calcul : le sien, sinon celui par defaut."""
        try:
            path, filename = self.file_path(assembly_id, "modele")
        except AssemblyNotFoundError:
            return self._template(season_id)
        return path, {"kind": "own", "name": filename}

    # ----- calcul -----

    def run(self, assembly_id: int, data: dict) -> dict:
        row = self._row(assembly_id)
        if self._summary(row)["status"] == "running":
            raise AssemblyError("Un calcul est déjà en cours")
        if self._source_report(row["season_id"]) is None:
            raise AssemblyError("Aucun bilan calculé pour cette saison : calcule-le d'abord dans Bilan financier.")
        if self._model(assembly_id, row["season_id"]) is None:
            raise AssemblyError("Pas de PPT modèle : choisis d'abord le PPT d'une AG précédente.")
        name, state, prompt, model = self._validate({**dict(row), **{k: v for k, v in data.items() if v is not None}})
        with self.db.connect() as connection:
            if state == "officiel":
                self._demote_official(connection, row["season_id"], assembly_id)
            connection.execute(
                """UPDATE general_assemblies SET name = ?, state = ?, prompt = ?, model = ?, status = 'running',
                   error = NULL, run_started_at = ?, updated_at = ? WHERE id = ?""",
                (name, state, prompt, model, _now(), _now(), assembly_id),
            )
        if self.background:
            threading.Thread(target=self._execute, args=(assembly_id,), daemon=True).start()
        else:
            self._execute(assembly_id)
        return self.get(assembly_id)

    def _execute(self, assembly_id: int) -> None:
        row = self._row(assembly_id)
        cost = 0.0
        try:
            seasons = self.seasons()
            index = next(i for i, s in enumerate(seasons) if s["id"] == row["season_id"])
            season = seasons[index]
            source = self._source_report(season["id"])
            if source is None:
                raise AssemblyError("Aucun bilan calculé pour cette saison.")
            report = self.report(source["id"])
            template, template_info = self._model(assembly_id, season["id"])
            if template_info["kind"] != "own":
                # Modele par defaut : il devient le modele du calcul.
                self._set_file(
                    assembly_id,
                    "modele",
                    template.read_bytes(),
                    f"{template_info['name']}.pptx",
                    f"Pris par défaut, faute de modèle choisi : {template_info['name']}",
                )
                template, _ = self.file_path(assembly_id, "modele")
            data = self._ai_data(seasons, index, report, outline(template))
            draft: Draft = self.writer.write(row["model"], data, row["prompt"])
            cost = draft.cost
            output = self.storage / str(assembly_id) / "calcul.tmp"
            output.parent.mkdir(parents=True, exist_ok=True)
            changed = fill(template, output, draft.zones)
            warnings = check_amounts(
                draft.zones, self._known_amounts(report["result"]) | self._prompt_amounts(row["prompt"])
            )
            self._set_file(
                assembly_id,
                "genere",
                output,
                f"AG-{season['name']}-{row['name']}.pptx",
                f"Produit par {MODELS[draft.model]['label']} à partir du PPT modèle",
            )
            result = {
                "report": {"id": report["id"], "name": report["name"], "state": report["state"]},
                "template": template_info,
                "changedSlides": changed,
                "summary": draft.summary,
                "warnings": warnings,
                "model": draft.model,
                "modelLabel": MODELS[draft.model]["label"],
                "servedBy": draft.served_by,
                "cost": cost,
                "generatedAt": _now(),
            }
            with self.db.connect() as connection:
                connection.execute(
                    """UPDATE general_assemblies SET result = ?, status = 'idle', error = NULL,
                       ai_cost = ai_cost + ?, updated_at = ? WHERE id = ?""",
                    (json.dumps(result, ensure_ascii=False), cost, _now(), assembly_id),
                )
        except Exception as exc:  # noqa: BLE001 - tout echec doit sortir le calcul de l'etat "en cours"
            cost = exc.cost if isinstance(exc, AnalysisError) else cost
            message = str(exc) if isinstance(exc, (AnalysisError, AssemblyError, SlidesError)) else f"Le calcul a échoué : {exc}"
            with self.db.connect() as connection:
                connection.execute(
                    "UPDATE general_assemblies SET status = 'error', error = ?, ai_cost = ai_cost + ?, updated_at = ? WHERE id = ?",
                    (message, cost, _now(), assembly_id),
                )
        if cost:
            self.add_ai_cost(cost)

    @staticmethod
    def _known_amounts(result: dict) -> set[float]:
        """Montants du bilan (et de la saison precedente) que l'IA peut citer."""
        amounts = {result.get(k) for k in ("opening", "closing", "totalIncome", "totalExpense", "result")}
        amounts |= {r["amount"] for r in result.get("income", []) + result.get("expense", [])}
        amounts |= set(result.get("net", {}).values())
        previous = result.get("previous") or {}
        amounts |= {previous.get(k) for k in ("opening", "closing", "totalIncome", "totalExpense", "result")}
        amounts |= set((previous.get("net") or {}).values())
        return {a for a in amounts if a is not None}

    @staticmethod
    def _prompt_amounts(prompt: str) -> set[float]:
        """Montants donnes par le tresorier dans son prompt (ex : cotisation)."""
        return set(amounts_in(prompt))

    @staticmethod
    def _ai_data(seasons: list[dict], index: int, report: dict, template: list[dict]) -> dict:
        """Donnees envoyees a l'IA (noms de champs en francais : lus par l'IA)."""
        season = seasons[index]
        result = report["result"]
        previous = result.get("previous")
        following = seasons[index + 1]["name"] if index + 1 < len(seasons) else None
        if following is None and season["name"][:4].isdigit():
            start = int(season["name"][:4])
            following = f"{start + 1}-{start + 2}"
        return {
            "saison": season["name"],
            "saisonSuivante": following,
            "bilan": {
                "nom": report["name"],
                "etat": report["state"],
                "debutSaison": result["start"],
                "finSaison": result["end"],
                "dateArret": result["cutoff"],
                "saisonTerminee": result["cutoff"] >= result["end"],
                "soldeDebut": result["opening"],
                "soldeFin": result["closing"],
                "recettes": {r["category"]: r["amount"] for r in result["income"]},
                "depenses": {r["category"]: r["amount"] for r in result["expense"]},
                "totalRecettes": result["totalIncome"],
                "totalDepenses": result["totalExpense"],
                "resultat": result["result"],
                "verificationDesSoldesOk": result["verification"]["ok"],
                "analyse": result.get("analysis", []),
                "saisonPrecedente": previous
                and {
                    "saison": previous["season"],
                    "soldeDebut": previous["opening"],
                    "soldeFin": previous["closing"],
                    "totalRecettes": previous["totalIncome"],
                    "totalDepenses": previous["totalExpense"],
                    "resultat": previous["result"],
                    "recettesEtDepensesNettesParCategorie": previous["net"],
                },
            },
            "licencies": [{"saison": s["name"], "licencies": s.get("licences")} for s in seasons[: index + 1]],
            "modele": template,
        }
