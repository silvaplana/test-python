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
