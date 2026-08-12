"""Point d'entree unique du backend : assemble les differents modules
(motor, helloasso, ...) sur une seule app FastAPI / un seul service HTTP.

N'appartient a aucun des modules qu'il assemble (voir DEPLOY.md :
un seul conteneur "backend" pour tout le projet).
"""

import os

import uvicorn
from dotenv import load_dotenv

from helloasso import HelloAsso, HelloAssoReceiver
from motor import MotorModel, MotorReceiver

load_dotenv()  # charge backend/.env si present (variables HELLOASSO_*)

model = MotorModel()
receiver = MotorReceiver(model)

# instance FastAPI exposee pour uvicorn / TestClient
app = receiver.app

# Monte les routes HelloAsso (/helloasso/members, /helloasso/unpaid) sur la
# meme app : un seul service HTTP pour tout le backend (voir DEPLOY.md).
helloasso_client = HelloAsso(
    client_id=os.environ.get("HELLOASSO_CLIENT_ID", ""),
    client_secret=os.environ.get("HELLOASSO_CLIENT_SECRET", ""),
    organization_slug=os.environ.get("HELLOASSO_ORGANIZATION_SLUG"),
    sandbox=os.environ.get("HELLOASSO_SANDBOX", "").lower() in ("1", "true", "yes"),
)
helloasso_receiver = HelloAssoReceiver(
    client=helloasso_client,
    app=app,
    form_slug=os.environ.get(
        "HELLOASSO_FORM_SLUG", "rejoignez-notre-club-de-sambo-mma-pour-la-saison-2025-2026"
    ),
)


def main() -> None:
    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
