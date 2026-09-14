"""Genere le hash bcrypt d'un mot de passe saisi au clavier, pour
APP_PASSWORD_HASH (voir .env.example) -- le mot de passe en clair n'est
jamais stocke, ni affiche a l'ecran (getpass), ni ecrit en dur dans le
code.

Usage :
    cd backend && source venv/bin/activate && python -m auth.generate_password_hash
"""

from __future__ import annotations

import getpass

import bcrypt

from auth.auth import normalize_password


def main() -> None:
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
    print(f"APP_PASSWORD_HASH={password_hash}")


if __name__ == "__main__":
    main()
