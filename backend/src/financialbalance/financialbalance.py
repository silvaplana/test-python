"""Bilan financier du club.

Reception et stockage de l'archive zip des releves bancaires (compte
courant + Livret bleu) envoyee depuis le frontend, puis analyse du
contenu via l'API Claude (Anthropic) : resume synthetique + ventilation
des recettes/depenses par categorie.
"""

from __future__ import annotations

import base64
import json
import zipfile
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

import anthropic

# Modele utilise pour l'analyse : le plus capable, adapte a un travail de
# categorisation/synthese sur plusieurs documents financiers.
MODEL = "claude-opus-5"

# Schema impose a la reponse (structured outputs) : garantit un JSON
# exploitable directement par le frontend, sans parsing fragile de texte
# libre. Un compte bancaire par element de "accounts" : les releves
# fournis melangent generalement plusieurs comptes distincts (compte
# courant, Livret bleu, ...), chacun avec sa propre periode et ses propres
# soldes -- les regrouper en un seul bloc global masquerait justement les
# niveaux de compte au debut/a la fin de chaque periode.
_ACCOUNT_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
            "description": "Nom/type du compte tel qu'indique sur les releves (ex: 'Compte courant Connect Asso', 'Livret bleu').",
        },
        "period_start": {
            "type": "string",
            "description": (
                "Date exacte du premier solde/mouvement trouve pour ce "
                "compte, au format JJ/MM/AAAA. Jamais un mois seul (ex: "
                "'juin 2025') -- toujours le jour precis."
            ),
        },
        "period_end": {
            "type": "string",
            "description": (
                "Date exacte du dernier solde/mouvement trouve pour ce "
                "compte, au format JJ/MM/AAAA. Jamais un mois seul."
            ),
        },
        "opening_balance": {
            "type": "number",
            "description": "Solde exact de ce compte au debut de la periode (period_start), en euros, au centime pres.",
        },
        "closing_balance": {
            "type": "number",
            "description": "Solde exact de ce compte a la fin de la periode (period_end), en euros, au centime pres.",
        },
        "total_income": {
            "type": "number",
            "description": (
                "Total exact des recettes de ce compte sur la periode, en "
                "euros, au centime pres (ne jamais arrondir a l'euro). "
                "Doit etre coherent avec opening_balance + total_income - "
                "total_expense = closing_balance."
            ),
        },
        "total_expense": {
            "type": "number",
            "description": (
                "Total exact des depenses de ce compte sur la periode, en "
                "euros, au centime pres (ne jamais arrondir a l'euro)."
            ),
        },
        "categories": {
            "type": "array",
            "description": (
                "Ventilation des recettes et depenses de ce compte par "
                "categorie (salaires, cotisations sociales, licences "
                "federales, mutuelle, cotisations HelloAsso/adherents, "
                "frais bancaires, materiel, subventions, virements internes "
                "vers/depuis un autre compte, etc.). La somme des montants "
                "de toutes les categories doit correspondre exactement a "
                "total_income et total_expense de ce compte."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "category": {"type": "string"},
                    "income": {
                        "type": "number",
                        "description": "Total exact des recettes pour cette categorie, en euros, au centime pres (0 si aucune).",
                    },
                    "expense": {
                        "type": "number",
                        "description": "Total exact des depenses pour cette categorie, en euros, au centime pres (0 si aucune).",
                    },
                },
                "required": ["category", "income", "expense"],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "name",
        "period_start",
        "period_end",
        "opening_balance",
        "closing_balance",
        "total_income",
        "total_expense",
        "categories",
    ],
    "additionalProperties": False,
}

# Vue consolidee : "3eme categorie" en plus des comptes individuels,
# combinant tous les comptes ensemble. Champ separe (pas juste la somme
# brute des comptes) car les virements internes entre comptes doivent y
# etre neutralises (comptes une seule fois) pour ne pas gonfler
# artificiellement les recettes ET les depenses du meme montant.
_CONSOLIDATED_SCHEMA = {
    "type": "object",
    "properties": {
        "opening_balance": {
            "type": "number",
            "description": (
                "Somme des soldes de tous les comptes a leur date de debut "
                "de periode respective, en euros, au centime pres."
            ),
        },
        "closing_balance": {
            "type": "number",
            "description": (
                "Somme des soldes de tous les comptes a leur date de fin "
                "de periode respective, en euros, au centime pres."
            ),
        },
        "total_income": {
            "type": "number",
            "description": (
                "Total des recettes de tous les comptes cumules, en euros, "
                "au centime pres, en ne comptant qu'UNE SEULE FOIS chaque "
                "virement interne entre ces comptes (jamais a la fois comme "
                "recette d'un compte et depense de l'autre)."
            ),
        },
        "total_expense": {
            "type": "number",
            "description": (
                "Total des depenses de tous les comptes cumules, en euros, "
                "au centime pres, avec la meme neutralisation des virements "
                "internes que total_income."
            ),
        },
        "categories": {
            "type": "array",
            "description": (
                "Ventilation consolidee par categorie, tous comptes "
                "confondus (categories fusionnees si elles existent sur "
                "plusieurs comptes), SANS les virements internes entre "
                "comptes de l'association (ils s'annulent et ne doivent "
                "plus apparaitre ici)."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "category": {"type": "string"},
                    "income": {
                        "type": "number",
                        "description": "Total exact des recettes pour cette categorie, tous comptes confondus, au centime pres (0 si aucune).",
                    },
                    "expense": {
                        "type": "number",
                        "description": "Total exact des depenses pour cette categorie, tous comptes confondus, au centime pres (0 si aucune).",
                    },
                },
                "required": ["category", "income", "expense"],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "opening_balance",
        "closing_balance",
        "total_income",
        "total_expense",
        "categories",
    ],
    "additionalProperties": False,
}

ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": (
                "Resume synthetique du bilan financier, en francais, sur "
                "plusieurs paragraphes : entrees/sorties, tendance, points "
                "d'attention, vue d'ensemble sur tous les comptes. Cite les "
                "periodes et les soldes avec des valeurs precises (dates "
                "JJ/MM/AAAA, montants au centime pres), jamais de noms de "
                "mois seuls ni de montants arrondis a l'euro."
            ),
        },
        "accounts": {
            "type": "array",
            "description": "Un element par compte bancaire distinct identifiable dans les releves fournis.",
            "items": _ACCOUNT_SCHEMA,
        },
        "consolidated": {
            **_CONSOLIDATED_SCHEMA,
            "description": (
                "Vue consolidee combinant TOUS les comptes ensemble "
                "(troisieme vue, en plus de chaque compte pris "
                "individuellement dans 'accounts'), avec les virements "
                "internes entre ces comptes neutralises."
            ),
        },
    },
    "required": ["summary", "accounts", "consolidated"],
    "additionalProperties": False,
}

ANALYSIS_PROMPT = (
    "Voici les releves bancaires (compte courant et/ou Livret bleu) d'une "
    "association sportive. Ces releves peuvent couvrir plusieurs comptes "
    "distincts. Fournis TROIS niveaux d'analyse :\n"
    "1) Pour CHAQUE compte pris individuellement :\n"
    "   - La date de debut et de fin exactes de la periode couverte par "
    "ses releves (jour/mois/annee, jamais seulement un mois ou une "
    "saison).\n"
    "   - Le solde exact au debut de la periode ET le solde exact a la "
    "fin de la periode (les deux niveaux de compte), au centime pres.\n"
    "   - Le total exact des recettes et le total exact des depenses sur "
    "toute la periode, au centime pres -- ne jamais arrondir a l'euro. "
    "Verifie que solde_debut + recettes - depenses = solde_fin, et que la "
    "somme des categories correspond exactement aux totaux.\n"
    "   - Une ventilation des recettes/depenses par categorie, avec des "
    "montants exacts au centime pres. S'il y a un virement entre deux de "
    "ces comptes, indique-le comme une categorie a part sur chacun des "
    "deux comptes concernes (ce n'est pas une vraie recette ou depense "
    "externe, seulement un mouvement entre comptes de la meme "
    "association).\n"
    "2) Une VUE CONSOLIDEE combinant tous les comptes ensemble (voir "
    "'consolidated') : les soldes debut/fin sommes, les totaux "
    "recettes/depenses et la ventilation par categorie, en neutralisant "
    "(comptant une seule fois) tout virement interne entre comptes de "
    "l'association -- il ne doit apparaitre ni dans les totaux ni dans "
    "les categories de la vue consolidee.\n"
    "3) Un resume synthetique global (entrees/sorties, tendance, points "
    "d'attention), qui precise clairement quand un mouvement est un "
    "virement interne entre comptes de l'association plutot qu'une "
    "vraie recette/depense externe. Reponds en francais."
)


class FinancialBalanceAnalysisError(Exception):
    """Levee quand l'analyse IA d'une archive de releves echoue (cle API
    manquante/invalide, erreur reseau, refus du modele, archive vide...)."""


class FinancialBalance:
    """Gere la reception, le stockage et l'analyse IA des archives de
    releves bancaires.

    storage_dir doit pointer vers un repertoire persistant (volume Docker
    monte, voir docker-compose.yml) : sans ca, les archives recues
    seraient perdues au prochain redeploiement (reconstruction de l'image).
    """

    def __init__(self, storage_dir: str = "data/bank_archives") -> None:
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        # Sous-repertoire frere de storage_dir : vit donc dans le meme volume
        # Docker persistant (docker-compose.yml monte tout /app/data, pas
        # seulement bank_archives/), sans configuration supplementaire.
        self.analyses_dir = self.storage_dir.parent / "analyses"
        self.analyses_dir.mkdir(parents=True, exist_ok=True)
        # Cree paresseusement (lit ANTHROPIC_API_KEY dans l'environnement) :
        # pas d'erreur au demarrage du backend si la cle n'est pas encore
        # configuree, tant qu'aucune analyse n'est demandee.
        self._anthropic_client: anthropic.Anthropic | None = None

    def save_bank_account_archive(self, filename: str, content: bytes) -> dict:
        """Enregistre l'archive zip recue sur disque et retourne des infos
        sur le fichier stocke (nom final, taille, date de reception).

        Leve ValueError si le fichier ne semble pas etre une archive zip.
        """
        if not filename.lower().endswith(".zip"):
            raise ValueError("Le fichier envoye doit etre une archive .zip")

        received_at = datetime.now(timezone.utc)
        timestamp = received_at.strftime("%Y%m%dT%H%M%SZ")
        # Path(...).name pour ne garder que le nom de fichier, jamais un
        # chemin (evite tout risque d'ecriture hors de storage_dir).
        safe_name = Path(filename).name
        stored_name = f"{timestamp}_{safe_name}"
        stored_path = self.storage_dir / stored_name
        stored_path.write_bytes(content)

        print(f"FinancialBalance.save_bank_account_archive: {stored_name} ({len(content)} octets)")
        return {
            "filename": stored_name,
            "size": len(content),
            "uploadedAt": received_at.isoformat(),
        }

    def save_analysis(self, analysis: dict) -> dict:
        """Enregistre un bilan (deja calcule par l'IA, voir ANALYSIS_SCHEMA)
        sur disque et retourne des infos sur le fichier stocke.

        Ne recalcule rien : sauvegarde tel quel le JSON fourni par le
        frontend (celui qu'il a recu de /financialbalance/analysis).
        Horodate le fichier plutot que d'ecraser un seul fichier "latest" :
        rien n'est jamais perdu, get_latest_analysis() se contente de
        prendre le plus recent.

        Leve ValueError si le contenu ne ressemble pas a un bilan valide.
        """
        if not isinstance(analysis, dict) or "summary" not in analysis or "accounts" not in analysis:
            raise ValueError("Le bilan a sauvegarder est invalide (champs 'summary'/'accounts' manquants).")

        saved_at = datetime.now(timezone.utc)
        timestamp = saved_at.strftime("%Y%m%dT%H%M%SZ")
        stored_name = f"{timestamp}.json"
        stored_path = self.analyses_dir / stored_name
        stored_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")

        print(f"FinancialBalance.save_analysis: {stored_name}")
        return {"filename": stored_name, "savedAt": saved_at.isoformat()}

    def get_latest_analysis(self) -> dict:
        """Retourne le dernier bilan sauvegarde (le plus recent fichier de
        analyses_dir). Leve FileNotFoundError si aucun bilan n'a encore
        ete sauvegarde."""
        saved = sorted(self.analyses_dir.glob("*.json"), key=lambda p: p.stat().st_mtime)
        if not saved:
            raise FileNotFoundError("Aucun bilan n'a encore ete sauvegarde.")
        return json.loads(saved[-1].read_text(encoding="utf-8"))

    def _client(self) -> anthropic.Anthropic:
        if self._anthropic_client is None:
            self._anthropic_client = anthropic.Anthropic()
        return self._anthropic_client

    def _latest_archive_path(self) -> Path:
        archives = sorted(self.storage_dir.glob("*.zip"), key=lambda p: p.stat().st_mtime)
        if not archives:
            raise FinancialBalanceAnalysisError("Aucune archive de releves n'a encore ete envoyee.")
        return archives[-1]

    def _pdf_content_blocks(self, archive_path: Path) -> list[dict]:
        """Extrait chaque PDF de l'archive et le convertit en bloc "document"
        (base64) pret a etre envoye a l'API Messages."""
        blocks: list[dict] = []
        with zipfile.ZipFile(archive_path) as zf:
            for name in zf.namelist():
                if not name.lower().endswith(".pdf"):
                    continue
                data = zf.read(name)
                blocks.append(
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": base64.standard_b64encode(data).decode("ascii"),
                        },
                        "title": Path(name).stem,
                    }
                )
        if not blocks:
            raise FinancialBalanceAnalysisError("L'archive ne contient aucun releve PDF.")
        return blocks

    def analyze_latest_archive(self) -> Iterator[dict]:
        """Analyse la derniere archive envoyee via l'API Claude.

        Generateur : produit des evenements JSON-serialisables au fur et a
        mesure (utilise par le receiver pour un flux Server-Sent Events),
        afin que le frontend puisse afficher une progression pendant que
        l'IA travaille (analyse potentiellement longue : plusieurs releves
        PDF + reflexion du modele). Se termine par un evenement "result"
        contenant le bilan structure (voir ANALYSIS_SCHEMA).

        Leve FinancialBalanceAnalysisError en cas d'echec (cle API
        manquante/invalide, erreur reseau, refus du modele...).
        """
        archive_path = self._latest_archive_path()
        blocks = self._pdf_content_blocks(archive_path)

        yield {
            "type": "progress",
            "message": f"{len(blocks)} releve(s) charge(s), analyse en cours... "
            "(cela peut prendre 1 a 2 minutes)",
        }

        try:
            client = self._client()
            tick = 0
            with client.messages.stream(
                model=MODEL,
                max_tokens=16000,
                output_config={"format": {"type": "json_schema", "schema": ANALYSIS_SCHEMA}},
                messages=[
                    {
                        "role": "user",
                        "content": [*blocks, {"type": "text", "text": ANALYSIS_PROMPT}],
                    }
                ],
            ) as stream:
                # Un evenement de progression toutes les ~15 fragments recus :
                # assez pour faire avancer une barre de progression sans
                # inonder le flux SSE d'un evenement par token.
                for event in stream:
                    if event.type == "content_block_delta":
                        tick += 1
                        if tick % 15 == 0:
                            yield {"type": "progress", "message": "L'IA redige le bilan..."}
                response = stream.get_final_message()
        except Exception as exc:  # noqa: BLE001 - isole toute erreur de l'appel IA (cle absente, reseau, refus...) derriere un message clair
            raise FinancialBalanceAnalysisError(f"L'analyse IA a echoue : {exc}") from exc

        if response.stop_reason == "refusal":
            raise FinancialBalanceAnalysisError("L'IA a refuse d'analyser ces documents.")

        text = next((b.text for b in response.content if b.type == "text"), None)
        if text is None:
            raise FinancialBalanceAnalysisError("Reponse inattendue de l'IA (pas de contenu texte).")

        try:
            result = json.loads(text)
        except json.JSONDecodeError as exc:
            raise FinancialBalanceAnalysisError("Reponse de l'IA illisible (JSON invalide).") from exc

        print(f"FinancialBalance.analyze_latest_archive: bilan genere ({len(blocks)} releve(s))")
        yield {"type": "result", "data": result}
