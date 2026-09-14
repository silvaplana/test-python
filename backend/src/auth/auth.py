"""Authentification simple par mot de passe partage : pas de comptes
individuels, un seul mot de passe connu de quelques utilisateurs.

Le hash bcrypt du mot de passe vient de la variable d'environnement
APP_PASSWORD_HASH (jamais en dur dans le code, voir .env.example) --
genere via `python -m auth.generate_password_hash`.

Session : un cookie signe (itsdangerous), pas de session cote serveur
(pas de base de donnees necessaire) -- sa signature garantit qu'il n'a
pas ete forge/modifie sans connaitre le secret de signature. Ce secret
est APP_PASSWORD_HASH lui-meme (deja un secret haute entropie, pas
besoin d'en gerer un 2eme) : consequence assumee, changer le mot de
passe invalide aussi toutes les sessions en cours, ce qui est le
comportement voulu ici.

require_auth (dependance FastAPI) retourne un identifiant utilisateur
(aujourd'hui toujours SHARED_USER_ID, voir plus bas) plutot que juste un
booleen : le jour d'une vraie gestion multi-utilisateurs, elle pourra
retourner un identifiant/objet utilisateur reel sans que les routes qui
en dependent (Depends(require_auth)) aient a changer.
"""

from __future__ import annotations

import os

import bcrypt
from fastapi import Cookie, HTTPException, Response, status
from itsdangerous import BadSignature, URLSafeTimedSerializer

SESSION_COOKIE_NAME = "session"
SESSION_MAX_AGE_SECONDS = 365 * 24 * 3600  # 1 an

# Identifiant symbolique du seul "utilisateur" actuel (mot de passe
# partage, pas de comptes individuels) -- signe dans le cookie de
# session en lieu et place d'un vrai identifiant.
SHARED_USER_ID = "shared-user"


def _serializer() -> URLSafeTimedSerializer:
    secret = os.environ.get("APP_PASSWORD_HASH", "")
    if not secret:
        raise RuntimeError("APP_PASSWORD_HASH doit être définie (voir .env.example)")
    return URLSafeTimedSerializer(secret, salt="auth-session-cookie")


def normalize_password(password: str) -> str:
    """Mot de passe insensible a la casse (demande explicite) : la
    casse saisie n'a pas a etre memorisee exactement par les quelques
    utilisateurs qui le partagent. Utilisee a la fois ici et par
    generate_password_hash.py -- le hash doit etre genere sur la meme
    forme normalisee que celle comparee ici, sinon rien ne correspond
    jamais (bcrypt compare des octets exacts, pas insensible a la casse
    par lui-meme)."""
    return password.strip().lower()


def verify_password(password: str) -> bool:
    """Compare le mot de passe fourni (normalise, voir
    normalize_password) au hash bcrypt de APP_PASSWORD_HASH. Echoue
    "ferme" (retourne False, ne leve pas) si cette variable est absente
    ou si son contenu n'est pas un hash bcrypt valide -- une mauvaise
    configuration ne doit jamais se traduire par un acces libre."""
    password_hash = os.environ.get("APP_PASSWORD_HASH", "")
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(normalize_password(password).encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def set_session_cookie(response: Response) -> None:
    """Pose le cookie de session apres une authentification reussie."""
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=_serializer().dumps(SHARED_USER_ID),
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        secure=True,
        samesite="strict",
    )


def clear_session_cookie(response: Response) -> None:
    """Supprime le cookie de session (deconnexion)."""
    response.delete_cookie(key=SESSION_COOKIE_NAME)


def _verifier_cookie(session: str | None) -> str | None:
    """Retourne l'identifiant utilisateur si le cookie de session est
    valide (present, signature correcte, pas expire), None sinon."""
    if session is None:
        return None
    try:
        return _serializer().loads(session, max_age=SESSION_MAX_AGE_SECONDS)
    except BadSignature:
        return None


def is_authenticated(session: str | None) -> bool:
    """Utilise par GET /auth/status (voir receiver.py), qui doit pouvoir
    repondre meme sans cookie valide plutot que lever une erreur."""
    return _verifier_cookie(session) is not None


def require_auth(session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME)) -> str:
    """Dependance FastAPI a appliquer a toute route protegee (voir
    app/main.py : appliquee a toutes les routes de l'app sauf /auth/...,
    qui doivent rester accessibles sans etre deja authentifie).

    Leve 401 si le cookie de session est absent/invalide/expire, sinon
    retourne l'identifiant de l'utilisateur authentifie.
    """
    user_id = _verifier_cookie(session)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentification requise")
    return user_id
