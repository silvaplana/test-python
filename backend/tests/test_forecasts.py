"""Tests des previsionnels (Finances > Prévisionnel) : donnees preparees pour
la formule, verification et execution a part de la formule ecrite par l'IA
(simulee ici), curseurs, etats, cout de l'IA et telechargements.
Lancer depuis backend/ : PYTHONPATH=src venv/bin/python -m pytest tests"""

from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bankstatements import BankStatements
from database import Database
from financialreports.ai import AnalysisError
from forecasts import ForecastError, Forecasts, ForecastsReceiver
from forecasts import data as forecast_data
from forecasts.forecasts import ForecastNotFoundError
from forecasts.ai import Formula, defaults
from forecasts.sandbox import FormulaError, check, run
from seasons import Seasons

TODAY = date(2026, 10, 6)

CODE = '''
import math

def prevoir(donnees, p):
    """Salaire chaque mois, cotisations des nouveaux adherents."""
    solde = donnees["soldeDepart"]
    points = []
    for semaine in donnees["semaines"]:
        for mois in semaine["mois_commences"]:
            solde -= p["salaire"]
            solde += p["nouveaux"] * 10
        points.append({"date": semaine["date"], "solde": round(solde, 2)})
    return points
'''
PARAMETERS = [
    {"name": "salaire", "label": "Salaire mensuel", "min": 0, "max": 2000, "default": 1000, "step": 10, "unit": "€"},
    {"name": "nouveaux", "label": "Nouveaux adhérents", "min": 0, "max": 20, "default": 5, "step": 1, "unit": ""},
]


@pytest.fixture
def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    database.migrate()
    with database.connect() as connection:
        connection.execute("INSERT INTO bank_accounts (id, number, name, kind) VALUES (1, '01', 'Compte courant', 'checking')")
        connection.execute("INSERT INTO bank_accounts (id, number, name, kind) VALUES (2, '02', 'Livret Bleu', 'savings')")
        connection.execute("INSERT INTO bank_statements VALUES (1, 1, '2025-06-01', 100000, '2026-10-05', 0, 'cc.pdf', 'x')")
        connection.execute("INSERT INTO bank_statements VALUES (2, 2, '2025-06-01', 300000, '2026-10-05', 0, 'bleu.pdf', 'x')")
        operations = [
            (1, "2025-07-31", "VIR SALAIRE JUILLET", -60000),
            (1, "2025-09-15", "VIR STRIPE TECHNOLOGY", 600000),
            (1, "2026-07-31", "VIR SALAIRE JUILLET", -60000),
            (1, "2026-09-15", "VIR STRIPE TECHNOLOGY", 300000),
            (1, "2026-10-02", "VIR SALAIRE SEPTEMBRE", -58000),
        ]
        for position, (account, day, label, amount) in enumerate(operations):
            connection.execute(
                """INSERT INTO bank_operations (account_id, statement_id, position, date, value_date, label, amount)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (account, account, position, day, day, label, amount),
            )
    return database


@pytest.fixture
def seasons(db):
    client = Seasons(db=db, ledger=BankStatements(db).get_ledger, today=lambda: TODAY)
    client.create({"name": "2025-2026", "startDate": "2025-07-01", "endDate": "2026-06-30"})
    client.create({"name": "2026-2027", "startDate": "2026-07-01", "endDate": "2027-06-30"})
    return client


class FakeCoder:
    """IA simulee : renvoie toujours la meme formule, executee pour de vrai."""

    def __init__(self, code=CODE, error=None):
        self.code = code
        self.error = error
        self.calls = []

    def write(self, model, data, prompt):
        self.calls.append((model, data, prompt))
        if self.error:
            raise AnalysisError(self.error, cost=0.01)
        return Formula(
            code=self.code,
            explanation="Salaire chaque mois.",
            parameters=PARAMETERS,
            balances=run(self.code, data, defaults(PARAMETERS)),
            model=model,
            served_by="claude-sonnet-5-5",
            cost=0.05,
        )


def make_forecasts(db, seasons, coder, members=None):
    return Forecasts(
        db=db,
        ledger=BankStatements(db).get_ledger,
        seasons=lambda: seasons.get_seasons()["seasons"],
        add_season_ai_cost=seasons.add_ai_cost,
        members=members,
        today=lambda: TODAY,
        coder=coder,
        background=False,
    )


def season_id(seasons, name):
    return next(s["id"] for s in seasons.get_seasons()["seasons"] if s["name"] == name)


# ----- formule -----


@pytest.mark.parametrize(
    "code, message",
    [
        ("import os\ndef prevoir(d, p):\n    return []", "Import interdit : os"),
        ("from subprocess import run\ndef prevoir(d, p):\n    return []", "Import interdit"),
        ("def prevoir(d, p):\n    return open('/etc/passwd').read()", "Nom interdit"),
        ("def prevoir(d, p):\n    return ().__class__", "Attribut interdit"),
        ("def prevoir(d, p):\n    return __builtins__", "Nom interdit"),
        # Remontee aux variables du programme lanceur par un generateur.
        ("def prevoir(d, p):\n    g = (x for x in [1])\n    return g.gi_frame", "Attribut interdit dans la formule : gi_frame"),
        ("def prevoir(d, p):\n    return d.f_back.f_globals", "Attribut interdit dans la formule : f_"),
        ("def prevoir(d, p):\n    return '{0.real}'.format(1)", "Attribut interdit dans la formule : format"),
        ("def calcul(d, p):\n    return []", "prevoir"),
        ("def prevoir(d, p)\n    return []", "illisible"),
    ],
)
def test_check_refuses_dangerous_code(code, message):
    with pytest.raises(FormulaError, match=message):
        check(code)


def test_run_executes_in_separate_process():
    data = {"soldeDepart": 1000.0, "semaines": [{"date": "2026-10-13", "mois_commences": []}, {"date": "2026-10-20", "mois_commences": []}]}
    code = "import math\ndef prevoir(d, p):\n    return [d['soldeDepart'] + math.floor(p['x']) * i for i in range(len(d['semaines']))]"
    assert run(code, data, {"x": 10.7}) == [1000.0, 1010.0]


def test_run_reports_errors_and_wrong_sizes():
    data = {"soldeDepart": 0.0, "semaines": [{"date": "2026-10-13", "mois_commences": []}]}
    with pytest.raises(FormulaError, match="ZeroDivisionError"):
        run("def prevoir(d, p):\n    return [1 / 0]", data, {})
    with pytest.raises(FormulaError, match="une valeur par semaine"):
        run("def prevoir(d, p):\n    return [1, 2]", data, {})
    with pytest.raises(FormulaError, match="Solde invalide"):
        run("def prevoir(d, p):\n    return ['beaucoup']", data, {})
    # Un import cache dans la fonction est refuse aussi.
    with pytest.raises(FormulaError, match="Import interdit : socket"):
        run("def prevoir(d, p):\n    import socket\n    return [0]", data, {})


# Formule hostile : par un generateur, remonte aux variables du programme
# lanceur (sys, builtins), puis tente ACTION avec ce qu'elle y trouve.
ESCAPE = """
def prevoir(donnees, p):
    cadre = [0]
    def lire():
        g = (g.gi_frame.f_back.f_back for x in [1])
        for f in g:
            cadre[0] = f
    lire()
    f = cadre[0]
    while "sys" not in f.f_globals:
        f = f.f_back
    systeme = f.f_globals["sys"]
    integrees = f.f_globals["builtins"]
    ACTION
    return [1.0]
"""


@pytest.mark.parametrize(
    "action",
    [
        'integrees.open("/etc/hostname").read()',
        'systeme.modules["os"].system("true")',
        'systeme.modules["os"].listdir("/")',
        'integrees.__import__("socket")',
        'integrees.exec("x = 1")',
    ],
)
def test_escaped_formula_can_do_nothing(monkeypatch, action):
    """Meme si la verification du code etait contournee, le processus de
    calcul refuse fichiers, programmes, reseau et imports."""
    monkeypatch.setattr("forecasts.sandbox.check", lambda code: None)
    data = {"soldeDepart": 0.0, "semaines": [{"date": "2026-10-13", "mois_commences": []}]}
    with pytest.raises(FormulaError, match="Opération interdite dans la formule"):
        run(ESCAPE.replace("ACTION", action), data, {})


def test_escape_is_refused_by_check():
    with pytest.raises(FormulaError, match="Attribut interdit"):
        check(ESCAPE.replace("ACTION", "pass"))


def test_run_allows_dates():
    """Les dates (dont strptime, qui charge des modules) restent utilisables."""
    data = {"soldeDepart": 0.0, "semaines": [{"date": "2026-10-13", "mois_commences": []}]}
    code = (
        "import datetime\nfrom datetime import date\n"
        "def prevoir(d, p):\n"
        "    jour = datetime.datetime.strptime(d['semaines'][0]['date'], '%Y-%m-%d')\n"
        "    return [float(jour.month + date.fromisoformat('2026-10-13').day + (jour - jour).days)]"
    )
    assert run(code, data, {}) == [23.0]


def test_run_stops_endless_formula(monkeypatch):
    monkeypatch.setattr("forecasts.sandbox.TIMEOUT", 2)
    data = {"soldeDepart": 0.0, "semaines": [{"date": "2026-10-13", "mois_commences": []}]}
    with pytest.raises(FormulaError):
        run("def prevoir(d, p):\n    while True:\n        pass", data, {})


# ----- donnees -----


def test_weeks_mark_new_months():
    weeks = forecast_data.weeks("2026-10-06", "2026-11-10")
    assert [w["date"] for w in weeks] == ["2026-10-13", "2026-10-20", "2026-10-27", "2026-11-03", "2026-11-10"]
    assert [w["mois_commences"] for w in weeks] == [[], [], [], ["2026-11"], []]
    assert forecast_data.weeks("2027-06-28", "2027-06-30") == [{"date": "2027-06-30", "mois_commences": []}]


def test_build_data(db, seasons):
    season = next(s for s in seasons.get_seasons()["seasons"] if s["name"] == "2026-2027")
    members = {"members": 40, "adults": 30, "minors": 10, "averagePrice": 290.0, "totalPrice": 11600.0,
               "remaining": [{"month": "2026-11", "amount": 950.0, "payments": 6}], "unpaidTotal": 0}
    data = forecast_data.build(BankStatements(db).get_ledger(), season, "2026-10-05", members)
    # 1000 + 3000 - 600 + 6000 - 600 + 3000 - 580
    assert data["soldeDepart"] == 11220.0
    assert data["soldeDebutSaison"] == 9400.0
    assert data["moisEnCours"] == {"mois": "2026-10", "dejaPasseParCategorie": {"Salaires": -580.0}}
    assert data["moyennesMensuelles"] == {"Cotisations en ligne": 250.0, "Salaires": -50.0}
    assert len(data["douzeDerniersMois"]) == 12
    assert data["adherents"]["echeancesAVenir"] == {"2026-11": 950.0}
    assert data["semaines"][-1]["date"] == "2027-06-30"


# ----- previsionnels -----


def test_run_writes_formula_and_points(db, seasons):
    coder = FakeCoder()
    forecasts = make_forecasts(db, seasons, coder, members=lambda: {"members": 40, "remaining": []})
    sid = season_id(seasons, "2026-2027")
    created = forecasts.create({"seasonId": sid, "name": "Prudent", "model": "sonnet"})
    assert created["result"] is None and created["startDate"] is None

    done = forecasts.run(created["id"], {"prompt": "Salaire 1000 €", "model": "haiku"})
    assert done["status"] == "idle", done["error"]
    model, data, prompt = coder.calls[0]
    assert (model, prompt) == ("haiku", "Salaire 1000 €")
    # Date de depart : dernier jour connu des comptes.
    assert data["dateDepart"] == "2026-10-05"
    assert data["adherents"]["nombre"] == 40
    points = done["result"]["points"]
    assert points[0] == {"date": "2026-10-05", "solde": 11220.0}
    # 8 mois commences (novembre a juin) : -1000 + 50 chacun.
    assert points[-1] == {"date": "2027-06-30", "solde": 11220.0 - 8 * 950}
    assert done["params"] == {"salaire": 1000, "nouveaux": 5}
    assert done["endBalance"] == points[-1]["solde"]
    assert done["aiCost"] == pytest.approx(0.05)
    assert seasons.get_seasons()["seasons"][1]["aiCost"] == pytest.approx(0.05)


def test_sliders_replay_formula_and_are_kept(db, seasons):
    forecasts = make_forecasts(db, seasons, FakeCoder())
    sid = season_id(seasons, "2026-2027")
    fid = forecasts.create({"seasonId": sid, "name": "Prudent"})["id"]
    forecasts.run(fid, {})
    moved = forecasts.set_params(fid, {"salaire": 500, "nouveaux": 99})
    # nouveaux ramene a son maximum (20).
    assert moved["params"] == {"salaire": 500.0, "nouveaux": 20.0}
    assert moved["result"]["points"][-1]["solde"] == 11220.0 + 8 * (200 - 500)
    # Nouveau calcul : les curseurs restent a leur position.
    again = forecasts.run(fid, {})
    assert again["params"] == {"salaire": 500.0, "nouveaux": 20.0}
    assert again["aiCost"] == pytest.approx(0.10)
    with pytest.raises(ForecastError):
        forecasts.set_params(fid, {"salaire": "beaucoup"})


def test_start_date_to_test_on_past_season(db, seasons):
    forecasts = make_forecasts(db, seasons, FakeCoder(), members=lambda: pytest.fail("HelloAsso lu pour une date passée"))
    sid = season_id(seasons, "2025-2026")
    with pytest.raises(ForecastError, match="dans la saison"):
        forecasts.create({"seasonId": sid, "name": "Test", "startDate": "2026-07-01"})
    fid = forecasts.create({"seasonId": sid, "name": "Test"})["id"]
    # Saison terminee : une date de depart est obligatoire.
    with pytest.raises(ForecastError, match="Saison terminée"):
        forecasts.run(fid, {})
    done = forecasts.run(fid, {"startDate": "2026-01-01"})
    assert done["startDate"] == "2026-01-01"
    assert done["result"]["data"]["adherents"] is None
    assert done["result"]["points"][0] == {"date": "2026-01-01", "solde": 9400.0}


def test_ai_error_is_shown_and_charged(db, seasons):
    forecasts = make_forecasts(db, seasons, FakeCoder(error="L'IA a refusé d'écrire ce prévisionnel."))
    sid = season_id(seasons, "2026-2027")
    fid = forecasts.create({"seasonId": sid, "name": "Essai"})["id"]
    failed = forecasts.run(fid, {})
    assert failed["status"] == "error"
    assert failed["error"] == "L'IA a refusé d'écrire ce prévisionnel."
    assert failed["aiCost"] == pytest.approx(0.01)


def test_several_official_forecasts_allowed(db, seasons):
    forecasts = make_forecasts(db, seasons, FakeCoder())
    sid = season_id(seasons, "2026-2027")
    forecasts.create({"seasonId": sid, "name": "A", "state": "officiel"})
    forecasts.create({"seasonId": sid, "name": "B", "state": "officiel"})
    assert [f["state"] for f in forecasts.list(sid)] == ["officiel", "officiel"]


def test_api_and_downloads(db, seasons):
    app = FastAPI()
    ForecastsReceiver(make_forecasts(db, seasons, FakeCoder()), app)
    client = TestClient(app)
    sid = season_id(seasons, "2026-2027")
    listing = client.get(f"/forecasts?seasonId={sid}").json()
    assert [m["id"] for m in listing["models"]] == ["haiku", "sonnet", "fable"]
    fid = client.post("/forecasts", json={"seasonId": sid, "name": "Prudent", "prompt": "x"}).json()["id"]
    assert client.get(f"/forecasts/{fid}/download?format=png").status_code == 400
    assert client.post(f"/forecasts/{fid}/run", json={"model": "fable"}).json()["status"] == "idle"
    assert client.put(f"/forecasts/{fid}/params", json={"params": {"salaire": 800}}).json()["params"]["salaire"] == 800

    png = client.get(f"/forecasts/{fid}/download?format=png")
    assert png.status_code == 200 and png.content[:4] == b"\x89PNG"
    pdf = client.get(f"/forecasts/{fid}/download?format=pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    assert client.get(f"/forecasts/{fid}/download?format=xlsx").status_code == 400

    assert client.delete(f"/forecasts/{fid}").json() == {"deleted": fid}
    assert client.get(f"/forecasts/{fid}").status_code == 404


def test_explanation_open_is_kept(db, seasons):
    """La zone "Explication du résultat de l'IA" pliee ou depliee est
    retenue par previsionnel, sans toucher a sa date de modification."""
    forecasts = make_forecasts(db, seasons, FakeCoder())
    created = forecasts.create({"seasonId": season_id(seasons, "2026-2027"), "name": "P"})
    assert created["explanationOpen"] is True
    assert forecasts.set_explanation_open(created["id"], False) == {"explanationOpen": False}
    again = forecasts.get(created["id"])
    assert again["explanationOpen"] is False and again["updatedAt"] == created["updatedAt"]
    with pytest.raises(ForecastNotFoundError):
        forecasts.set_explanation_open(9999, True)
    # Meme chose pour la zone "Réglages de l'IA".
    assert again["settingsOpen"] is True
    assert forecasts.set_settings_open(created["id"], False) == {"settingsOpen": False}
    assert forecasts.get(created["id"])["settingsOpen"] is False
