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
from fastapi import Cookie, Depends, HTTPException, Response, status
from itsdangerous import BadSignature, URLSafeTimedSerializer

SESSION_COOKIE_NAME = "session"
SESSION_MAX_AGE_SECONDS = 365 * 24 * 3600  # 1 an

# Identifiant symbolique du seul "utilisateur" actuel (mot de passe
# partage, pas de comptes individuels) -- signe dans le cookie de
# session en lieu et place d'un vrai identifiant.
SHARED_USER_ID = "shared-user"

# 2e niveau d'acces (mot de passe distinct, APP_ACCOUNTS_PASSWORD_HASH) : voit
# en plus les donnees bancaires (module bankaccounts, onglet Finances/Comptes).
# Meme mecanique de cookie que SHARED_USER_ID, seul l'identifiant signe change
# -- require_accounts_auth (plus bas) le distingue.
ACCOUNTS_USER_ID = "accounts-user"


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


def _matches_hash(password: str, env_var: str) -> bool:
    """Compare le mot de passe fourni (normalise, voir normalize_password)
    au hash bcrypt de la variable d'environnement env_var. Echoue "ferme"
    (retourne False, ne leve pas) si cette variable est absente ou si son
    contenu n'est pas un hash bcrypt valide -- une mauvaise configuration ne
    doit jamais se traduire par un acces libre."""
    password_hash = os.environ.get(env_var, "")
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(normalize_password(password).encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def authenticate(password: str) -> str | None:
    """Retourne l'identifiant utilisateur correspondant au mot de passe
    fourni (ACCOUNTS_USER_ID pour le mot de passe "comptes", SHARED_USER_ID
    pour le mot de passe general), ou None s'il ne correspond a aucun.
    Le mot de passe "comptes" est teste en premier : il donne le niveau
    d'acces le plus large."""
    if _matches_hash(password, "APP_ACCOUNTS_PASSWORD_HASH"):
        return ACCOUNTS_USER_ID
    if _matches_hash(password, "APP_PASSWORD_HASH"):
        return SHARED_USER_ID
    return None


def verify_password(password: str) -> bool:
    """True si le mot de passe est valide a l'un des 2 niveaux d'acces."""
    return authenticate(password) is not None


def set_session_cookie(response: Response, user_id: str = SHARED_USER_ID) -> None:
    """Pose le cookie de session apres une authentification reussie
    (user_id : voir authenticate, determine le niveau d'acces)."""
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=_serializer().dumps(user_id),
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


def can_view_accounts(session: str | None) -> bool:
    """True si le cookie de session est valide ET du niveau "comptes"."""
    return _verifier_cookie(session) == ACCOUNTS_USER_ID


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


def require_accounts_auth(user_id: str = Depends(require_auth)) -> str:
    """Dependance FastAPI des routes bancaires (module bankaccounts) : en plus
    d'une session valide (require_auth, 401 sinon), exige le niveau d'acces
    "comptes" (403 sinon). C'est cette verification cote serveur qui protege
    reellement ces donnees -- masquer l'onglet cote frontend n'est que du
    confort d'affichage."""
    if user_id != ACCOUNTS_USER_ID:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès aux comptes non autorisé")
    return user_id
