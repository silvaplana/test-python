"""Historique des adherents (payeurs) du club, toutes saisons confondues.

Contrairement aux autres modules (helloasso, ffst, financialbalance), ne
parle a aucune API externe : lit un fichier xlsx statique, genere hors de
ce backend (export manuel a partir des donnees HelloAsso de toutes les
saisons passees) et embarque dans l'image Docker (voir
Dockerfile/pyproject.toml -- commite dans le repo, contrairement a
backend/data/ qui est gitignore pour les donnees sensibles uploadees).
Mis a jour en remplacant le fichier et en redeployant, pas via un endpoint
d'upload.
"""

from __future__ import annotations

from pathlib import Path

import openpyxl

# Fichier livre avec le code (voir docstring de module) : chemin relatif a
# ce module, pas au repertoire de travail du processus, pour rester valide
# quel que soit l'endroit d'ou "python -m app.main" est lance.
DEFAULT_XLSX_PATH = Path(__file__).parent / "data" / "liste_adherents_nombre_campagnes.xlsx"

# Nom de l'onglet et numero de la ligne d'en-tete dans le fichier source
# (3 lignes de titre/sous-titre/blanc avant l'en-tete des colonnes, voir
# le fichier lui-meme) -- si le format change, casse ici plutot que de
# silencieusement mal parser les donnees.
SHEET_NAME = "Adhérents"
HEADER_ROW_INDEX = 3  # 0-based : les donnees commencent juste apres


class MembersHistory:
    """Charge et expose l'historique des adherents (payeurs) par saison.

    Le fichier est lu une seule fois (au premier appel), pas a chaque
    requete : il est embarque dans l'image et ne change donc jamais en
    cours de vie du processus.
    """

    def __init__(self, xlsx_path: Path | str = DEFAULT_XLSX_PATH) -> None:
        self.xlsx_path = Path(xlsx_path)
        self._history: list[dict] | None = None

    def get_history(self) -> list[dict]:
        """Retourne l'historique des adherents : une ligne par payeur, avec
        son nombre de campagnes (saisons distinctes, "Nouvelle saison"
        comprise) et le detail de ces campagnes.
        """
        if self._history is None:
            self._history = self._parse()
        return self._history

    def _parse(self) -> list[dict]:
        workbook = openpyxl.load_workbook(self.xlsx_path, data_only=True)
        sheet = workbook[SHEET_NAME]
        rows = list(sheet.iter_rows(min_row=HEADER_ROW_INDEX + 2, values_only=True))
        history = []
        for last_name, first_name, campaign_count, campaigns in rows:
            if last_name is None:
                continue
            history.append(
                {
                    "lastName": last_name,
                    "firstName": first_name,
                    "campaignCount": campaign_count,
                    # Colonne source : liste de saisons separees par " | ".
                    "campaigns": [c.strip() for c in campaigns.split("|")],
                }
            )
        return history
