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
  `GET /ffst/demandes_validated`, `GET /ffst/demandes_draft`, pas d'API —
  parsing d'un bloc XML integre a la page HTML) + `POST
  /ffst/demandes_renouvellement` pour soumettre une demande de
  renouvellement (pilote un vrai navigateur Playwright, voir
  `Ffst.create_demande_renouvellement`) — voir `src/ffst/ffst.py`.
- **financialbalance** : upload de l'archive des relevés bancaires
  (`POST /financialbalance/archives`) puis analyse IA (Claude, via l'API
  Anthropic) en flux Server-Sent Events (`GET /financialbalance/analysis`)
  — résumé synthétique + ventilation par catégorie. Voir
  `src/financialbalance/financialbalance.py` et `ANTHROPIC_API_KEY` dans
  `.env.example`.

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
│   ├── ffst/
│   │   ├── __init__.py
│   │   ├── ffst.py         # Ffst : connexion WEBDEV + parsing XML des licences
│   │   └── receiver.py     # FfstReceiver : endpoints REST FastAPI /ffst/licences, /ffst/demandes_validated, /ffst/demandes_draft, /ffst/demandes_renouvellement
│   └── financialbalance/
│       ├── __init__.py
│       ├── financialbalance.py  # FinancialBalance : stockage archives + analyse IA (Claude)
│       └── receiver.py          # FinancialBalanceReceiver : endpoints /financialbalance/archives, /analysis (SSE)
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
- `GET /ffst/demandes_validated` -> demandes de nouvelle licence / renouvellement en cours (liste vide = cas normal)
- `GET /ffst/demandes_draft` -> demandes en brouillon, pas encore validées/soumises (le "panier" du portail ; liste vide = cas normal)
- `POST /ffst/demandes_renouvellement` avec body `{"lastName": "...", "firstName": "..."}` -> soumet une demande de renouvellement pour un ancien licencié du club (doit être identifiable de façon non ambiguë) ; la place dans `/ffst/demandes_draft` sans déclencher de facturation (celle-ci n'intervient qu'à la validation, manuelle, sur le portail)
- `POST /financialbalance/archives` (multipart, champ `file`) -> stocke une archive `.zip` de relevés bancaires
- `GET /financialbalance/analysis` -> flux SSE : progression puis bilan IA (résumé + tableau par catégorie) de la dernière archive envoyée

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
