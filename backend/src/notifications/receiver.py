from fastapi import FastAPI
from pydantic import BaseModel

from .notifications import PushNotifications


class PushSubscriptionKeys(BaseModel):
    p256dh: str
    auth: str


class PushSubscriptionRequest(BaseModel):
    """Corps de POST /notifications/subscribe et /notifications/unsubscribe :
    correspond exactement a PushSubscription.toJSON() cote navigateur
    (voir PushManager.subscribe() dans le frontend)."""

    endpoint: str
    keys: PushSubscriptionKeys | None = None


class NotificationsReceiver:
    """Recoit les requetes REST (FastAPI) et delegue a PushNotifications.

    Comme les autres receivers, enregistre ses routes sur une app FastAPI
    existante (partagee avec les autres modules), pas de service dedie.
    """

    def __init__(self, client: PushNotifications, app: FastAPI) -> None:
        self.client = client
        self.app = app
        self._register_routes()

    def _register_routes(self) -> None:
        self.app.get("/notifications/vapid_public_key")(self.getVapidPublicKey)
        self.app.post("/notifications/subscribe")(self.subscribe)
        self.app.post("/notifications/unsubscribe")(self.unsubscribe)

    def getVapidPublicKey(self) -> dict:
        """Endpoint REST GET /notifications/vapid_public_key. Retourne la
        cle publique VAPID du club, necessaire cote frontend pour
        PushManager.subscribe({applicationServerKey: ...})."""
        return {"publicKey": self.client.get_public_key()}

    def subscribe(self, request: PushSubscriptionRequest) -> dict:
        """Endpoint REST POST /notifications/subscribe. Enregistre un
        abonnement push (apres acceptation de la permission navigateur,
        voir l'onglet Profil du frontend)."""
        self.client.add_subscription(request.model_dump())
        return {"status": "ok"}

    def unsubscribe(self, request: PushSubscriptionRequest) -> dict:
        """Endpoint REST POST /notifications/unsubscribe. Retire un
        abonnement push (desactivation depuis l'onglet Profil)."""
        self.client.remove_subscription(request.endpoint)
        return {"status": "ok"}
