"""Verification par IA du dossier de chaque adherent (onglet HelloAsso >
Adherents, menu "Vérifier adhérents par IA") : photo d'identite, certificat
medical, autorisation parentale (mineurs) et coherence des reponses au
formulaire.

Deroule pour un adherent (voir MemberChecks.check) :
1. controles sans IA : documents manquants, date de naissance illisible,
   fichier illisible ;
2. s'il a depose au moins un document, UN appel a l'API Claude (voir
   Inspector) avec ses documents en images et ses reponses : l'IA dit, pour
   chaque element, s'il est correct et sinon pourquoi.
Le resultat est garde en base (table member_checks, voir database.py) :
statut "ok", "probleme" ou "erreur" (l'appel a echoue), raisons, et cout
cumule de l'IA pour cet adherent. Un adherent "ok" n'est plus reverifie :
relancer la verification ne coute que pour les autres.

Les documents (dont le certificat medical, donnee de sante) sont envoyes a
l'API Claude pour cette verification ; ils ne sont pas stockes ici.
"""

from __future__ import annotations

import base64
import io
import json
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timezone

import anthropic
import pymupdf
from PIL import Image, ImageOps

from database import Database
from financialreports.ai import MODELS, _cost

from .summary import CANCELED_ITEM_STATES

OK, PROBLEM, ERROR = "ok", "probleme", "erreur"
ADULT_AGE = 18
# Documents du formulaire reconnus par le nom de leur champ.
DOCUMENTS = {
    "photo": ("Photo d'identité", re.compile(r"photo", re.I)),
    "certificat": ("Certificat médical", re.compile(r"certificat", re.I)),
    "autorisation": ("Autorisation parentale", re.compile(r"autorisation parentale", re.I)),
}
DATA = "donnees"
# Pages d'un PDF transmises a l'IA, et plus grand cote d'une image (pixels).
MAX_PAGES = 2
MAX_SIDE = 1400

INSTRUCTIONS = """Tu aides le secrétaire d'un club de sambo (sport de combat), l'association Alliance Sambo Combat La Ciotat, à contrôler les dossiers d'inscription de ses adhérents.
On te donne les réponses d'un adhérent au formulaire d'inscription et les documents qu'il a déposés, en images. Pour chaque élément, dis s'il est correct ("ok": true) ou non ("ok": false), avec dans "raison" une phrase courte en français qui explique le problème (vide si tout va bien).

- photo : la photo d'identité doit montrer un être humain dont on voit le visage. Refuse un objet, un animal, un logo, un dessin, un document, une image vide ou illisible.
- certificat : ce doit être un certificat médical (ou une attestation médicale) qui autorise la pratique du sport, établi pour cet adhérent (nom et prénom concordants, en tolérant la casse, les accents et l'ordre), daté, et signé ou tamponné par un médecin. Signale un certificat daté de plus d'un an avant la date du jour, un document qui n'est pas un certificat médical, un autre nom, ou un document illisible.
- autorisation : ce doit être une autorisation parentale pour un mineur, signée par un parent ou un représentant légal, et qui concerne cet adhérent. Signale un document qui n'en est pas une, non signé, ou illisible.
- donnees : signale seulement une anomalie nette dans les réponses (date de naissance impossible, téléphone ou e-mail manifestement faux, nom et prénom inversés ou fantaisistes). Ne signale ni les fautes de frappe mineures ni les différences de casse.

Si un document n'est pas fourni, réponds "ok": true et une raison vide pour lui : son absence est traitée ailleurs. En cas de doute raisonnable, laisse "ok": true ; ne signale que ce qu'un bénévole devrait vraiment aller regarder.
"""

_VERDICT = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}, "raison": {"type": "string"}},
    "required": ["ok", "raison"],
    "additionalProperties": False,
}
SCHEMA = {
    "type": "object",
    "properties": {key: _VERDICT for key in (*DOCUMENTS, DATA)},
    "required": [*DOCUMENTS, DATA],
    "additionalProperties": False,
}


class InspectionError(Exception):
    """Echec de l'appel a l'IA (message affichable). cost : ce que l'appel a
    quand meme coute (euros)."""

    def __init__(self, message: str, cost: float = 0.0) -> None:
        super().__init__(message)
        self.cost = cost


@dataclass
class Verdict:
    results: dict[str, dict]  # element -> {"ok": bool, "raison": str}
    cost: float  # euros


def to_images(content: bytes) -> list[bytes]:
    """Fichier depose (photo de telephone, scan, PDF) -> images JPEG a
    envoyer a l'IA : les MAX_PAGES premieres pages d'un PDF, sinon l'image
    elle-meme, redressee (EXIF) et reduite. ValueError si illisible."""
    try:
        if content.startswith(b"%PDF"):
            with pymupdf.open(stream=content, filetype="pdf") as pdf:
                pages = []
                for page in list(pdf)[:MAX_PAGES]:
                    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
                    pages.append(Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples))
        else:
            pages = [ImageOps.exif_transpose(Image.open(io.BytesIO(content))).convert("RGB")]
    except Exception as exc:  # noqa: BLE001 - tout fichier illisible, quel que soit le format
        raise ValueError(f"fichier illisible ({type(exc).__name__})") from exc
    if not pages:
        raise ValueError("fichier vide")
    images = []
    for page in pages:
        page.thumbnail((MAX_SIDE, MAX_SIDE))
        buffer = io.BytesIO()
        page.save(buffer, format="JPEG", quality=80)
        images.append(buffer.getvalue())
    return images


class Inspector:
    """Appel a l'API Claude (cle ANTHROPIC_API_KEY, comme le bilan financier)."""

    def __init__(self) -> None:
        self._client: anthropic.Anthropic | None = None

    def inspect(self, model: str, answers: dict, documents: dict[str, list[bytes]], today: date) -> Verdict:
        """answers : identite et reponses au formulaire ; documents :
        {"photo" | "certificat" | "autorisation": [images JPEG]}."""
        if self._client is None:
            self._client = anthropic.Anthropic()
        spec = MODELS[model]
        content: list[dict] = [
            {
                "type": "text",
                "text": f"Date du jour : {today.isoformat()}\nAdhérent et réponses au formulaire (JSON) :\n"
                + json.dumps(answers, ensure_ascii=False, indent=1),
            }
        ]
        for key, images in documents.items():
            for number, image in enumerate(images, start=1):
                content.append({"type": "text", "text": f"Document « {key} » : {DOCUMENTS[key][0]}, page {number}"})
                content.append(
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(image).decode()},
                    }
                )
        missing = [key for key in DOCUMENTS if key not in documents]
        if missing:
            content.append({"type": "text", "text": "Documents non fournis : " + ", ".join(missing) + "."})
        params = {
            "model": spec["id"],
            "max_tokens": 8000,
            "system": INSTRUCTIONS,
            "messages": [{"role": "user", "content": content}],
            # Controle simple : peu de reflexion suffit, et coute moins.
            "output_config": {"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        }
        if model == "haiku":
            # Haiku 4.5 n'accepte pas le reglage d'effort.
            params["output_config"] = {"format": {"type": "json_schema", "schema": SCHEMA}}
        else:
            # Si le modele refuse la demande, l'API la relance d'elle-meme
            # sur le modele de secours recommande.
            params["betas"] = ["server-side-fallback-2026-07-01"]
            params["fallbacks"] = "default"
        try:
            with self._client.beta.messages.stream(**params) as stream:
                response = stream.get_final_message()
        except Exception as exc:  # noqa: BLE001 - toute erreur de l'appel (cle absente, reseau...) en message clair
            raise InspectionError(f"L'appel à l'IA a échoué : {exc}") from exc
        cost = _cost(response.model or spec["id"], response.usage)
        if response.stop_reason == "refusal":
            raise InspectionError("L'IA a refusé de vérifier ce dossier.", cost)
        text = next((block.text for block in response.content if block.type == "text"), "")
        try:
            results = json.loads(text)
        except json.JSONDecodeError as exc:
            raise InspectionError("Réponse de l'IA illisible.", cost) from exc
        return Verdict(results=results, cost=cost)


def _age(birth: str | None, today: date) -> int | None:
    match = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", (birth or "").strip())
    if not match:
        return None
    day, month, year = (int(part) for part in match.groups())
    try:
        born = date(year, month, day)
    except ValueError:
        return None
    age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    return age if 0 <= age <= 110 else None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class MemberChecks:
    def __init__(
        self,
        db: Database,
        members: Callable[[], list[dict]],
        member: Callable[[int], dict | None],
        document: Callable[[str], tuple[bytes, str]],
        model: str = "sonnet",
        inspector: Inspector | None = None,
        notify: Callable[[dict, list[str]], None] | None = None,
        add_cost: Callable[[float], object] | None = None,
        today: Callable[[], date] = date.today,
        background: bool = True,
    ) -> None:
        """members : adherents de la campagne (HelloAsso.get_members) ;
        member : fiche complete d'un adherent (get_member_detail) ; document :
        fichier depose (get_document) ; notify(fiche, raisons) : previent
        l'association d'un nouvel adherent a probleme (mail) ; add_cost(euros) :
        ajoute le cout de chaque appel a l'IA au cout IA de la saison en
        cours (Seasons.add_current_ai_cost) ;
        background=False : verification executee directement (tests)."""
        self.db = db
        self.members = members
        self.member = member
        self.document = document
        self.model = model if model in MODELS else "sonnet"
        self.inspector = inspector or Inspector()
        self.notify = notify
        self.add_cost = add_cost
        self.today = today
        self.background = background
        self._lock = threading.Lock()
        # Avancement de la verification en cours ou de la derniere.
        self._run: dict = {"running": False, "items": [], "startedAt": None, "finishedAt": None}

    # ----- lecture -----

    def state(self) -> dict:
        """Tout ce que l'ecran affiche : {"checks": {identifiant: {"status",
        "issues", "manual", "checkedAt"}}, "totalCost" (euros, cumul de tous
        les appels a l'IA), "modelLabel", "run" (avancement)}."""
        with self.db.connect() as connection:
            rows = connection.execute("SELECT * FROM member_checks").fetchall()
        with self._lock:
            run = {**self._run, "items": [dict(item) for item in self._run["items"]]}
        return {
            "checks": {
                row["member_id"]: {
                    "status": row["status"],
                    "issues": json.loads(row["issues"]),
                    "manual": bool(row["manual"]),
                    "checkedAt": row["checked_at"],
                }
                for row in rows
            },
            "totalCost": sum(row["cost"] for row in rows),
            "modelLabel": MODELS[self.model]["label"],
            "run": run,
        }

    def _status(self, member_id: int) -> str | None:
        with self.db.connect() as connection:
            row = connection.execute("SELECT status FROM member_checks WHERE member_id = ?", (member_id,)).fetchone()
        return row["status"] if row else None

    # ----- verification d'un adherent -----

    def check(self, member_id: int) -> dict:
        """Verifie un adherent et enregistre le resultat. Retourne {"status",
        "issues", "firstName", "lastName"}."""
        detail = self.member(member_id)
        if detail is None:
            raise LookupError(member_id)
        today = self.today()
        fields = detail.get("fields", [])
        answers = {f["name"]: f.get("answer") for f in fields if f.get("type") != "File"}
        files = {
            key: next((f["answer"] for f in fields if f.get("type") == "File" and f.get("answer") and pattern.search(f.get("name") or "")), None)
            for key, (_, pattern) in DOCUMENTS.items()
        }
        issues: list[str] = []
        age = _age(next((value for name, value in answers.items() if "naissance" in (name or "").lower()), None), today)
        if age is None:
            issues.append("Date de naissance absente ou illisible")
        if files["photo"] is None:
            issues.append("Photo d'identité manquante")
        if files["certificat"] is None:
            issues.append("Certificat médical manquant")
        if age is not None and age < ADULT_AGE and files["autorisation"] is None:
            issues.append("Autorisation parentale manquante (adhérent mineur)")

        documents: dict[str, list[bytes]] = {}
        for key, url in files.items():
            # L'autorisation parentale d'un majeur n'a pas a etre controlee.
            if url is None or (key == "autorisation" and age is not None and age >= ADULT_AGE):
                continue
            try:
                documents[key] = to_images(self.document(url)[0])
            except ValueError as exc:
                issues.append(f"{DOCUMENTS[key][0]} : {exc}")
            except Exception as exc:  # noqa: BLE001 - HelloAsso injoignable pour ce fichier
                issues.append(f"{DOCUMENTS[key][0]} : fichier indisponible ({exc})")

        cost, status = 0.0, None
        if documents:
            identity = {
                "prenom": detail.get("firstName"),
                "nom": detail.get("lastName"),
                "age": age,
                "inscritLe": (detail.get("orderDate") or "")[:10],
                "payeur": " ".join(part for part in (detail["payer"].get("firstName"), detail["payer"].get("lastName")) if part),
                "reponses": answers,
            }
            try:
                verdict = self.inspector.inspect(self.model, identity, documents, today)
                cost = verdict.cost
                labels = {**{key: label for key, (label, _) in DOCUMENTS.items()}, DATA: "Réponses au formulaire"}
                for key, label in labels.items():
                    result = verdict.results.get(key) or {}
                    if key != DATA and key not in documents:
                        continue
                    if result.get("ok") is False:
                        issues.append(f"{label} : {(result.get('raison') or 'à vérifier').strip()}")
            except InspectionError as exc:
                cost, status = exc.cost, ERROR
                issues.append(str(exc))
        status = status or (PROBLEM if issues else OK)
        if cost and self.add_cost is not None:
            self.add_cost(cost)
        with self.db.connect() as connection:
            connection.execute(
                """INSERT INTO member_checks (member_id, first_name, last_name, status, issues, manual, model, cost, checked_at)
                   VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?)
                   ON CONFLICT (member_id) DO UPDATE SET first_name = excluded.first_name, last_name = excluded.last_name,
                   status = excluded.status, issues = excluded.issues, manual = 0, model = excluded.model,
                   cost = member_checks.cost + excluded.cost, checked_at = excluded.checked_at""",
                (
                    member_id,
                    detail.get("firstName") or "",
                    detail.get("lastName") or "",
                    status,
                    json.dumps(issues, ensure_ascii=False),
                    self.model,
                    cost,
                    _now(),
                ),
            )
        return {"status": status, "issues": issues, "firstName": detail.get("firstName"), "lastName": detail.get("lastName")}

    def mark_ok(self, member_id: int) -> None:
        """Dossier valide a la main (l'IA s'est trompee, ou le probleme a ete
        regle hors de HelloAsso) : il ne sera plus reverifie."""
        detail = self.member(member_id)
        if detail is None:
            raise LookupError(member_id)
        with self.db.connect() as connection:
            connection.execute(
                """INSERT INTO member_checks (member_id, first_name, last_name, status, issues, manual, model, cost, checked_at)
                   VALUES (?, ?, ?, 'ok', '[]', 1, NULL, 0, ?)
                   ON CONFLICT (member_id) DO UPDATE SET status = 'ok', issues = '[]', manual = 1, checked_at = excluded.checked_at""",
                (member_id, detail.get("firstName") or "", detail.get("lastName") or "", _now()),
            )

    def check_new_member(self, member_id: int) -> dict:
        """Nouvel adherent (voir la boucle de detection d'app/main.py) : son
        dossier est verifie tout de suite, et l'association est prevenue par
        mail s'il y a un probleme."""
        result = self.check(member_id)
        if result["status"] != OK and self.notify is not None:
            self.notify(self.member(member_id), result["issues"])
        return result

    # ----- verification de tous les adherents -----

    def run(self) -> dict:
        """Lance la verification de tous les adherents dont le dossier n'est
        pas deja bon (en arriere-plan). Retourne l'avancement."""
        with self._lock:
            if self._run["running"]:
                raise RuntimeError("Une vérification est déjà en cours")
            members = [m for m in self.members() if m.get("state") not in CANCELED_ITEM_STATES and m.get("id") is not None]
            items = []
            for m in members:
                already = self._status(m["id"]) == OK
                items.append(
                    {
                        "memberId": m["id"],
                        "name": f"{m.get('firstName') or ''} {m.get('lastName') or ''}".strip(),
                        # "deja" : dossier deja bon, pas de nouvel appel a l'IA.
                        "state": "deja" if already else "attente",
                        "issues": [],
                    }
                )
            self._run = {"running": True, "items": items, "startedAt": _now(), "finishedAt": None}
        if self.background:
            threading.Thread(target=self._execute, daemon=True).start()
        else:
            self._execute()
        return self.state()["run"]

    def _execute(self) -> None:
        try:
            for index in range(len(self._run["items"])):
                with self._lock:
                    item = self._run["items"][index]
                    if item["state"] != "attente":
                        continue
                    item["state"] = "encours"
                try:
                    result = self.check(item["memberId"])
                    state, issues = result["status"], result["issues"]
                except Exception as exc:  # noqa: BLE001 - un adherent en echec n'arrete pas les autres
                    state, issues = ERROR, [f"Vérification impossible : {exc}"]
                with self._lock:
                    item["state"], item["issues"] = state, issues
        finally:
            with self._lock:
                self._run["running"] = False
                self._run["finishedAt"] = _now()
