"""Appel a l'IA (API Claude d'Anthropic) pour un previsionnel : l'IA ne
calcule pas le resultat, elle ecrit une formule Python (fonction
prevoir(donnees, p)) et declare ses parametres reglables (curseurs de
l'ecran), d'apres le prompt du tresorier.

Memes modeles, tarifs et cle d'API que les bilans (voir financialreports/ai.py).
La formule est verifiee puis executee par l'appli (voir sandbox.py) : en cas
d'echec, l'IA recoit l'erreur et corrige sa formule (une fois).
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import anthropic

from financialreports.ai import DEFAULT_MODEL, MODELS, AnalysisError, _cost

from .sandbox import FormulaError, run

INSTRUCTIONS = """Tu es le trésorier bénévole d'un club de sambo, l'association Alliance Sambo Combat La Ciotat.
Tu prépares un prévisionnel : le solde des comptes du club (compte courant + Livret Bleu cumulés) chaque semaine, de la date de départ jusqu'à la fin de la saison sportive (du 1er juillet au 30 juin).

Tu ne calcules pas toi-même le résultat : tu écris une formule en Python que l'application exécute, puis rejoue à chaque fois que le trésorier bouge un curseur.

La formule :
- définit une fonction prevoir(donnees, p) qui renvoie une liste avec une valeur par élément de donnees["semaines"], dans le même ordre : le solde prévu (en euros) à la date de cette semaine, sous la forme {"date": ..., "solde": ...} ;
- part de donnees["soldeDepart"] (solde réel à la date de départ) ;
- lit les paramètres réglables dans le dictionnaire p (clés déclarées dans "parametres") ;
- n'utilise que Python standard : seuls les modules math et datetime peuvent être importés ; pas de fichier, pas de réseau, pas de print, pas de nom commençant par « _ » ;
- reste simple et lisible par un trésorier : des commentaires en français, pas d'astuce.

Les données (dictionnaire donnees, montants en euros, recettes positives, dépenses négatives, virements entre les comptes du club exclus) :
- saison, debutSaison, finSaison, dateDepart (AAAA-MM-JJ), soldeDepart, soldeDebutSaison ;
- semaines : [{"date", "mois_commences"}] ; mois_commences : les mois ("AAAA-MM") dont le 1er jour tombe dans la semaine, utile pour les dépenses mensuelles ;
- moisEnCours : {"mois", "dejaPasseParCategorie"} : ce qui est déjà passé sur le mois de la date de départ (pour ne pas compter deux fois un salaire déjà payé) ;
- moyennesMensuelles : moyenne par mois, par catégorie, des 12 mois avant la date de départ ;
- douzeDerniersMois : [{"mois", "parCategorie"}] : le détail de ces 12 mois (saisonnalité : inscriptions en septembre-octobre, etc.) ;
- adherents : null, ou {"nombre", "majeurs", "mineurs", "prixMoyenAdhesion", "totalAdhesions", "echeancesAVenir": {"AAAA-MM": montant}, "impayes"} : adhérents HelloAsso de la campagne en cours et échéances des paiements en plusieurs fois pas encore encaissées (les cotisations arrivent sur le compte sous la catégorie « Cotisations en ligne »).

Paramètres : déclare dans "parametres" chaque paramètre que le prompt du trésorier rend réglable (nom de clé Python, libellé court en français, min, max, défaut, pas, unité). Respecte les bornes et défauts du prompt. S'il n'en demande aucun, propose 2 ou 3 paramètres utiles.

Explication : 3 à 6 phrases en français simple qui disent ce que fait la formule, poste par poste, pour que le trésorier vérifie que tu as compris sa demande. Si des données manquent (adherents null...), dis comment tu as fait sans.
"""

SCHEMA = {
    "type": "object",
    "properties": {
        "code": {"type": "string", "description": "Code Python complet définissant prevoir(donnees, p)."},
        "explication": {"type": "string"},
        "parametres": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "nom": {"type": "string", "description": "Clé dans p (identifiant Python)."},
                    "libelle": {"type": "string"},
                    "min": {"type": "number"},
                    "max": {"type": "number"},
                    "defaut": {"type": "number"},
                    "pas": {"type": "number"},
                    "unite": {"type": "string", "description": "« € », « % », « adhérents »… ou vide."},
                },
                "required": ["nom", "libelle", "min", "max", "defaut", "pas", "unite"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["code", "explication", "parametres"],
    "additionalProperties": False,
}


@dataclass
class Formula:
    code: str
    explanation: str
    parameters: list[dict]  # [{"name", "label", "min", "max", "default", "step", "unit"}]
    balances: list[float]  # resultat avec les valeurs par defaut
    model: str  # cle de MODELS
    served_by: str
    cost: float  # euros, toutes les tentatives


def defaults(parameters: list[dict]) -> dict:
    return {p["name"]: p["default"] for p in parameters}


def _parameters(raw: list[dict]) -> list[dict]:
    """Parametres declares par l'IA, controles (identifiant, bornes)."""
    result = []
    for p in raw:
        name = str(p.get("nom", "")).strip()
        if not name.isidentifier() or name.startswith("_") or any(r["name"] == name for r in result):
            raise FormulaError(f"Nom de paramètre invalide : {name!r}")
        low, high = float(p["min"]), float(p["max"])
        if low > high:
            low, high = high, low
        step = abs(float(p.get("pas") or 0)) or (high - low) / 100 or 1
        default = min(high, max(low, float(p["defaut"])))
        result.append(
            {
                "name": name,
                "label": str(p.get("libelle") or name).strip(),
                "min": low,
                "max": high,
                "default": default,
                "step": step,
                "unit": str(p.get("unite") or "").strip(),
            }
        )
    return result


class Coder:
    # Tentatives : la 2e recoit l'erreur de la 1re pour corriger la formule.
    ATTEMPTS = 2

    def __init__(self) -> None:
        self._client: anthropic.Anthropic | None = None

    def _anthropic(self) -> anthropic.Anthropic:
        if self._client is None:
            self._client = anthropic.Anthropic()
        return self._client

    def write(self, model: str, data: dict, prompt: str) -> Formula:
        """data : donnees de la formule (voir data.build) ; prompt : consignes
        du tresorier. La formule rendue a ete verifiee et executee avec les
        valeurs par defaut de ses parametres."""
        if model not in MODELS:
            raise AnalysisError(f"Modèle inconnu : {model}")
        spec = MODELS[model]
        text = "Données (JSON) :\n" + json.dumps(data, ensure_ascii=False, indent=1)
        text += "\n\nDemande du trésorier pour ce prévisionnel :\n" + (prompt.strip() or "(aucune consigne particulière)")
        messages: list[dict] = [{"role": "user", "content": text}]
        cost = 0.0
        for attempt in range(self.ATTEMPTS):
            try:
                response = self._call(spec, model, messages)
            except AnalysisError as exc:
                exc.cost += cost  # la 1re tentative a ete facturee
                raise
            cost +=_cost(response.model or spec["id"], response.usage)
            if response.stop_reason == "refusal":
                raise AnalysisError("L'IA a refusé d'écrire ce prévisionnel.", cost)
            if response.stop_reason == "max_tokens":
                raise AnalysisError("Réponse de l'IA incomplète (trop longue).", cost)
            answer = next((b.text for b in response.content if b.type == "text"), "")
            try:
                result = json.loads(answer)
                parameters = _parameters(result.get("parametres", []))
                code = result["code"]
                balances = run(code, data, defaults(parameters))
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                problem = str(exc) if isinstance(exc, FormulaError) else f"Réponse illisible : {exc}"
                if attempt + 1 == self.ATTEMPTS:
                    raise AnalysisError(f"La formule de l'IA ne fonctionne pas : {problem}", cost) from exc
                messages += [
                    {"role": "assistant", "content": answer},
                    {"role": "user", "content": f"Ta formule a été refusée ou a échoué : {problem}\nCorrige-la et renvoie la réponse complète."},
                ]
                continue
            return Formula(
                code=code,
                explanation=str(result.get("explication", "")).strip(),
                parameters=parameters,
                balances=balances,
                model=model,
                served_by=response.model or spec["id"],
                cost=cost,
            )
        raise AnalysisError("La formule de l'IA ne fonctionne pas.", cost)  # pragma: no cover

    def _call(self, spec: dict, model: str, messages: list[dict]):
        params = {
            "model": spec["id"],
            "max_tokens": 32000,
            "system": INSTRUCTIONS,
            "messages": messages,
            "output_config": {"format": {"type": "json_schema", "schema": SCHEMA}},
        }
        if model != "haiku":
            # Comme pour les bilans : si le modele refuse, l'API relance la
            # demande sur le modele de secours recommande.
            params["betas"] = ["server-side-fallback-2026-07-01"]
            params["fallbacks"] = "default"
        try:
            with self._anthropic().beta.messages.stream(**params) as stream:
                return stream.get_final_message()
        except Exception as exc:  # noqa: BLE001 - toute erreur de l'appel en message clair
            raise AnalysisError(f"L'appel à l'IA a échoué : {exc}") from exc


__all__ = ["Coder", "Formula", "defaults", "DEFAULT_MODEL", "MODELS"]
