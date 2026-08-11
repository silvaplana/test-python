import uvicorn

from .model import MotorModel
from .receiver import MotorReceiver

model = MotorModel()
receiver = MotorReceiver(model)

# instance FastAPI exposee pour uvicorn / TestClient
app = receiver.app


def main() -> None:
    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
