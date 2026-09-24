"""Genere le hash bcrypt d'un mot de passe saisi au clavier, pour
APP_PASSWORD_HASH (voir .env.example) -- le mot de passe en clair n'est
jamais stocke, ni affiche a l'ecran (getpass), ni ecrit en dur dans le
code.

Usage :
    cd backend && source venv/bin/activate && python -m auth.generate_password_hash
    # mot de passe du 2e niveau d'acces (onglet Finances/Comptes) :
    python -m auth.generate_password_hash --accounts
"""

from __future__ import annotations

import argparse
import getpass

import bcrypt

from auth.auth import normalize_password


def main() -> None:
    parser = argparse.ArgumentParser(description="Génère un hash bcrypt pour le fichier .env")
    parser.add_argument(
        "--accounts",
        action="store_true",
        help="hash du mot de passe donnant accès à Finances/Comptes (APP_ACCOUNTS_PASSWORD_HASH)",
    )
    args = parser.parse_args()
    variable = "APP_ACCOUNTS_PASSWORD_HASH" if args.accounts else "APP_PASSWORD_HASH"

    password = getpass.getpass("Mot de passe : ")
    if not password:
        raise SystemExit("Mot de passe vide refusé.")
    confirmation = getpass.getpass("Confirme le mot de passe : ")
    if password != confirmation:
        raise SystemExit("Les 2 saisies ne correspondent pas.")

    # normalize_password (insensible a la casse, voir auth.py) : le hash
    # doit etre genere sur la meme forme que celle comparee au login,
    # sinon la connexion echoue toujours.
    password_hash = bcrypt.hashpw(normalize_password(password).encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    print(f"{variable}={password_hash}")


if __name__ == "__main__":
    main()
