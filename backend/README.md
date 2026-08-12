# backend

API REST (FastAPI) packagée avec `pyproject.toml` et un layout `src/`. Un
seul point d'entrée (`app.main`) assemble plusieurs modules sur la même
app FastAPI :

- **motor** : `MotorReceiver` / `MotorModel` (`GET`/`POST /motor`)
- **helloasso** : client API HelloAsso (`GET /helloasso/campaign`,
  `/helloasso/members`, `/helloasso/unpaid`) — voir
  `src/helloasso/helloasso.py` pour le detail des methodes et
  `.env.example` pour la config requise.
- **ffst** : scraping du portail de licences FFST (`GET /ffst/licences`,
  `GET /ffst/demandes`, pas d'API — parsing d'un bloc XML integre a la
  page HTML) — voir `src/ffst/ffst.py`.

## Structure

```
backend/
├── pyproject.toml
├── .env.example            # variables HELLOASSO_* et FFST_* attendues
├── src/
│   ├── app/
│   │   └── main.py         # point d'entrée : assemble motor + helloasso sur une app FastAPI, lance uvicorn
│   ├── motor/
│   │   ├── __init__.py
│   │   ├── model.py        # MotorModel : etat + getMotor()/setMotor()
│   │   └── receiver.py     # MotorReceiver : endpoints REST FastAPI GET/POST /motor
│   ├── helloasso/
│   │   ├── __init__.py
│   │   ├── helloasso.py    # HelloAsso : client OAuth2 + appels API (organisation, formulaires, commandes)
│   │   └── receiver.py     # HelloAssoReceiver : endpoints REST FastAPI /helloasso/...
│   └── ffst/
│       ├── __init__.py
│       ├── ffst.py         # Ffst : connexion WEBDEV + parsing XML des licences
│       └── receiver.py     # FfstReceiver : endpoints REST FastAPI /ffst/licences, /ffst/demandes
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
app
# ou
python -m app.main
```

Le serveur écoute par défaut sur `http://0.0.0.0:8000`.

- `GET /motor` -> retourne le nom du moteur courant (`MotorModel.getMotor()`)
- `POST /motor` avec body `{"motorName": "toto"}` -> définit le nom du moteur (`MotorModel.setMotor()`)
- `GET /helloasso/campaign` -> titre de la campagne d'adhésion configurée (`HELLOASSO_FORM_SLUG`)
- `GET /helloasso/members` -> liste des adhérents de cette campagne
- `GET /helloasso/unpaid` -> adhérents avec au moins un paiement refusé
- `GET /ffst/licences` -> liste des licences FFST du club (saison en cours)
- `GET /ffst/demandes` -> demandes de nouvelle licence / renouvellement en cours (liste vide = cas normal)

Exemple :

```bash
curl -X POST http://localhost:8000/motor -H "Content-Type: application/json" -d '{"motorName": "toto"}'
curl http://localhost:8000/motor
curl http://localhost:8000/helloasso/members
curl http://localhost:8000/ffst/licences
```

## Tests

```bash
pytest
```

Le test `tests/test_motor.py` envoie une requête `POST /motor` avec `motorName="toto"`, puis vérifie que `GET /motor` retourne bien `"toto"`.
