# motor

API REST (FastAPI) exposant un moteur via `MotorReceiver` / `MotorModel`, packagée avec `pyproject.toml` et un layout `src/`.

## Structure

```
test-python/
├── pyproject.toml         # métadonnées du package et dépendances
├── src/
│   └── motor/
│       ├── __init__.py
│       ├── model.py        # MotorModel : etat + getMotor()/setMotor()
│       ├── receiver.py      # MotorReceiver : endpoints REST FastAPI GET/POST /motor
│       └── main.py          # point d'entrée : instancie MotorModel/MotorReceiver et lance uvicorn
└── tests/
    └── test_motor.py       # test pytest : POST setMotor("toto") puis GET getMotor
```

## Installation (venv + pip)

```bash
python3 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
```

## Utilisation

```bash
motor
# ou
python -m motor.main
```

Le serveur écoute par défaut sur `http://0.0.0.0:8000`.

- `GET /motor` -> retourne le nom du moteur courant (`MotorModel.getMotor()`)
- `POST /motor` avec body `{"motorName": "toto"}` -> définit le nom du moteur (`MotorModel.setMotor()`)

Exemple :

```bash
curl -X POST http://localhost:8000/motor -H "Content-Type: application/json" -d '{"motorName": "toto"}'
curl http://localhost:8000/motor
```

## Tests

```bash
pytest
```

Le test `tests/test_motor.py` envoie une requête `POST /motor` avec `motorName="toto"`, puis vérifie que `GET /motor` retourne bien `"toto"`.
