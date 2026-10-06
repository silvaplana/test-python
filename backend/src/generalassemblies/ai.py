"""Appel a l'IA (API Claude, comme le bilan financier : voir
financialreports/ai.py, dont on reprend les modeles et le calcul du cout)
pour ecrire la base du PowerPoint d'une assemblee generale.

L'IA recoit le plan du PPT modele (zones de texte de chaque diapo), les
chiffres du bilan financier de la saison et l'historique des licencies.
Elle reecrit les parties du tresorier (rapport d'activites, bilan
financier, recettes, depenses, resultat, budget previsionnel), met les
annees de saison a jour et marque "À compléter" ce qu'elle ne sait pas.
L'appli place ensuite ce texte dans le PPT (voir slides.fill).
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import anthropic

from financialreports.ai import DEFAULT_MODEL, MODELS, AnalysisError, _cost

from .slides import TO_COMPLETE

INSTRUCTIONS = f"""Tu es le trésorier bénévole d'un club de sambo, l'association Alliance Sambo Combat La Ciotat.
Tu prépares la base du PowerPoint de l'assemblée générale (AG) d'une saison sportive (du 1er juillet au 30 juin).

On te donne :
- "modele" : le plan du PowerPoint de l'AG précédente, diapo par diapo. Chaque diapo a des zones de texte (identifiant "zone", rôle "titre" ou "texte") et leurs paragraphes avec leur niveau de puce (0 = puce principale, 1 = sous-puce...). "\\n" est un retour à la ligne dans un paragraphe.
- "bilan" : le bilan financier de la saison, calculé par l'application au centime à partir des relevés de banque (compte courant + Livret Bleu), avec son analyse et la saison précédente pour comparer.
- "licencies" : le nombre de licenciés par saison.

Ta mission : réécrire pour la saison demandée les zones qui doivent changer, en gardant le style du modèle (phrases courtes, mêmes niveaux de puces, à peu près le même nombre de lignes pour que le texte tienne sur la diapo).
1. Parties du trésorier, à remplir avec les données : rapport d'activités (licenciés de la saison et des saisons précédentes), bilan financier (période des comptes), résumé exécutif (résultat, soldes de début et de fin), recettes (vue globale et analyse par rapport à la saison précédente), dépenses (vue globale et analyse), résultat global, budget prévisionnel de la saison suivante.
2. Années : remplace partout les saisons et années de l'AG précédente par celles de la saison demandée (titres compris, par exemple « Projets 2026-2027 » devient « Projets 2027-2028 » pour la saison 2026-2027).
3. Autres diapos (accueil, bureau, projets, objectifs, renouvellement, questions, clôture) : ne les change pas, sauf les années, et sauf un contenu qui ne vaut que pour l'AG précédente (noms, démissions, dates, événements passés) : remplace-le par « {TO_COMPLETE} ».

Règles :
- Les montants viennent uniquement des données fournies, arrondis à l'euro (ex : « 15 718 € »). N'additionne et ne soustrais aucun montant toi-même : cite ceux qui sont fournis. N'invente aucun chiffre.
- Ce que les données ne disent pas (date de l'AG, nom du trésorier, prix de la cotisation, subventions non visibles en banque, budget prévisionnel chiffré, explications des variations...) : écris exactement « {TO_COMPLETE} » à la place de l'information.
- Une recette ou une dépense exceptionnelle (qui ne se reproduira pas) doit être signalée comme telle.
- Si la saison n'est pas terminée (date d'arrêt avant la fin de saison), dis que les comptes sont arrêtés à cette date.
- Ne renvoie que les zones que tu modifies, avec tous leurs paragraphes (le texte complet de la zone). Ne modifie pas les diapos masquées.
- "resume" : 3 lignes au plus pour le trésorier : ce que tu as rempli et ce qui reste à compléter.
"""

SCHEMA = {
    "type": "object",
    "properties": {
        "zones": {
            "type": "array",
            "description": "Zones de texte modifiées, avec leur texte complet.",
            "items": {
                "type": "object",
                "properties": {
                    "diapo": {"type": "integer"},
                    "zone": {"type": "integer"},
                    "paragraphes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"niveau": {"type": "integer"}, "texte": {"type": "string"}},
                            "required": ["niveau", "texte"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["diapo", "zone", "paragraphes"],
                "additionalProperties": False,
            },
        },
        "resume": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["zones", "resume"],
    "additionalProperties": False,
}


@dataclass
class Draft:
    zones: list[dict]
    summary: list[str]
    model: str  # cle de MODELS
    served_by: str
    cost: float  # euros


class Writer:
    def __init__(self) -> None:
        self._client: anthropic.Anthropic | None = None

    def _anthropic(self) -> anthropic.Anthropic:
        if self._client is None:
            self._client = anthropic.Anthropic()
        return self._client

    def write(self, model: str, data: dict, prompt: str) -> Draft:
        """data : plan du modele et chiffres (voir GeneralAssemblies._ai_data) ;
        prompt : consignes saisies dans l'ecran (peut etre vide)."""
        if model not in MODELS:
            raise AnalysisError(f"Modèle inconnu : {model}")
        spec = MODELS[model]
        text = "Données (JSON) :\n" + json.dumps(data, ensure_ascii=False, indent=1)
        if prompt.strip():
            text += "\n\nConsignes du trésorier pour cette AG :\n" + prompt.strip()
        params = {
            "model": spec["id"],
            "max_tokens": 32000,
            "system": INSTRUCTIONS,
            "messages": [{"role": "user", "content": text}],
            "output_config": {"format": {"type": "json_schema", "schema": SCHEMA}},
        }
        if model != "haiku":
            # Comme le bilan : si le modele refuse, l'API relance la demande
            # sur le modele de secours recommande.
            params["betas"] = ["server-side-fallback-2026-07-01"]
            params["fallbacks"] = "default"
        try:
            with self._anthropic().beta.messages.stream(**params) as stream:
                response = stream.get_final_message()
        except Exception as exc:  # noqa: BLE001 - toute erreur de l'appel en message clair
            raise AnalysisError(f"L'appel à l'IA a échoué : {exc}") from exc

        cost = _cost(response.model or spec["id"], response.usage)
        if response.stop_reason == "refusal":
            raise AnalysisError("L'IA a refusé de préparer cette AG.", cost)
        if response.stop_reason == "max_tokens":
            raise AnalysisError("Réponse de l'IA incomplète (trop longue).", cost)
        text_block = next((b.text for b in response.content if b.type == "text"), None)
        try:
            result = json.loads(text_block or "")
        except json.JSONDecodeError as exc:
            raise AnalysisError("Réponse de l'IA illisible.", cost) from exc
        return Draft(
            zones=[z for z in result.get("zones", []) if isinstance(z, dict)],
            summary=[line.strip() for line in result.get("resume", []) if line.strip()][:3],
            model=model,
            served_by=response.model or spec["id"],
            cost=cost,
        )


__all__ = ["DEFAULT_MODEL", "MODELS", "AnalysisError", "Draft", "Writer"]
