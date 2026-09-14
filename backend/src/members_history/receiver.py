from fastapi import APIRouter, FastAPI

from .members_history import MembersHistory


class MembersHistoryReceiver:
    """Recoit les requetes REST (FastAPI) et delegue a MembersHistory.

    Comme les autres receivers, enregistre ses routes sur une app FastAPI
    existante (partagee avec les autres modules), pas de service dedie.
    En realite le routeur protege par require_auth (voir app/main.py),
    d'ou FastAPI | APIRouter (meme interface .get/.post/.delete).
    """

    def __init__(self, client: MembersHistory, app: FastAPI | APIRouter) -> None:
        self.client = client
        self.app = app
        self._register_routes()

    def _register_routes(self) -> None:
        self.app.get("/members_history")(self.getMembersHistory)

    def getMembersHistory(self) -> list[dict]:
        """Endpoint REST GET /members_history. Retourne l'historique des
        adherents (payeurs) du club, toutes saisons confondues (un fichier
        statique embarque dans le backend, voir MembersHistory)."""
        return self.client.get_history()
