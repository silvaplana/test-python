"""Appel a l'IA (API Claude d'Anthropic, comme l'ancien bilan de l'onglet
Deprecated, voir financialbalance/) pour un bilan financier.

L'IA ne calcule rien : le tableau est calcule au centime par l'appli (voir
report.py). Elle recoit les chiffres de la saison et des saisons
precedentes et :
- classe les operations de la categorie "Autres" (categorie existante ou
  nouvelle) ;
- ecrit l'analyse de 5 lignes (faits marquants et comparaisons).

Cle d'API : variable d'environnement ANTHROPIC_API_KEY (lue par le SDK).
Cout : facture en dollars par l'API, converti en euros au taux AI_USD_TO_EUR.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

import anthropic

# Modeles proposes dans l'ecran. Prix en dollars par million de jetons
# (tarifs publics de l'API Anthropic).
MODELS: dict[str, dict] = {
    "haiku": {"id": "claude-haiku-4-5", "label": "Claude Haiku 4.5", "input": 1.0, "output": 5.0},
    "sonnet": {"id": "claude-sonnet-5-5", "label": "Claude Sonnet 5.5", "input": 2.0, "output": 10.0},
    "fable": {"id": "claude-fable-5-1", "label": "Claude Fable 5.1", "input": 10.0, "output": 50.0},
}
DEFAULT_MODEL = "sonnet"

# Modeles qui peuvent prendre le relais quand le modele choisi refuse une
# demande (voir fallbacks plus bas) : pour calculer le cout au bon tarif.
_OTHER_PRICES = {
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
}

# Taux de conversion dollar -> euro du cout de l'IA (a ajuster de temps en
# temps : le cout n'est qu'indicatif).
USD_TO_EUR = float(os.environ.get("AI_USD_TO_EUR", "0.86"))

# Consignes fixes, completees par le prompt saisi dans l'ecran.
INSTRUCTIONS = """Tu es le trésorier bénévole d'un club de sambo, l'association Alliance Sambo Combat La Ciotat.
On te donne le compte d'exploitation d'une saison sportive (du 1er juillet au 30 juin), calculé par l'application à partir des relevés de banque (compte courant + Livret Bleu), ainsi que les chiffres des saisons précédentes (soldes, licenciés, recettes et dépenses par catégorie).

Les chiffres fournis sont exacts au centime : ne recalcule aucun total et n'invente aucun chiffre.

Ta mission :
1. Classer chacune des opérations de la catégorie « Autres » (liste "operationsAClasser") : choisis une des catégories existantes si elle convient, sinon crée une catégorie courte et claire (par exemple « Réception AG »). Laisse « Autres » si rien ne convient vraiment.
2. Écrire une analyse en 5 lignes au plus (une phrase courte par ligne), en français simple, sans jargon comptable, avec des montants arrondis à l'euro :
   - les faits marquants de la saison ;
   - la comparaison avec les saisons précédentes : solde des comptes, nombre de licenciés, principaux postes de recettes et de dépenses.
   Tiens compte de ton classement des opérations « Autres ». Si la saison n'est pas terminée (date d'arrêt avant la fin de saison), dis-le.
"""

SCHEMA = {
    "type": "object",
    "properties": {
        "classifications": {
            "type": "array",
            "description": "Une entrée par opération de la liste operationsAClasser.",
            "items": {
                "type": "object",
                "properties": {
                    "operationId": {"type": "integer"},
                    "category": {"type": "string"},
                },
                "required": ["operationId", "category"],
                "additionalProperties": False,
            },
        },
        "analysis": {
            "type": "array",
            "description": "Analyse : 5 lignes au plus, une phrase par ligne.",
            "items": {"type": "string"},
        },
    },
    "required": ["classifications", "analysis"],
    "additionalProperties": False,
}


class AnalysisError(Exception):
    """Echec de l'appel a l'IA (cle absente, reseau, refus...) : message
    affichable tel quel. cost : ce que l'appel a quand meme coute (euros)."""

    def __init__(self, message: str, cost: float = 0.0) -> None:
        super().__init__(message)
        self.cost = cost


@dataclass
class Analysis:
    classifications: dict[int, str]
    analysis: list[str]
    model: str  # cle de MODELS
    served_by: str  # identifiant du modele qui a vraiment repondu
    cost: float  # euros


def _cost(model_id: str, usage) -> float:
    if model_id in _OTHER_PRICES:
        input_price, output_price = _OTHER_PRICES[model_id]
    else:
        spec = next((m for m in MODELS.values() if model_id.startswith(m["id"])), MODELS[DEFAULT_MODEL])
        input_price, output_price = spec["input"], spec["output"]
    input_tokens = (
        (usage.input_tokens or 0)
        + 1.25 * (getattr(usage, "cache_creation_input_tokens", 0) or 0)
        + 0.1 * (getattr(usage, "cache_read_input_tokens", 0) or 0)
    )
    dollars = (input_tokens * input_price + (usage.output_tokens or 0) * output_price) / 1_000_000
    return dollars * USD_TO_EUR


class Analyst:
    def __init__(self) -> None:
        self._client: anthropic.Anthropic | None = None

    def _anthropic(self) -> anthropic.Anthropic:
        if self._client is None:
            self._client = anthropic.Anthropic()
        return self._client

    def analyze(self, model: str, data: dict, prompt: str) -> Analysis:
        """data : chiffres envoyes a l'IA (voir FinancialReports._ai_data) ;
        prompt : consignes saisies dans l'ecran (peut etre vide)."""
        if model not in MODELS:
            raise AnalysisError(f"Modèle inconnu : {model}")
        spec = MODELS[model]
        text = "Données de la saison (JSON) :\n" + json.dumps(data, ensure_ascii=False, indent=1)
        if prompt.strip():
            text += "\n\nConsignes du trésorier pour ce bilan :\n" + prompt.strip()
        params = {
            "model": spec["id"],
            "max_tokens": 32000,
            "system": INSTRUCTIONS,
            "messages": [{"role": "user", "content": text}],
            "output_config": {"format": {"type": "json_schema", "schema": SCHEMA}},
        }
        if model != "haiku":
            # Si le modele refuse la demande (filtres de securite), l'API
            # la relance d'elle-meme sur le modele de secours recommande.
            params["betas"] = ["server-side-fallback-2026-07-01"]
            params["fallbacks"] = "default"
        try:
            with self._anthropic().beta.messages.stream(**params) as stream:
                response = stream.get_final_message()
        except Exception as exc:  # noqa: BLE001 - toute erreur de l'appel (cle absente, reseau...) en message clair
            raise AnalysisError(f"L'appel à l'IA a échoué : {exc}") from exc

        cost = _cost(response.model or spec["id"], response.usage)
        if response.stop_reason == "refusal":
            raise AnalysisError("L'IA a refusé de faire ce bilan.", cost)
        if response.stop_reason == "max_tokens":
            raise AnalysisError("Réponse de l'IA incomplète (trop longue).", cost)
        text_block = next((b.text for b in response.content if b.type == "text"), None)
        try:
            result = json.loads(text_block or "")
        except json.JSONDecodeError as exc:
            raise AnalysisError("Réponse de l'IA illisible.", cost) from exc
        return Analysis(
            classifications={
                int(c["operationId"]): c["category"].strip()
                for c in result.get("classifications", [])
                if c.get("category", "").strip()
            },
            analysis=[line.strip() for line in result.get("analysis", []) if line.strip()][:5],
            model=model,
            served_by=response.model or spec["id"],
            cost=cost,
        )
