"""Base de donnees SQLite de l'appli (un seul fichier, ex: data/sambo.db).

SQLite plutot que PostgreSQL : un seul serveur, peu de donnees, pas de
conteneur ni de mot de passe en plus -- sauvegarder la base revient a copier
ce fichier. Il vit dans le volume Docker (/app/data, voir docker-compose.yml)
sous peine d'etre perdu a chaque redeploiement.

Evolutions du schema : la liste MIGRATIONS ci-dessous, appliquee dans l'ordre
au demarrage (Database.migrate). Le numero de la derniere migration appliquee
est memorise dans la base elle-meme (PRAGMA user_version). Ne jamais modifier
une migration deja deployee : en ajouter une nouvelle a la fin.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

MIGRATIONS: list[str] = [
    # 1 : eleves en cours d'essai (voir trials/trials.py). Une ligne par
    # eleve, 2 cours d'essai au maximum (colonnes course1_* / course2_*).
    # Dates au format AAAA-MM-JJ, horodatages ISO 8601 (UTC).
    """
    CREATE TABLE trial_students (
        id INTEGER PRIMARY KEY,
        first_name TEXT NOT NULL,
        last_name TEXT NOT NULL,
        birth_date TEXT,
        gender TEXT,
        email TEXT,
        phone TEXT,
        parent_name TEXT,
        medical_attestation INTEGER NOT NULL DEFAULT 0,
        medical_certificate_file TEXT,
        parental_consent INTEGER NOT NULL DEFAULT 0,
        waiver_accepted INTEGER NOT NULL DEFAULT 0,
        signature_png BLOB,
        signed_at TEXT,
        signed_ip TEXT,
        terms_version TEXT,
        qr_token TEXT UNIQUE,
        qr_created_at TEXT,
        course1_date TEXT,
        course1_mode TEXT,
        course2_date TEXT,
        course2_mode TEXT,
        comment TEXT NOT NULL DEFAULT '',
        source TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX trial_students_email ON trial_students (lower(email));
    """,
    # 2 : inscription de plusieurs personnes d'une meme famille en une seule
    # demande (family_id commun, un QR code par personne) et age declare a
    # l'inscription (la date de naissance n'est plus demandee).
    """
    ALTER TABLE trial_students ADD COLUMN age INTEGER;
    ALTER TABLE trial_students ADD COLUMN family_id TEXT;
    CREATE INDEX trial_students_family ON trial_students (family_id);
    """,
    # 3 : signatures d'une demande d'inscription (family_id) : celle de la
    # 1re personne inscrite et celle de chaque representant legal exterieur
    # (parent d'un mineur qui n'est pas la 1re personne). role : "first",
    # "parent" ou "adult" (majeur de la famille signant lui-meme quand la 1re
    # personne est mineure).
    """
    CREATE TABLE trial_signatures (
        id INTEGER PRIMARY KEY,
        family_id TEXT NOT NULL,
        signer_name TEXT NOT NULL,
        role TEXT NOT NULL,
        png BLOB NOT NULL,
        signed_at TEXT NOT NULL,
        signed_ip TEXT
    );
    CREATE INDEX trial_signatures_family ON trial_signatures (family_id);
    """,
    # 4 : historique des comptes bancaires lu dans les releves PDF (voir
    # bankstatements/). Une seule table d'operations pour tous les comptes
    # (colonne account_id) : total, tableau et graphique communs = simple tri
    # par date. Montants en centimes (entiers, signes : < 0 = debit).
    # transfer_id : operation jumelle dans l'autre compte quand c'est un
    # virement entre les comptes du club (ne change pas le total).
    # source : "releve" (lue dans un releve PDF, statement_id renseigne) ou
    # "banque" (recuperee par la connexion bancaire apres le dernier releve,
    # provisoire : remplacee par le releve quand il est importe).
    """
    CREATE TABLE bank_accounts (
        id INTEGER PRIMARY KEY,
        number TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        kind TEXT NOT NULL
    );
    CREATE TABLE bank_statements (
        id INTEGER PRIMARY KEY,
        account_id INTEGER NOT NULL REFERENCES bank_accounts (id),
        start_date TEXT NOT NULL,
        start_balance INTEGER NOT NULL,
        end_date TEXT NOT NULL,
        end_balance INTEGER NOT NULL,
        file_name TEXT NOT NULL,
        imported_at TEXT NOT NULL,
        UNIQUE (account_id, start_date, end_date)
    );
    CREATE TABLE bank_operations (
        id INTEGER PRIMARY KEY,
        account_id INTEGER NOT NULL REFERENCES bank_accounts (id),
        statement_id INTEGER REFERENCES bank_statements (id) ON DELETE CASCADE,
        source TEXT NOT NULL DEFAULT 'releve',
        position INTEGER NOT NULL,
        date TEXT NOT NULL,
        value_date TEXT NOT NULL,
        label TEXT NOT NULL,
        details TEXT NOT NULL DEFAULT '',
        amount INTEGER NOT NULL,
        transfer_id INTEGER REFERENCES bank_operations (id) ON DELETE SET NULL
    );
    CREATE INDEX bank_operations_date ON bank_operations (date);
    """,
    # 5 : saisons du club (voir seasons/), ex "2026-2027" du 01/07/2026 au
    # 30/06/2027. end_balance : solde de fin de saison (compte courant +
    # Livret Bleu cumules) en centimes ; NULL = calcule depuis l'historique
    # des comptes (bankstatements), sinon saisi a la main.
    # ai_cost : cout cumule de l'API d'IA sur la saison, en centimes.
    """
    CREATE TABLE seasons (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        start_date TEXT NOT NULL,
        end_date TEXT NOT NULL,
        licences INTEGER,
        end_balance INTEGER,
        ai_cost INTEGER,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """,
    # 6 : bilans financiers d'une saison (voir financialreports/). Plusieurs
    # calculs par saison, chacun avec son etat (brouillon, valide, officiel :
    # un seul officiel par saison), le prompt donne a l'IA, le dernier modele
    # utilise et le cout cumule de l'IA en euros (REAL : quelques centimes par
    # calcul). result : JSON du dernier calcul (tableau + analyse). status :
    # "idle", "running" (calcul en cours, lance a run_started_at) ou "error".
    # Supprimer la saison supprime ses bilans.
    """
    CREATE TABLE financial_reports (
        id INTEGER PRIMARY KEY,
        season_id INTEGER NOT NULL REFERENCES seasons (id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        state TEXT NOT NULL DEFAULT 'brouillon',
        prompt TEXT NOT NULL DEFAULT '',
        model TEXT NOT NULL,
        ai_cost REAL NOT NULL DEFAULT 0,
        result TEXT,
        status TEXT NOT NULL DEFAULT 'idle',
        error TEXT,
        run_started_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX financial_reports_season ON financial_reports (season_id);
    """,
    # 7 : assemblees generales d'une saison (voir generalassemblies/) :
    # calculs de PPT d'AG, memes champs que les bilans (etat, prompt, modele,
    # cout de l'IA cumule en euros, status du calcul). result : JSON du
    # dernier calcul (bilan et modele utilises, diapos modifiees, alertes).
    # Les PPT sont des versions (general_assembly_versions) : origin
    # "genere" (calcul) ou "envoye" (PPT modifie par le tresorier), fichier
    # <dossier des AG>/<assembly_id>/v<number>.pptx.
    """
    CREATE TABLE general_assemblies (
        id INTEGER PRIMARY KEY,
        season_id INTEGER NOT NULL REFERENCES seasons (id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        state TEXT NOT NULL DEFAULT 'brouillon',
        prompt TEXT NOT NULL DEFAULT '',
        model TEXT NOT NULL,
        ai_cost REAL NOT NULL DEFAULT 0,
        result TEXT,
        status TEXT NOT NULL DEFAULT 'idle',
        error TEXT,
        run_started_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX general_assemblies_season ON general_assemblies (season_id);
    CREATE TABLE general_assembly_versions (
        id INTEGER PRIMARY KEY,
        assembly_id INTEGER NOT NULL REFERENCES general_assemblies (id) ON DELETE CASCADE,
        number INTEGER NOT NULL,
        origin TEXT NOT NULL,
        filename TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE (assembly_id, number)
    );
    """,
    # 8 : previsionnels d'une saison (voir forecasts/). Plusieurs par saison,
    # memes champs que les bilans (etat, prompt, modele, cout de l'IA cumule
    # en euros, status du calcul) plus start_date (date de depart du
    # previsionnel, NULL : dernier jour connu des comptes) et params (JSON :
    # derniere position des curseurs). result : JSON du dernier calcul
    # (formule Python ecrite par l'IA, explication, parametres declares,
    # donnees utilisees, courbe prevue).
    """
    CREATE TABLE forecasts (
        id INTEGER PRIMARY KEY,
        season_id INTEGER NOT NULL REFERENCES seasons (id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        state TEXT NOT NULL DEFAULT 'brouillon',
        prompt TEXT NOT NULL DEFAULT '',
        model TEXT NOT NULL,
        start_date TEXT,
        ai_cost REAL NOT NULL DEFAULT 0,
        result TEXT,
        params TEXT,
        status TEXT NOT NULL DEFAULT 'idle',
        error TEXT,
        run_started_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX forecasts_season ON forecasts (season_id);
    """,
    # 9 : provenance d'un PPT d'assemblee generale (voir generalassemblies/),
    # affichee pour le PPT modele : fichier importe, copie du PPT d'un autre
    # calcul, modele par defaut... NULL : inconnue (PPT d'avant).
    """
    ALTER TABLE general_assembly_versions ADD COLUMN source TEXT;
    """,
    # 10 : previsionnel, zone "Explication du résultat de l'IA" depliee (1)
    # ou repliee (0) dans l'ecran -- retenu par previsionnel.
    """
    ALTER TABLE forecasts ADD COLUMN explanation_open INTEGER NOT NULL DEFAULT 1;
    """,
    # 11 : bilans et assemblees generales, zone "Réglages de l'IA" (prompt,
    # modele, cout) depliee (1) ou repliee (0) dans l'ecran -- par calcul.
    """
    ALTER TABLE financial_reports ADD COLUMN settings_open INTEGER NOT NULL DEFAULT 1;
    ALTER TABLE general_assemblies ADD COLUMN settings_open INTEGER NOT NULL DEFAULT 1;
    """,
    # 12 : previsionnels, meme zone "Réglages de l'IA" depliee ou repliee.
    """
    ALTER TABLE forecasts ADD COLUMN settings_open INTEGER NOT NULL DEFAULT 1;
    """,
    # 13 : journal des mails envoyes aux adherents (voir helloasso/mails.py).
    # member_id : identifiant HelloAsso de l'adhesion (les adherents ne sont
    # pas en base) ; nom et adresse copies au moment de l'envoi. status :
    # "envoye" ou "echec" (error : la raison).
    """
    CREATE TABLE member_mails (
        id INTEGER PRIMARY KEY,
        member_id INTEGER NOT NULL,
        first_name TEXT NOT NULL,
        last_name TEXT NOT NULL,
        to_email TEXT NOT NULL,
        cc TEXT,
        sender TEXT,
        subject TEXT NOT NULL,
        body TEXT NOT NULL,
        status TEXT NOT NULL,
        error TEXT,
        sent_at TEXT NOT NULL
    );
    CREATE INDEX member_mails_member ON member_mails (member_id);
    """,
    # 14 : journal des SMS prepares pour les adherents (voir
    # helloasso/mails.py). Le SMS part de l'appli SMS du telephone de
    # l'utilisateur : l'appli sait qu'il a ete prepare, pas qu'il est parti.
    """
    CREATE TABLE member_sms (
        id INTEGER PRIMARY KEY,
        member_id INTEGER NOT NULL,
        first_name TEXT NOT NULL,
        last_name TEXT NOT NULL,
        phone TEXT NOT NULL,
        body TEXT NOT NULL,
        sent_at TEXT NOT NULL
    );
    CREATE INDEX member_sms_member ON member_sms (member_id);
    """,
    # 15 : verification par IA du dossier de chaque adherent (voir
    # helloasso/verification.py). member_id : identifiant HelloAsso de
    # l'adhesion. status : "ok", "probleme" ou "erreur" ; issues : raisons
    # (liste JSON) ; manual : valide a la main ; cost : cout cumule de l'IA
    # pour cet adherent, en euros (le total des lignes = cout de toutes les
    # verifications).
    """
    CREATE TABLE member_checks (
        member_id INTEGER PRIMARY KEY,
        first_name TEXT NOT NULL,
        last_name TEXT NOT NULL,
        status TEXT NOT NULL,
        issues TEXT NOT NULL,
        manual INTEGER NOT NULL DEFAULT 0,
        model TEXT,
        cost REAL NOT NULL DEFAULT 0,
        checked_at TEXT NOT NULL
    );
    """,
    # 16 : prompts enregistres d'un bilan financier (voir financialreports/) :
    # la disquette a cote du prompt l'ajoute a la liste du bilan, reproposee
    # dans un menu deroulant. Propres a chaque bilan ; supprimer le bilan
    # supprime ses prompts.
    """
    CREATE TABLE financial_report_prompts (
        id INTEGER PRIMARY KEY,
        report_id INTEGER NOT NULL REFERENCES financial_reports (id) ON DELETE CASCADE,
        prompt TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE INDEX financial_report_prompts_report ON financial_report_prompts (report_id);
    """,
    # 17 : ordre d'affichage fige des cartes d'une saison (voir
    # database/ordering.py) : position, la plus petite en premier. Jusqu'ici
    # les cartes etaient triees par date de modification (la carte modifiee
    # remontait en tete) : chaque saison garde l'ordre affiche au moment de la
    # migration.
    """
    ALTER TABLE financial_reports ADD COLUMN position INTEGER NOT NULL DEFAULT 0;
    UPDATE financial_reports SET position = (
        SELECT COUNT(*) FROM financial_reports AS other
        WHERE other.season_id = financial_reports.season_id
          AND (other.updated_at > financial_reports.updated_at
               OR (other.updated_at = financial_reports.updated_at AND other.id > financial_reports.id))
    );
    ALTER TABLE general_assemblies ADD COLUMN position INTEGER NOT NULL DEFAULT 0;
    UPDATE general_assemblies SET position = (
        SELECT COUNT(*) FROM general_assemblies AS other
        WHERE other.season_id = general_assemblies.season_id
          AND (other.updated_at > general_assemblies.updated_at
               OR (other.updated_at = general_assemblies.updated_at AND other.id > general_assemblies.id))
    );
    ALTER TABLE forecasts ADD COLUMN position INTEGER NOT NULL DEFAULT 0;
    UPDATE forecasts SET position = (
        SELECT COUNT(*) FROM forecasts AS other
        WHERE other.season_id = forecasts.season_id
          AND (other.updated_at > forecasts.updated_at
               OR (other.updated_at = forecasts.updated_at AND other.id > forecasts.id))
    );
    """,
    # 18 : prompts enregistres d'une assemblee generale et d'un previsionnel,
    # comme ceux d'un bilan financier (migration 16, voir database/prompts.py).
    # Propres a chaque calcul ; le supprimer supprime ses prompts.
    """
    CREATE TABLE general_assembly_prompts (
        id INTEGER PRIMARY KEY,
        assembly_id INTEGER NOT NULL REFERENCES general_assemblies (id) ON DELETE CASCADE,
        prompt TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE INDEX general_assembly_prompts_assembly ON general_assembly_prompts (assembly_id);
    CREATE TABLE forecast_prompts (
        id INTEGER PRIMARY KEY,
        forecast_id INTEGER NOT NULL REFERENCES forecasts (id) ON DELETE CASCADE,
        prompt TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE INDEX forecast_prompts_forecast ON forecast_prompts (forecast_id);
    """,
    # 19 : messages preenregistres pour ecrire aux adherents (voir
    # helloasso/mails.py, MessageTemplates) : kind "mail" (objet + corps) ou
    # "sms" (corps seul). Communs a tous les adherents ; le corps peut contenir
    # {prénom} et {nom}, remplaces par ceux de l'adherent a qui l'on ecrit.
    """
    CREATE TABLE member_message_templates (
        id INTEGER PRIMARY KEY,
        kind TEXT NOT NULL,
        subject TEXT NOT NULL DEFAULT '',
        body TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE INDEX member_message_templates_kind ON member_message_templates (kind);
    """,
]


class Database:
    """Acces a la base SQLite : une connexion par operation (voir connect),
    suffisant pour le trafic de l'appli et sans souci de partage entre les
    threads de FastAPI."""

    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Connexion dont les lignes se lisent comme des dict (row["nom"]).
        Transaction validee a la sortie du bloc, annulee sur exception."""
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def migrate(self) -> None:
        """Applique les migrations pas encore passees (voir MIGRATIONS)."""
        with self.connect() as connection:
            # WAL : les lectures ne bloquent pas pendant une ecriture.
            connection.execute("PRAGMA journal_mode = WAL")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
        for number, script in enumerate(MIGRATIONS[version:], start=version + 1):
            with self.connect() as connection:
                connection.executescript(f"BEGIN; {script}; PRAGMA user_version = {number}; COMMIT;")
