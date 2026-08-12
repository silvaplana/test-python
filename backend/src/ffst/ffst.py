"""Client pour le portail de gestion des licences FFST (ffst-licences.com).

Pas d'API : le portail est une application WEBDEV (framework francais)
protegee par un formulaire de connexion classique. Deux particularites :

- L'identifiant "Utilisateur" est saisi en 3 champs separes (ex: 21 / 13 /
  1230 - vraisemblablement ligue / departement / n° d'affiliation du club).
- Il n'y a pas d'endpoint API distinct pour les donnees : la page qui suit
  la connexion ("Licences de la saison") contient directement un bloc XML
  echappe (balises \\x3C/\\x3E) integre dans un <script>, qui alimente le
  tableau cote client. Ce module recupere ce bloc et le parse.

Variables d'environnement attendues pour le main() de demo :
    FFST_USER_PART1, FFST_USER_PART2, FFST_USER_PART3   identifiant (3 champs)
    FFST_PASSWORD                                        mot de passe

Voir .env.example a la racine de backend/.
"""

from __future__ import annotations

import html
import os
import re
import xml.etree.ElementTree as ET

import httpx
from dotenv import load_dotenv


class FfstAuthError(RuntimeError):
    """Levee quand l'authentification aupres du portail FFST echoue."""


class Ffst:
    """Client pour le portail de gestion des licences FFST.

    Chaque appel a get_licences() effectue une nouvelle connexion (le
    site ne propose pas de rafraichissement des donnees hors connexion,
    la page de connexion et la page de resultats ne faisant qu'un).
    """

    BASE_URL = "https://ffst-licences.com"
    LOGIN_PATH = "/GESTION_LICENCES_FFST"

    def __init__(self, user_part1: str, user_part2: str, user_part3: str, password: str) -> None:
        self.user_part1 = user_part1
        self.user_part2 = user_part2
        self.user_part3 = user_part3
        self.password = password

    def _login(self) -> str:
        """Se connecte (nouvelle session a chaque appel) et retourne le HTML
        de la page "Licences de la saison" qui suit la connexion."""
        with httpx.Client(follow_redirects=True, timeout=20) as client:
            login_page = client.get(f"{self.BASE_URL}{self.LOGIN_PATH}")

            match_action = re.search(r'<form name="ACCUEIL" action="([^"]+)"', login_page.text)
            if not match_action:
                raise FfstAuthError("Formulaire de connexion FFST introuvable (site modifie ?)")

            hidden_fields = {
                key: html.unescape(value)
                for key, value in re.findall(
                    r'<input type="hidden" name="([^"]+)" value="([^"]*)"', login_page.text
                )
            }
            action_url = f"{self.BASE_URL}{match_action.group(1)}"

            data = {
                **hidden_fields,
                "A5": self.user_part1,
                "A9": self.user_part2,
                "A10": self.user_part3,
                "A3": self.password,
                "WD_BUTTON_CLICK_": "A7",
            }
            response = client.post(action_url, data=data)

        if "Visu_Licences_Club" not in response.text:
            raise FfstAuthError("Authentification FFST echouee (identifiants incorrects ?)")

        print("Ffst.login: connecte")
        return response.text

    def get_licences(self) -> list[dict]:
        """Retourne la liste des licences du club pour la saison en cours.

        Chaque licence est un dict dont les cles sont les colonnes telles
        que definies par le site (Discipline, "Nom et Prenom", "Ne(e) le",
        Sexe, Type, "Licence n°", ...).
        """
        page_html = self._login()

        match = re.search(
            r'DeclareChamp\("A1".*?WDTable,\["(.*?)",0,\d+,\d+,\d+,\d+,\[',
            page_html,
            re.DOTALL,
        )
        if not match:
            raise RuntimeError("Bloc de donnees des licences introuvable dans la page")

        xml_str = match.group(1).replace("\\x3C", "<").replace("\\x3E", ">").replace('\\"', '"')
        root = ET.fromstring(xml_str)
        columns = [col.get("TITRE") for col in root.find("COLONNES")]

        licences = []
        for ligne in root.find("LIGNES"):
            values = [col.text for col in ligne]
            licences.append(dict(zip(columns, values)))

        print(f"Ffst.get_licences: {len(licences)} licence(s) recuperee(s)")
        return licences


def main() -> None:
    load_dotenv()  # charge backend/.env si present

    user_part1 = os.environ.get("FFST_USER_PART1")
    user_part2 = os.environ.get("FFST_USER_PART2")
    user_part3 = os.environ.get("FFST_USER_PART3")
    password = os.environ.get("FFST_PASSWORD")

    if not all([user_part1, user_part2, user_part3, password]):
        raise SystemExit(
            "FFST_USER_PART1, FFST_USER_PART2, FFST_USER_PART3 et FFST_PASSWORD "
            "doivent etre definis (variables d'environnement, voir backend/.env.example)."
        )

    client = Ffst(user_part1, user_part2, user_part3, password)
    for licence in client.get_licences():
        print(licence)


if __name__ == "__main__":
    main()
