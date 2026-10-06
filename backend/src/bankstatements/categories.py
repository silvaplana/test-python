"""Categories des operations bancaires (recettes et depenses), deduites du
libelle de la banque par mots-cles.

Les libelles de la banque sont irreguliers (les salaires apparaissent sous
"VIR SALAIRE", "VIR SEPA SALAIRE CHRISTOPHE", "VIR SALAIRES"...) : une
operation entre dans la 1re categorie de CATEGORIES dont un mot-cle figure
dans son libelle ou ses details, sans tenir compte des majuscules ni des
accents. Sinon : OTHER. Rien n'est stocke en base : changer une regle ici
reclasse tout l'historique.

A COMPLETER ICI pour ajouter une categorie ou un mot-cle. L'ordre compte :
la 1re categorie qui correspond l'emporte.
"""

from __future__ import annotations

import unicodedata

# (nom affiche, mots-cles)
CATEGORIES: list[tuple[str, list[str]]] = [
    ("Cotisations en ligne", ["STRIPE", "HELLOASSO"]),
    ("Salaires", ["SALAIRE"]),
    ("URSSAF", ["URSSAF"]),
    ("Mutuelle", ["PLAN SANTE"]),
    ("FFST (licences)", ["FFST", "LICENCE"]),
    # "FACT SGT..." : frais de tenue de compte ("FACT" seul prendrait aussi
    # une facture d'un fournisseur).
    ("Frais bancaires", ["FACT SGT"]),
    ("Soutien asso (banque)", ["SOUTIEN ASSO"]),
    ("Intérêts", ["INTERETS"]),
    ("Matériel", ["ALI EXPR", "MATOS", "DECATHLON"]),
    ("Médecine du travail", ["GIMS"]),
    # ASP : Agence de services et de paiement (aides de l'Etat) ; DGFIP :
    # remboursements des impots. "ASP" seul serait trop court (il figure
    # dans d'autres mots).
    ("Aides et remboursements", ["ASP AGENCE", "DGFIP"]),
    ("Saisies", ["BLOCAGE SAISIE"]),
]

OTHER = "Autres"
# Virement entre les comptes du club : ni une recette ni une depense.
INTERNAL_TRANSFER = "Virement interne"

# Toutes les categories, dans l'ordre d'affichage.
CATEGORY_NAMES = [name for name, _ in CATEGORIES] + [OTHER, INTERNAL_TRANSFER]


def _normalize(text: str) -> str:
    """"Intérêts  Livret" -> "INTERETS LIVRET" (sans accents, majuscules,
    espaces simples)."""
    decomposed = unicodedata.normalize("NFD", " ".join((text or "").split()))
    return "".join(c for c in decomposed if not unicodedata.combining(c)).upper()


_RULES = [(name, [_normalize(keyword) for keyword in keywords]) for name, keywords in CATEGORIES]


def categorize(label: str, details: str = "", internal_transfer: bool = False) -> str:
    """Categorie d'une operation d'apres son libelle et ses details."""
    if internal_transfer:
        return INTERNAL_TRANSFER
    text = _normalize(f"{label} {details}")
    return next((name for name, keywords in _RULES if any(keyword in text for keyword in keywords)), OTHER)
