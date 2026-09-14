from fastapi import Cookie, FastAPI, HTTPException, Response
from pydantic import BaseModel

from .auth import SESSION_COOKIE_NAME, clear_session_cookie, is_authenticated, set_session_cookie, verify_password


class LoginRequest(BaseModel):
    """Corps de POST /auth/login."""

    password: str


class AuthReceiver:
    """Recoit les requetes REST (FastAPI) et delegue a auth.py.

    Contrairement aux autres receivers de ce backend, enregistre ses
    routes directement sur l'app (jamais sur le routeur protege par
    require_auth, voir app/main.py) : il faut pouvoir les appeler
    justement quand on n'est PAS encore authentifie.
    """

    def __init__(self, app: FastAPI) -> None:
        self.app = app
        self._register_routes()

    def _register_routes(self) -> None:
        self.app.post("/auth/login")(self.login)
        self.app.post("/auth/logout")(self.logout)
        self.app.get("/auth/status")(self.status)

    def login(self, request: LoginRequest, response: Response) -> dict:
        """Endpoint REST POST /auth/login. Verifie le mot de passe fourni
        et pose le cookie de session s'il est correct.

        Message d'erreur generique en cas d'echec (pas de detail sur ce
        qui est faux -- il n'y a qu'un seul champ de toute facon)."""
        if not verify_password(request.password):
            raise HTTPException(status_code=401, detail="Mot de passe incorrect")
        set_session_cookie(response)
        return {"status": "ok"}

    def logout(self, response: Response) -> dict:
        """Endpoint REST POST /auth/logout. Supprime le cookie de
        session."""
        clear_session_cookie(response)
        return {"status": "ok"}

    def status(self, session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME)) -> dict:
        """Endpoint REST GET /auth/status. Indique si la requete porte un
        cookie de session valide -- jamais d'erreur 401 ici (contrairement
        a require_auth) : le frontend l'appelle justement pour savoir s'il
        doit afficher le formulaire de mot de passe ou l'application."""
        return {"authenticated": is_authenticated(session)}
