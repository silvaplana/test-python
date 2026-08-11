from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .model import MotorModel


class MotorRequest(BaseModel):
    """Corps de la requete POST /motor."""

    motorName: str


class MotorReceiver:
    """Recoit les requetes REST (FastAPI) et delegue a MotorModel."""

    def __init__(self, model: MotorModel) -> None:
        self.model = model
        self.app = FastAPI(title="Motor API")
        self._register_cors()
        self._register_routes()

    def _register_cors(self) -> None:
        # Autorise le frontend React (Vite, servi sur un autre port) a appeler l'API.
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )

    def _register_routes(self) -> None:
        self.app.get("/motor")(self.getMotor)
        self.app.post("/motor")(self.setMotor)

    def getMotor(self) -> str:
        """Endpoint REST GET /motor. Retourne MotorModel.getMotor()."""
        return self.model.getMotor()

    def setMotor(self, request: MotorRequest) -> None:
        """Endpoint REST POST /motor. Fait MotorModel.setMotor(motorName)."""
        self.model.setMotor(request.motorName)
