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
get_demandes_validated() en fait deux, sur la meme session : connexion, puis clic
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
from playwright.sync_api import sync_playwright


class FfstAuthError(RuntimeError):
    """Levee quand l'authentification aupres du portail FFST echoue."""


class FfstLicencieIntrouvableError(RuntimeError):
    """Levee quand aucun ancien licencie renouvelable ne correspond a la
    recherche -- signale a create_demande_renouvellement() qu'il faut
    basculer sur le chemin "nouvelle demande" plutot qu'echouer."""


class Ffst:
    """Client pour le portail de gestion des licences FFST.

    Chaque appel public (get_licences(), get_demandes_validated(),
    get_demandes_draft(), create_demande_renouvellement()) effectue une
    nouvelle connexion (le site ne propose pas de rafraichissement des
    donnees hors connexion). get_demandes_validated() et
    get_demandes_draft() ont besoin d'une navigation supplementaire apres
    la connexion (clic simule sur un bouton different pour chacune) : les
    deux requetes partagent alors le meme client httpx (memes cookies),
    contrairement a get_licences() qui n'a besoin que de la connexion.
    create_demande_renouvellement() est a part : c'est la seule methode
    d'ecriture (elle cree une vraie demande facturee par la FFST), et la
    seule a piloter un navigateur (Playwright) plutot qu'un simple client
    httpx -- voir sa docstring.

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
        integre a page_html. Utilise par get_licences() et get_demandes_validated() :
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

    def get_demandes_validated(self) -> list[dict]:
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
        print(f"Ffst.get_demandes_validated: {len(demandes)} demande(s) en cours")
        return demandes

    def get_demandes_draft(self) -> list[dict]:
        """Retourne les demandes de licence en brouillon (enregistrees mais
        pas encore validees/soumises a la FFST) pour le club -- le
        "panier" du portail.

        Se connecte puis simule le clic sur le lien "N demande(s) de
        licence sont enregistrees (cliquer sur le panier pour les
        valider)" (bouton WEBDEV M39, formulaire VISU_LICENCES_CLUB) depuis
        la page des licences, pour naviguer vers la page "Panier". Meme
        mecanisme de session partagee que get_demandes_validated().

        Contrairement a get_demandes_validated(), IDDemande est toujours
        vide ici (aucun numero de demande tant qu'elle n'est pas validee).
        Une liste vide est le cas normal : la plupart du temps le panier
        est vide.
        """
        with self._lock, httpx.Client(follow_redirects=True, timeout=20) as client:
            licences_page_html = self._login(client)
            draft_page_html = self._click_bouton(
                client, licences_page_html, form_name="VISU_LICENCES_CLUB", button_id="M39"
            )

        if "Panier" not in draft_page_html:
            raise RuntimeError(
                "Navigation vers le panier de demandes en brouillon a echoue (site modifie ?)"
            )

        demandes = self._parse_wd_table(draft_page_html)
        print(f"Ffst.get_demandes_draft: {len(demandes)} demande(s) en brouillon")
        return demandes

    def create_demande_renouvellement(
        self,
        last_name: str,
        first_name: str,
        *,
        gender: str | None = None,
        birth_date: str | None = None,
        address_line1: str | None = None,
        postal_code: str | None = None,
        city: str | None = None,
        phone: str | None = None,
        email: str | None = None,
    ) -> None:
        """Soumet une demande de licence pour un adherent du club, en
        essayant d'abord le renouvellement (chemin 1) puis, si l'adherent
        n'a jamais ete licencie au club, une nouvelle demande (chemin 2).

        Contrairement aux methodes de lecture ci-dessus (simples POST via
        httpx), ces deux pages du portail sont des formulaires dont l'etat
        est gere par du JS cote client (case a cocher d'un tableau WEBDEV
        pour le chemin 1, formulaire complet pour le chemin 2) -- trop
        fragiles a rejouer en HTTP brut. On pilote donc un vrai navigateur
        (Playwright/Chromium), avec exactement les memes clics qu'un
        humain, plutot que de reproduire ces mecanismes.

        Chemin 1 (renouvellement) : recherche par nom+prenom parmi les
        anciens licencies du club, doit isoler une seule correspondance
        (sinon RuntimeError si ambigu). Reprend automatiquement les
        coordonnees de la licence precedente -- gender/birth_date/etc. ne
        sont pas necessaires ici.

        Chemin 2 (nouvelle demande), utilise seulement si le chemin 1 ne
        trouve personne : necessite gender ("Homme"/"Femme"/"H"/"F", peu
        importe la casse ou la forme), birth_date (JJ/MM/AAAA),
        address_line1, postal_code et city -- leve RuntimeError listant ce
        qui manque si l'appelant ne les a pas fournis. phone et email sont
        optionnels (le formulaire FFST ne les exige pas). La fonction est
        toujours "005-PRATIQUANT" et "Droit a l'image" toujours coche
        (decisions produit, pas une donnee FFST/HelloAsso).

        Les deux chemins cochent "Vous etes en possession de l'attestation
        d'assurance signee par l'adherent" avant de soumettre : la demande
        creee est facturee par la FFST (24 EUR au moment de l'ecriture de
        cette methode) -- a n'appeler que sur action explicite de
        l'utilisateur, jamais automatiquement.
        """
        with self._lock, sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                page = browser.new_page()
                page.on("dialog", lambda dialog: dialog.accept())
                self._se_connecter_via_navigateur(page)

                try:
                    self._renouveler_via_navigateur(page, last_name, first_name)
                except FfstLicencieIntrouvableError:
                    manquants = [
                        libelle
                        for libelle, valeur in {
                            "sexe": gender,
                            "date de naissance": birth_date,
                            "adresse": address_line1,
                            "code postal": postal_code,
                            "ville": city,
                        }.items()
                        if not valeur
                    ]
                    if manquants:
                        raise RuntimeError(
                            f"{last_name} {first_name} n'a pas d'ancienne licence renouvelable "
                            f"et il manque des informations pour saisir une nouvelle demande : "
                            f"{', '.join(manquants)}"
                        ) from None
                    self._saisir_nouvelle_demande_via_navigateur(
                        page,
                        last_name,
                        first_name,
                        gender=gender,
                        birth_date=birth_date,
                        address_line1=address_line1,
                        postal_code=postal_code,
                        city=city,
                        phone=phone,
                        email=email,
                    )
            finally:
                browser.close()

        print(f"Ffst.create_demande_renouvellement: demande soumise pour {last_name} {first_name}")

    def _se_connecter_via_navigateur(self, page) -> None:
        page.goto(f"{self.BASE_URL}{self.LOGIN_PATH}")
        page.fill('[name="A5"]', self.user_part1)
        page.fill('[name="A9"]', self.user_part2)
        page.fill('[name="A10"]', self.user_part3)
        page.fill('[name="A3"]', self.password)
        page.get_by_role("button", name="Valider").click()
        page.wait_for_load_state("networkidle")

        if "Visu_Licences_Club" not in page.content():
            raise FfstAuthError("Authentification FFST echouee (identifiants incorrects ?)")

    def _renouveler_via_navigateur(self, page, last_name: str, first_name: str) -> None:
        # Equivalent au clic sur "Renouveler les licences" (bouton WEBDEV
        # M31, dans un menu deroulant "Demandes") : on appelle directement
        # la fonction JS declenchee par ce bouton plutot que de chercher a
        # ouvrir ce menu, moins fragile face a la mise en page.
        page.evaluate("_JSL(_PAGE_, 'M31', '_self', '', '')")
        page.wait_for_load_state("networkidle")

        # exact=True : "Prénom :" contient "nom :" en sous-chaine, sans quoi
        # get_by_label("Nom :") matcherait aussi le champ Prenom.
        page.get_by_label("Nom :", exact=True).fill(last_name)
        page.get_by_label("Prénom :", exact=True).fill(first_name)
        page.get_by_role("button", name="Rechercher").click()
        page.wait_for_load_state("networkidle")

        checkboxes = page.get_by_role("checkbox")
        count = checkboxes.count()
        if count == 0:
            raise FfstLicencieIntrouvableError(
                f"Aucun ancien licencie renouvelable trouve pour {last_name} {first_name}"
            )
        if count > 1:
            raise RuntimeError(
                f"Plusieurs anciens licencies renouvelables correspondent a "
                f"{last_name} {first_name} : verifier manuellement sur le portail FFST"
            )
        checkboxes.first.check()

        page.get_by_role("button", name="Renouveler les licences sélectionnées").click()
        page.wait_for_load_state("networkidle")

        page.get_by_role(
            "checkbox", name="Vous êtes en possession de l'attestation d'assurance signée par l'adhérent"
        ).check()
        page.get_by_role("button", name="Enregistrer votre demande").click()
        page.wait_for_load_state("networkidle")

    def _saisir_nouvelle_demande_via_navigateur(
        self,
        page,
        last_name: str,
        first_name: str,
        *,
        gender: str,
        birth_date: str,
        address_line1: str,
        postal_code: str,
        city: str,
        phone: str | None,
        email: str | None,
    ) -> None:
        # Equivalent au clic sur "Saisir une nouvelle demande" (bouton
        # WEBDEV M30, meme menu que M31) -- meme technique que
        # _renouveler_via_navigateur (voir sa docstring).
        page.evaluate("_JSL(_PAGE_, 'M30', '_self', '', '')")
        # Ce formulaire se construit en 2 temps cote client (constate en
        # debug : "networkidle" seul se declenche puis le contexte de page
        # est aussitot detruit par un second rendu) -- attendre un champ
        # concret du formulaire final avant d'y toucher, sinon les valeurs
        # saisies (ex: select_option sur la discipline) sont perdues et la
        # validation FFST rejette silencieusement la demande.
        page.wait_for_selector('[name="A33"]', state="attached", timeout=15000)
        page.wait_for_load_state("networkidle")

        gender_normalized = (gender or "").strip()[:1].upper()
        if gender_normalized not in ("H", "F"):
            raise RuntimeError(
                f"Sexe HelloAsso non reconnu pour {last_name} {first_name} : {gender!r} "
                "(attendu 'Homme'/'H' ou 'Femme'/'F')"
            )

        def stabiliser() -> None:
            # Plusieurs champs de ce formulaire (discipline, fonction, code
            # postal, ...) declenchent un rechargement cote serveur au
            # blur (constate en debug : les valeurs suivantes se
            # retrouvaient perdues ou melangees sans cette pause) --
            # attendre le reseau ET un court delai supplementaire (le
            # rechargement peut demarrer apres la resolution de
            # "networkidle") avant de toucher au champ suivant.
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(300)
            page.wait_for_selector('[name="A33"]', state="attached", timeout=15000)

        def remplir(selector: str, value: str) -> None:
            page.fill(selector, value)
            page.press(selector, "Tab")  # force le blur (declencheur du rechargement)
            stabiliser()

        # Noms de champs WEBDEV confirmes par inspection du formulaire
        # (aucun de ces champs n'a de <label for=...> exploitable par
        # Playwright, contrairement aux pages de lecture) : A33 discipline,
        # A10 nom, A12 prenom, A15 sexe (1=Masculin/2=Feminin), A18 date de
        # naissance, A39 fonction, A24/A27/A28 adresse, A29/A30 telephones,
        # A31 email, A78 droit a l'image, A35 attestation assurance. Seule
        # discipline du club : Sambo (0470-SAMBO).
        page.select_option('[name="A33"]', label="0470-SAMBO")
        stabiliser()
        remplir('[name="A10"]', last_name)
        remplir('[name="A12"]', first_name)
        page.check(f'[name="A15"][value="{"1" if gender_normalized == "H" else "2"}"]')
        stabiliser()
        remplir('[name="A18"]', birth_date)
        page.select_option('[name="A39"]', label="005-PRATIQUANT")
        stabiliser()
        remplir('[name="A27"]', postal_code)  # avant l'adresse : declenche une suggestion de ville
        remplir('[name="A24"]', address_line1)
        remplir('[name="A28"]', city)
        if phone:
            remplir('[name="A30"]', phone)  # Tel. mobile (decision produit : voir docstring)
        if email:
            remplir('[name="A31"]', email)

        page.check('#A78_1')  # Droit a l'image
        page.check('#A35_1')  # Attestation d'assurance
        page.get_by_role("button", name="Enregistrer votre demande").click()
        page.wait_for_load_state("networkidle")


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
    for demande in client.get_demandes_validated():
        print(demande)
    for demande in client.get_demandes_draft():
        print(demande)


if __name__ == "__main__":
    main()
