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


# Options exactes du champ "Fonction*" (A39) du formulaire de demande de
# licence, confirmees par inspection en direct (page.eval_on_selector sur
# le <select>). A tenir a jour si le portail en ajoute/retire -- pas
# d'endpoint pour les recuperer dynamiquement, ce champ n'existe que dans
# le HTML/JS de la page (comme les tableaux WEBDEV lus ailleurs dans ce
# module).
FFST_FONCTIONS = [
    "001-PRESIDENT",
    "002-SECRETAIRE",
    "003-TRESORIER",
    "004-ENTRAINEUR",
    "005-PRATIQUANT",
    "006-JUGE",
    "007-ARBITRE",
    "008-ADMINISTRATIF",
    "010-VICE PRESIDENT",
    "011-TRESORIER PRATIQUANT",
    "012-SECRETAIRE PRATIQUANT",
    "013-ADMINISTRATIF PRATIQUANT",
    "014-DIRIGEANT PRATIQUANT",
    "015-DIRIGEANT",
    "016-PRESIDENT ENTRAINEUR",
    "017-SECRETAIRE ENTRAINEUR",
    "018-TRESORIER ENTRAINEUR",
    "019-PRESIDENT PRATIQUANT",
    "021-ADMINISTRATIF JUGE",
    "022-ADMINISTRATIF/JUGE/ENT",
    "024-SECRETAIRE ADJOINT",
    "025-TRESORIER ADJOINT",
    "026-ENT/ADM/PRATIQUANT",
    "028-PRESIDENT D'HONNEUR",
    "029-ENTRAINEUR - JUGE",
    "030-ADMINISTRATIF ENTRAINEUR",
    "032-PRESIDENT ADJOINT",
    "034-ENTRAINEUR - PRATIQUANT",
    "036-Vice Président/Entraîneur",
    "038-JUGE - PRATIQUANT",
    "042-RESPONSABLE SECTION",
    "043-MEDECIN",
    "053-INSTRUCTEUR",
    "056-PRESIDENT NATIONAL",
    "057-TRESORIERE NATIONALE",
    "059-TRESORIER - JUGE",
    "060-MEMBRE D HONNEUR",
    "061-ARBITRE - PRATIQUANT",
    "062-PRESIDENT - ARBITRE",
    "063-TRESORIER - ARBITRE",
    "064-SECRETAIRE - ARBITRE",
    "065-ENTRAINEUR - ARBITRE",
    "066-SECRETAIRE - JUGE",
]

# Ville de repli pour le champ FFST "Commune de naissance" (obligatoire pour
# toute fonction autre que "005-PRATIQUANT", absent de HelloAsso) quand la
# ville de l'adresse de l'adherent n'est pas reconnue par la recherche du
# formulaire -- voir Ffst._remplir_informations_demande. Ville du club :
# hypothese la plus probable a defaut d'autre info, a corriger sur le
# portail FFST si elle est fausse pour l'adherent concerne.
COMMUNE_NAISSANCE_PAR_DEFAUT = "La Ciotat"


class Ffst:
    """Client pour le portail de gestion des licences FFST.

    Chaque appel public (get_licences(), get_demandes_validated(),
    get_demandes_draft(), create_demande_renouvellement(),
    delete_demande_draft()) effectue une nouvelle connexion (le site ne
    propose pas de rafraichissement des donnees hors connexion).
    get_demandes_validated() et get_demandes_draft() ont besoin d'une
    navigation supplementaire apres la connexion (clic simule sur un
    bouton different pour chacune) : les deux requetes partagent alors le
    meme client httpx (memes cookies), contrairement a get_licences() qui
    n'a besoin que de la connexion. create_demande_renouvellement() et
    delete_demande_draft() sont a part : ce sont les seules methodes
    d'ecriture (elles creent/suppriment une vraie demande FFST), et les
    seules a piloter un navigateur (Playwright) plutot qu'un simple
    client httpx -- voir leurs docstrings.

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

    def delete_demande_draft(self, last_name: str, first_name: str) -> None:
        """Supprime une demande en brouillon (panier) pour un adherent
        identifie par nom+prenom (doit correspondre a une seule ligne du
        panier, sinon RuntimeError).

        Comme create_demande_renouvellement(), pilote un vrai navigateur
        (Playwright) : la case a cocher du panier est le meme genre de
        tableau WEBDEV editable que celui de "Renouveler les licences",
        et la suppression elle-meme passe par une modale de confirmation
        (lien "Oui", pas une boite de dialogue JS) rendue dans la page.
        """
        with self._lock, sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                page = browser.new_page()
                page.on("dialog", lambda dialog: dialog.accept())
                self._se_connecter_via_navigateur(page)
                self._supprimer_demande_draft_via_navigateur(page, last_name, first_name)
            finally:
                browser.close()

        print(f"Ffst.delete_demande_draft: demande supprimee pour {last_name} {first_name}")

    def _supprimer_demande_draft_via_navigateur(self, page, last_name: str, first_name: str) -> None:
        page.evaluate("_JSL(_PAGE_, 'M39', '_self', '', '')")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(500)

        if "Panier" not in page.content():
            raise RuntimeError(
                "Navigation vers le panier de demandes en brouillon a echoue (site modifie ?)"
            )

        # HelloAsso fournit parfois nom/prenom avec un espace superflu en
        # debut/fin (constate en prod : lastName="Barrachina " pour Tom
        # Barrachina) -- un simple .strip() ne suffit pas, il ne nettoie
        # que les bords de la chaine concatenee, pas l'espace double que
        # ca laisse entre nom et prenom. " ".join(...split()) normalise
        # tous les espaces (comme memberIdentifier() cote frontend, qui
        # fait ce meme rapprochement pour la colonne Statut FFST) : sans
        # ca, la demande venait bien d'etre creee avec succes (recherche
        # FFST insensible a cet espace) mais introuvable a la suppression.
        cible = " ".join(f"{last_name} {first_name}".split()).upper()

        def trouver_index() -> int:
            demandes = self._parse_wd_table(page.content())
            indices = [
                i
                for i, d in enumerate(demandes)
                if " ".join((d.get("Nom et Prénom") or "").split()).upper() == cible
            ]
            if not indices:
                return -1
            if len(indices) > 1:
                raise RuntimeError(
                    f"Plusieurs demandes en brouillon correspondent a {last_name} {first_name} : "
                    "verifier manuellement sur le portail FFST"
                )
            return indices[0]

        index = trouver_index()
        if index == -1:
            raise RuntimeError(f"Aucune demande en brouillon trouvee pour {last_name} {first_name}")

        # 2 tentatives : la confirmation ci-dessous s'est deja averee
        # silencieusement sans effet une fois en test (rien ne remontait
        # d'erreur ni de dialogue inattendu) -- on ne fait donc jamais
        # confiance a "aucune exception levee" seul, on reverifie toujours
        # que la ligne a bien disparu avant de conclure au succes.
        for _ in range(2):
            # Case a cocher de la ligne : nommee "_{index}_A1_0" (index de
            # la ligne dans le tableau, confirme par inspection du panier
            # -- meme tableau WEBDEV editable que "Renouveler les
            # licences", mais la case n'y suit pas la meme convention de
            # nommage que le champ "Sel" utilise pour le renouvellement).
            page.check(f'[name="_{index}_A1_0"]')
            page.wait_for_timeout(300)

            page.get_by_role("button", name="Supprimer la demande").click()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(300)

            # La confirmation ("Etes vous certain de bien vouloir annuler
            # la demande de ... ?") est un lien stylise en bouton (<a>),
            # pas un <button> ni une boite de dialogue JS -- get_by_role
            # ("button", ...) ne le trouverait pas. ".first" : le bouton
            # "riche" WEBDEV duplique son libelle dans 2 spans (etats
            # hover/normal).
            page.get_by_role("link", name="Oui").first.click()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(500)

            index = trouver_index()
            if index == -1:
                return

        raise RuntimeError(
            f"La suppression de la demande de {last_name} {first_name} semble avoir echoue "
            "(toujours presente apres 2 tentatives) : verifier manuellement sur le portail FFST"
        )

    def create_demande_renouvellement(
        self,
        last_name: str,
        first_name: str,
        *,
        fonction: str = "005-PRATIQUANT",
        gender: str | None = None,
        birth_date: str | None = None,
        address_line1: str | None = None,
        postal_code: str | None = None,
        city: str | None = None,
        phone: str | None = None,
        email: str | None = None,
    ) -> list[str]:
        """Soumet une demande de licence pour un adherent du club, en
        essayant d'abord le renouvellement (chemin 1) puis, si l'adherent
        n'a jamais ete licencie au club, une nouvelle demande (chemin 2).
        Retourne une liste d'avertissements non bloquants (vide si aucun),
        voir plus bas.

        Contrairement aux methodes de lecture ci-dessus (simples POST via
        httpx), ces deux pages du portail sont des formulaires dont l'etat
        est gere par du JS cote client (case a cocher d'un tableau WEBDEV
        pour le chemin 1, formulaire complet pour le chemin 2) -- trop
        fragiles a rejouer en HTTP brut. On pilote donc un vrai navigateur
        (Playwright/Chromium), avec exactement les memes clics qu'un
        humain, plutot que de reproduire ces mecanismes.

        Chemin 1 (renouvellement) : recherche par nom+prenom parmi les
        anciens licencies du club, doit isoler une seule correspondance
        (sinon RuntimeError si ambigu). Le formulaire qui suit arrive
        pre-rempli avec les coordonnees de la licence precedente, mais
        celles-ci peuvent etre perimees (adherent qui a demenage/change de
        telephone depuis) : elles sont donc ecrasees avec les informations
        HelloAsso ci-dessous, exactement comme le chemin 2, plutot que
        d'etre reprises telles quelles.

        Chemin 2 (nouvelle demande), utilise seulement si le chemin 1 ne
        trouve personne : formulaire vierge, memes informations.

        Dans les deux cas, gender ("Homme"/"Femme"/"H"/"F", peu importe la
        casse ou la forme), birth_date (JJ/MM/AAAA), address_line1,
        postal_code et city sont desormais obligatoires (RuntimeError
        listant ce qui manque sinon) ; phone et email restent optionnels
        (le formulaire FFST ne les exige pas). fonction doit etre l'une des
        valeurs de FFST_FONCTIONS (RuntimeError sinon), par defaut
        "005-PRATIQUANT" (le cas le plus courant : la plupart des
        adherents d'un club ne sont que pratiquants). "Droit a l'image"
        est toujours coche pour une nouvelle demande (decision produit,
        pas une donnee FFST/HelloAsso) -- pas touche pour un
        renouvellement (deja renseigne par l'adherent lors de sa demande
        precedente).

        Toute fonction autre que "005-PRATIQUANT" declenche en plus une
        tentative de renseignement de la "Commune de naissance" (exigee
        par la FFST, absente de HelloAsso) a partir de city, avec repli
        sur COMMUNE_NAISSANCE_PAR_DEFAUT si city n'est pas reconnue (voir
        _remplir_informations_demande) -- ce repli est signale dans la
        liste retournee, a afficher a l'utilisateur (la vraie commune
        devra alors etre corrigee manuellement sur le portail FFST). Dans
        tous les cas, la confirmation FFST est verifiee apres soumission
        (voir _verifier_confirmation_enregistrement) : RuntimeError si la
        demande a ete rejetee plutot qu'un faux succes silencieux.

        Les deux chemins cochent "Vous etes en possession de l'attestation
        d'assurance signee par l'adherent" avant de soumettre : la demande
        creee est facturee par la FFST (24 EUR au moment de l'ecriture de
        cette methode) -- a n'appeler que sur action explicite de
        l'utilisateur, jamais automatiquement.
        """
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
                f"Informations manquantes pour soumettre une demande pour {last_name} {first_name} : "
                f"{', '.join(manquants)}"
            )
        if fonction not in FFST_FONCTIONS:
            raise RuntimeError(f"Fonction FFST inconnue : {fonction!r} (voir FFST_FONCTIONS)")

        with self._lock, sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                page = browser.new_page()
                # Les popups JS (confirmation ou rejet de la demande, voir
                # _verifier_confirmation_enregistrement) doivent etre
                # acceptees pour que Playwright continue -- mais leur texte
                # est conserve (attribut ajoute sur l'objet page) pour
                # detecter un rejet silencieux plutot que de l'avaler sans
                # verification.
                page.ffst_dialog_messages = []
                # Avertissements non bloquants (ex: commune de naissance de
                # repli utilisee, voir _remplir_informations_demande) --
                # a faire remonter a l'utilisateur, contrairement aux
                # RuntimeError qui interrompent la demande.
                page.ffst_warnings = []
                page.on(
                    "dialog",
                    lambda dialog: (page.ffst_dialog_messages.append(dialog.message), dialog.accept()),
                )
                self._se_connecter_via_navigateur(page)

                infos = dict(
                    fonction=fonction,
                    gender=gender,
                    birth_date=birth_date,
                    address_line1=address_line1,
                    postal_code=postal_code,
                    city=city,
                    phone=phone,
                    email=email,
                )
                try:
                    self._renouveler_via_navigateur(page, last_name, first_name, **infos)
                except FfstLicencieIntrouvableError:
                    self._saisir_nouvelle_demande_via_navigateur(page, last_name, first_name, **infos)
                warnings = list(page.ffst_warnings)
            finally:
                browser.close()

        print(f"Ffst.create_demande_renouvellement: demande soumise pour {last_name} {first_name}")
        return warnings

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

    def _renouveler_via_navigateur(
        self,
        page,
        last_name: str,
        first_name: str,
        *,
        fonction: str,
        gender: str,
        birth_date: str,
        address_line1: str,
        postal_code: str,
        city: str,
        phone: str | None,
        email: str | None,
    ) -> None:
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
        # Meme instabilite constatee que pour "nouvelle demande" (page
        # reconstruite en 2 temps cote client) : attendre un champ concret
        # du formulaire final avant d'y toucher (voir
        # _saisir_nouvelle_demande_via_navigateur).
        page.wait_for_selector('[name="A33"]', state="attached", timeout=15000)
        page.wait_for_load_state("networkidle")

        # Ce formulaire arrive pre-rempli avec les coordonnees de
        # l'ANCIENNE licence (adresse, telephone, ...), potentiellement
        # perimees (l'adherent a pu demenager/changer de numero depuis) :
        # on les ecrase avec les informations HelloAsso les plus recentes
        # plutot que de les laisser telles quelles. Ne touche pas a la
        # discipline (A33) : en lecture seule ici (deja fixee par
        # l'ancienne licence), contrairement a une nouvelle demande.
        self._remplir_informations_demande(
            page,
            last_name,
            first_name,
            fonction=fonction,
            gender=gender,
            birth_date=birth_date,
            address_line1=address_line1,
            postal_code=postal_code,
            city=city,
            phone=phone,
            email=email,
        )

        page.get_by_role(
            "checkbox", name="Vous êtes en possession de l'attestation d'assurance signée par l'adhérent"
        ).check()
        page.ffst_dialog_messages.clear()
        page.get_by_role("button", name="Enregistrer votre demande").click()
        page.wait_for_load_state("networkidle")
        self._verifier_confirmation_enregistrement(page, last_name, first_name)

    def _saisir_nouvelle_demande_via_navigateur(
        self,
        page,
        last_name: str,
        first_name: str,
        *,
        fonction: str,
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

        # Seul ce chemin (formulaire vierge, aucun historique de licence a
        # reprendre) doit definir la discipline : en lecture seule pour un
        # renouvellement (voir _renouveler_via_navigateur). Seule
        # discipline du club : Sambo (0470-SAMBO).
        page.select_option('[name="A33"]', label="0470-SAMBO")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(300)
        page.wait_for_selector('[name="A33"]', state="attached", timeout=15000)

        self._remplir_informations_demande(
            page,
            last_name,
            first_name,
            fonction=fonction,
            gender=gender,
            birth_date=birth_date,
            address_line1=address_line1,
            postal_code=postal_code,
            city=city,
            phone=phone,
            email=email,
        )

        page.check("#A78_1")  # Droit a l'image (decision produit, pas une donnee HelloAsso)
        page.check("#A35_1")  # Attestation d'assurance
        page.ffst_dialog_messages.clear()
        page.get_by_role("button", name="Enregistrer votre demande").click()
        page.wait_for_load_state("networkidle")
        self._verifier_confirmation_enregistrement(page, last_name, first_name)

    def _verifier_confirmation_enregistrement(self, page, last_name: str, first_name: str) -> None:
        """Verifie que la FFST a bien confirme l'enregistrement de la
        demande ("Votre demande a bien ete enregistree", popup JS) apres le
        clic sur "Enregistrer votre demande".

        Indispensable : un champ obligatoire manquant ou invalide (ex:
        commune de naissance non trouvee, coordonnees manquantes pour un
        Président/Trésorier/Secrétaire) ne fait pas echouer le clic ni la
        navigation -- la FFST affiche une simple alerte JS, silencieusement
        acceptee par le gestionnaire de dialogues (necessaire pour que
        Playwright continue), et rien d'autre ne signale l'echec. Sans
        cette verification, une demande rejetee semblerait avoir reussi.
        """
        messages = getattr(page, "ffst_dialog_messages", [])
        if any("bien" in m.lower() and "enregistr" in m.lower() for m in messages):
            return
        detail = messages[-1] if messages else "aucune confirmation recue de la FFST (site modifie ?)"
        raise RuntimeError(
            f"La demande pour {last_name} {first_name} n'a pas ete enregistree par la FFST : {detail}"
        )

    def _remplir_informations_demande(
        self,
        page,
        last_name: str,
        first_name: str,
        *,
        fonction: str,
        gender: str,
        birth_date: str,
        address_line1: str,
        postal_code: str,
        city: str,
        phone: str | None,
        email: str | None,
    ) -> None:
        """Remplit les champs communs aux 2 formulaires de demande (nom,
        prenom, sexe, date de naissance, fonction, adresse, telephone,
        email) avec les informations fournies -- utilise aussi bien pour
        un renouvellement (deja pre-rempli avec d'anciennes coordonnees) que
        pour une nouvelle demande (formulaire vierge), justement pour
        remplacer d'eventuelles anciennes coordonnees perimees.

        Ne touche pas au champ discipline (A33) : lecture seule pour un
        renouvellement, a definir separement par l'appelant pour une
        nouvelle demande (seule utilisatrice de ce champ editable).

        Toute fonction autre que "005-PRATIQUANT" fait apparaitre un champ
        supplementaire obligatoire, "Commune de naissance" (absent de
        HelloAsso) : on tente la ville de l'adresse actuelle en
        approximation (seule donnee disponible), via le widget de
        recherche du formulaire (champ A61 + bouton de recherche #A76 +
        resultats dans le select A54). Si cette recherche ne renvoie
        aucun resultat ou plusieurs (impossible de choisir sans
        ambiguite), on retente avec COMMUNE_NAISSANCE_PAR_DEFAUT (ville du
        club) : succes -> avertissement ajoute a page.ffst_warnings (a
        faire remonter a l'utilisateur, la vraie commune devra etre
        corrigee sur le portail FFST) ; echec des deux tentatives ->
        RuntimeError.
        """
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
        # Playwright, contrairement aux pages de lecture) : A10 nom, A12
        # prenom, A15 sexe (1=Masculin/2=Feminin), A18 date de naissance,
        # A39 fonction, A24/A27/A28 adresse, A29 tel. fixe, A30 tel.
        # mobile, A31 email.
        remplir('[name="A10"]', last_name)
        remplir('[name="A12"]', first_name)
        page.check(f'[name="A15"][value="{"1" if gender_normalized == "H" else "2"}"]')
        stabiliser()
        remplir('[name="A18"]', birth_date)
        page.select_option('[name="A39"]', label=fonction)
        stabiliser()

        # Champ "Commune de naissance" : visible seulement pour les
        # fonctions autres que pratiquant. Sur le formulaire "nouvelle
        # demande", il est carrement absent du DOM pour "005-PRATIQUANT"
        # (count() == 0) -- mais sur le formulaire "renouvellement", il y
        # reste toujours present (count() == 1), juste masque en CSS
        # (bug constate en prod le 2026-09-10 : count() > 0 le traitait
        # a tort comme visible pour un renouvellement de pratiquant, d'ou
        # un page.fill() qui timeout puisque l'element n'est jamais
        # visible -- 500 systematique). is_visible() gere les 2 cas
        # (renvoie False si l'element est absent OU masque).
        if page.locator('[name="A61"]').is_visible():

            def rechercher_commune(ville: str) -> list[dict]:
                page.fill('[name="A61"]', ville)
                page.click("#A76")
                stabiliser()
                options = page.eval_on_selector(
                    '[name="A54"]', "el => Array.from(el.options).map(o => ({value: o.value, text: o.text}))"
                )
                return [o for o in options if o["text"] != "Sélectionnez"]

            candidats = rechercher_commune(city)
            if len(candidats) != 1:
                candidats_repli = rechercher_commune(COMMUNE_NAISSANCE_PAR_DEFAUT)
                if len(candidats_repli) != 1:
                    raise RuntimeError(
                        f"Commune de naissance introuvable ni pour '{city}' ni pour le repli "
                        f"'{COMMUNE_NAISSANCE_PAR_DEFAUT}' (obligatoire pour la fonction {fonction!r}) : "
                        "a completer manuellement sur le portail FFST"
                    )
                candidats = candidats_repli
                if not hasattr(page, "ffst_warnings"):
                    page.ffst_warnings = []
                page.ffst_warnings.append(
                    f"Commune de naissance de {last_name} {first_name} introuvable pour '{city}' : "
                    f"'{COMMUNE_NAISSANCE_PAR_DEFAUT}' utilisee par defaut, a corriger sur le portail "
                    "FFST si besoin."
                )
            page.select_option('[name="A54"]', value=candidats[0]["value"])
            stabiliser()

        remplir('[name="A27"]', postal_code)  # avant l'adresse : declenche une suggestion de ville
        remplir('[name="A24"]', address_line1)
        remplir('[name="A28"]', city)
        if phone:
            # HelloAsso ne fournit qu'un seul numero, sans distinguer
            # fixe/mobile : rempli dans les deux champs (decision produit)
            # pour que la FFST l'accepte quel que soit celui qu'elle exige
            # (obligatoire pour President/Tresorier/Secretaire, voir
            # docstring de create_demande_renouvellement).
            remplir('[name="A29"]', phone)  # Tel. fixe
            remplir('[name="A30"]', phone)  # Tel. mobile
        if email:
            remplir('[name="A31"]', email)


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
