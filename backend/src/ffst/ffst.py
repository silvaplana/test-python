"""Client pour le portail de gestion des licences FFST (ffst-licences.com).

Pas d'API : le portail est une application WEBDEV (framework francais)
protegee par un formulaire de connexion classique. Deux particularites :

- L'identifiant "Utilisateur" est saisi en 3 champs separes (ex: 21 / 13 /
  1230 - vraisemblablement ligue / departement / n° d'affiliation du club).
- Il n'y a pas d'endpoint API distinct pour les donnees : chaque page
  ("Licences de la saison", "Renouvellement de licences" pour les
  demandes en cours, ...) contient directement un bloc XML echappe
  (balises \\x3C/\\x3E) integre dans un <script>, qui alimente le tableau
  cote client. Ce module recupere ce bloc et le parse.

get_licences() ne fait qu'une requete (connexion = page de resultat).
get_demandes() en fait deux, sur la meme session : connexion, puis clic
simule sur le bouton "Visualiser les demandes de licence en cours".

Variables d'environnement attendues pour le main() de demo :
    FFST_USER_PART1, FFST_USER_PART2, FFST_USER_PART3   identifiant (3 champs)
    FFST_PASSWORD                                        mot de passe

Voir .env.example a la racine de backend/.
"""

from __future__ import annotations

import html
import os
import re
import threading
import xml.etree.ElementTree as ET

import httpx
from dotenv import load_dotenv


class FfstAuthError(RuntimeError):
    """Levee quand l'authentification aupres du portail FFST echoue."""


class Ffst:
    """Client pour le portail de gestion des licences FFST.

    Chaque appel public (get_licences(), get_demandes()) effectue une
    nouvelle connexion (le site ne propose pas de rafraichissement des
    donnees hors connexion). get_demandes() a besoin d'une navigation
    supplementaire apres la connexion (clic simule sur un bouton) : les
    deux requetes partagent alors le meme client httpx (memes cookies),
    contrairement a get_licences() qui n'a besoin que de la connexion.

    Le site ne supporte pas bien les connexions concurrentes sur le meme
    compte (des requetes simultanees font parfois echouer la connexion,
    la page retournee ne contenant alors plus le formulaire attendu) : un
    verrou serialise donc tous les appels reseau de cette instance.
    """

    BASE_URL = "https://ffst-licences.com"
    LOGIN_PATH = "/GESTION_LICENCES_FFST"

    def __init__(self, user_part1: str, user_part2: str, user_part3: str, password: str) -> None:
        self.user_part1 = user_part1
        self.user_part2 = user_part2
        self.user_part3 = user_part3
        self.password = password
        self._lock = threading.Lock()

    def _extract_form(self, page_html: str, form_name: str) -> tuple[str, dict[str, str]]:
        """Extrait l'URL d'action (absolue) et les champs caches (deja
        HTML-unescapes) du formulaire WEBDEV `form_name` present dans
        page_html. Leve RuntimeError si le formulaire est introuvable."""
        match_action = re.search(rf'<form name="{form_name}" action="([^"]+)"', page_html)
        if not match_action:
            raise RuntimeError(f'Formulaire WEBDEV "{form_name}" introuvable (site modifie ?)')

        hidden_fields = {
            key: html.unescape(value)
            for key, value in re.findall(
                r'<input type="hidden" name="([^"]+)" value="([^"]*)"', page_html
            )
        }
        return f"{self.BASE_URL}{match_action.group(1)}", hidden_fields

    def _login(self, client: httpx.Client) -> str:
        """Se connecte (avec le client httpx fourni, pour permettre a
        l'appelant d'enchainer d'autres requetes sur la meme session) et
        retourne le HTML de la page "Licences de la saison" qui suit la
        connexion."""
        login_page = client.get(f"{self.BASE_URL}{self.LOGIN_PATH}")
        action_url, hidden_fields = self._extract_form(login_page.text, "ACCUEIL")

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

    def _click_bouton(
        self, client: httpx.Client, page_html: str, form_name: str, button_id: str
    ) -> str:
        """Simule le clic sur un bouton WEBDEV (soumission du formulaire
        `form_name` avec WD_BUTTON_CLICK_=`button_id`) et retourne le HTML
        de la page resultante. Le client httpx doit etre le meme (memes
        cookies) que celui utilise pour la connexion prealable : le
        portail WEBDEV lie la navigation a la session."""
        action_url, hidden_fields = self._extract_form(page_html, form_name)
        data = {**hidden_fields, "WD_BUTTON_CLICK_": button_id}
        response = client.post(action_url, data=data)
        return response.text

    def _parse_wd_table(self, page_html: str) -> list[dict]:
        """Extrait et parse le tableau de donnees WEBDEV (champ "A1")
        integre a page_html. Utilise par get_licences() et get_demandes() :
        les deux pages du portail exposent leurs donnees via le meme
        mecanisme (bloc XML echappe dans un appel JS
        DeclareChamp("A1", ..., WDTable, [...]))."""
        match = re.search(
            r'DeclareChamp\("A1".*?WDTable,\["(.*?)",0,\d+,\d+,\d+,\d+,\[',
            page_html,
            re.DOTALL,
        )
        if not match:
            raise RuntimeError("Bloc de donnees WEBDEV (champ A1) introuvable dans la page")

        xml_str = match.group(1).replace("\\x3C", "<").replace("\\x3E", ">").replace('\\"', '"')
        root = ET.fromstring(xml_str)
        columns = [col.get("TITRE") for col in root.find("COLONNES")]

        rows = []
        for ligne in root.find("LIGNES"):
            values = [col.text for col in ligne]
            rows.append(dict(zip(columns, values)))
        return rows

    def get_licences(self) -> list[dict]:
        """Retourne la liste des licences du club pour la saison en cours.

        Chaque licence est un dict dont les cles sont les colonnes telles
        que definies par le site (Discipline, "Nom et Prenom", "Ne(e) le",
        Sexe, Type, "Licence n°", ...).
        """
        with self._lock, httpx.Client(follow_redirects=True, timeout=20) as client:
            page_html = self._login(client)

        licences = self._parse_wd_table(page_html)
        print(f"Ffst.get_licences: {len(licences)} licence(s) recuperee(s)")
        return licences

    def get_demandes(self) -> list[dict]:
        """Retourne les demandes de licence en cours (nouvelles demandes et
        renouvellements pas encore valides) pour le club.

        Se connecte puis simule le clic sur "Visualiser les demandes de
        licence en cours" (bouton WEBDEV M32, formulaire
        VISU_LICENCES_CLUB) depuis la page des licences, pour naviguer vers
        la page "Renouvellement de licences". Contrairement a
        get_licences(), les deux requetes (connexion + clic) partagent la
        meme session/cookies (meme client httpx, meme bloc `with`).

        Une liste vide est le cas normal : la plupart du temps il n'y a
        aucune demande en attente.
        """
        with self._lock, httpx.Client(follow_redirects=True, timeout=20) as client:
            licences_page_html = self._login(client)
            demandes_page_html = self._click_bouton(
                client, licences_page_html, form_name="VISU_LICENCES_CLUB", button_id="M32"
            )

        if "Renouvellement de licences" not in demandes_page_html:
            raise RuntimeError(
                "Navigation vers la page des demandes en cours a echoue (site modifie ?)"
            )

        demandes = self._parse_wd_table(demandes_page_html)
        print(f"Ffst.get_demandes: {len(demandes)} demande(s) en cours")
        return demandes


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
    for demande in client.get_demandes():
        print(demande)


if __name__ == "__main__":
    main()
