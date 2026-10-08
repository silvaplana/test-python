"""Tests des bilans financiers (Finances > Bilan financier) : compte
d'exploitation calcule depuis l'historique des comptes, verification des
soldes, classement des operations "Autres" par l'IA (simulee ici), etats,
cout de l'IA et telechargements.
Lancer depuis backend/ : PYTHONPATH=src venv/bin/python -m pytest tests"""

from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bankstatements import BankStatements
from database import Database
from financialreports import FinancialReports, FinancialReportsReceiver, ReportError
from financialreports.ai import Analysis, AnalysisError, _cost
from financialreports.report import compute_report
from seasons import Seasons

TODAY = date(2026, 10, 6)


@pytest.fixture
def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    database.migrate()
    # Compte courant (1) et Livret Bleu (2) ; montants en centimes.
    with database.connect() as connection:
        connection.execute("INSERT INTO bank_accounts (id, number, name, kind) VALUES (1, '01', 'Compte courant', 'checking')")
        connection.execute("INSERT INTO bank_accounts (id, number, name, kind) VALUES (2, '02', 'Livret Bleu', 'savings')")
        connection.execute("INSERT INTO bank_statements VALUES (1, 1, '2024-06-01', 100000, '2026-08-31', 0, 'cc.pdf', 'x')")
        connection.execute("INSERT INTO bank_statements VALUES (2, 2, '2024-06-01', 300000, '2026-08-31', 0, 'bleu.pdf', 'x')")
        operations = [
            # saison 2024-2025
            (1, "2024-10-05", "VIR STRIPE TECHNOLOGY", 500000),
            (1, "2024-11-10", "VIR SALAIRE NOVEMBRE", -100000),
            # saison 2025-2026
            (1, "2025-07-31", "VIR SALAIRE JUILLET", -120000),
            (1, "2025-08-20", "VIR SEPA FFST", 20000),  # licences remboursees
            (1, "2025-09-15", "VIR STRIPE TECHNOLOGY", 600000),
            (1, "2025-09-20", "VIR SEPA FFST", -50000),
            (1, "2025-12-07", "VIR PIZZA AG 29 NOV", -18680),
            (1, "2026-06-24", "CTR CLT 102780897200020300801", 329074),
            (2, "2025-12-31", "INTERETS", 6794),
        ]
        for position, (account, day, label, amount) in enumerate(operations):
            connection.execute(
                """INSERT INTO bank_operations (account_id, statement_id, position, date, value_date, label, amount)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (account, account, position, day, day, label, amount),
            )
    return database


class FakeAnalyst:
    """IA simulee : classe les operations "Autres" et renvoie une analyse."""

    def __init__(self, classify=None, error=None):
        self.classify = classify or {}
        self.error = error
        self.calls = []

    def analyze(self, model, data, prompt):
        self.calls.append((model, data, prompt))
        if self.error:
            raise AnalysisError(self.error, cost=0.01)
        ids = {op["libelle"]: op["operationId"] for op in data["operationsAClasser"]}
        return Analysis(
            classifications={ids[label]: category for label, category in self.classify.items() if label in ids},
            analysis=["Ligne 1", "Ligne 2"],
            model=model,
            served_by="claude-sonnet-5-5",
            cost=0.09,
        )


@pytest.fixture
def seasons(db):
    client = Seasons(db=db, ledger=BankStatements(db).get_ledger, today=lambda: TODAY)
    client.create({"name": "2024-2025", "startDate": "2024-07-01", "endDate": "2025-06-30", "licences": 90})
    client.create({"name": "2025-2026", "startDate": "2025-07-01", "endDate": "2026-06-30", "licences": 110})
    client.create({"name": "2026-2027", "startDate": "2026-07-01", "endDate": "2027-06-30"})
    return client


def make_reports(db, seasons, analyst):
    return FinancialReports(
        db=db,
        ledger=BankStatements(db).get_ledger,
        seasons=lambda: seasons.get_seasons()["seasons"],
        add_ai_cost=seasons.add_current_ai_cost,
        analyst=analyst,
        background=False,
    )


def season_id(seasons, name):
    return next(s["id"] for s in seasons.get_seasons()["seasons"] if s["name"] == name)


def test_compute_report_balances_and_categories(db):
    report = compute_report(BankStatements(db).get_ledger(), "2025-07-01", "2026-06-30")
    # Courant 1000 + 5000 - 1000, Livret Bleu 3000.
    assert report["opening"] == 8000.0
    assert report["income"] == [
        {"category": "Cotisations en ligne", "amount": 6000.0},
        {"category": "Autres", "amount": 3103.94},  # 3290,74 - 186,80
        {"category": "Intérêts", "amount": 67.94},
    ]
    # Licences nettes : 500 payees - 200 remboursees.
    assert report["expense"] == [{"category": "Salaires", "amount": 1200.0}, {"category": "FFST (licences)", "amount": 300.0}]
    assert report["totalIncome"] == 9171.88
    assert report["totalExpense"] == 1500.0
    assert report["closing"] == 15671.88
    assert report["verification"] == {"expected": 15671.88, "actual": 15671.88, "gap": 0.0, "ok": True}
    assert [m["month"] for m in report["months"]][:2] == ["2025-07", "2025-08"]
    assert report["months"][0] == {"month": "2025-07", "opening": 8000.0, "closing": 6800.0, "amounts": {"Salaires": -1200.0}}
    assert report["months"][-1]["closing"] == 15671.88


def test_current_season_stops_at_last_known_day(db):
    report = compute_report(BankStatements(db).get_ledger(), "2026-07-01", "2027-06-30")
    assert report["cutoff"] == "2026-08-31"
    assert report["income"] == [] and report["expense"] == []
    assert report["opening"] == report["closing"] == 15671.88
    assert report["verification"]["ok"]


def test_run_classifies_others_and_adds_cost(db, seasons):
    analyst = FakeAnalyst({"VIR PIZZA AG 29 NOV": "Réception AG", "CTR CLT 102780897200020300801": "Reprise autre association"})
    reports = make_reports(db, seasons, analyst)
    sid = season_id(seasons, "2025-2026")
    created = reports.create({"seasonId": sid, "name": "Bilan AG", "prompt": "", "model": "sonnet"})
    assert created["status"] == "idle" and created["result"] is None

    done = reports.run(created["id"], {"prompt": "Ton simple", "model": "fable"})
    assert done["status"] == "idle"
    assert done["prompt"] == "Ton simple" and done["model"] == "fable"
    model, data, prompt = analyst.calls[0]
    assert (model, prompt) == ("fable", "Ton simple")
    assert [op["libelle"] for op in data["operationsAClasser"]] == ["VIR PIZZA AG 29 NOV", "CTR CLT 102780897200020300801"]
    assert data["saisonsPrecedentes"][0]["saison"] == "2024-2025"
    assert data["saisonsPrecedentes"][0]["licencies"] == 90

    result = done["result"]
    assert {r["category"]: r["amount"] for r in result["income"]}["Reprise autre association"] == 3290.74
    assert {r["category"]: r["amount"] for r in result["expense"]}["Réception AG"] == 186.8
    assert "Autres" not in result["net"]
    assert result["verification"]["ok"]
    assert result["previous"]["season"] == "2024-2025"
    assert result["previous"]["net"]["Cotisations en ligne"] == 5000.0
    assert result["analysis"] == ["Ligne 1", "Ligne 2"]
    assert result["modelLabel"] == "Claude Fable 5.1"

    # Cout cumule du bilan, et de la saison EN COURS (2026-2027 au 06/10/2026)
    # -- pas de la saison du bilan (2025-2026), deja terminee.
    reports.run(created["id"], {})
    assert reports.get(created["id"])["aiCost"] == pytest.approx(0.18)
    costs = {s["name"]: s["aiCost"] for s in seasons.get_seasons()["seasons"]}
    assert costs == {"2024-2025": None, "2025-2026": None, "2026-2027": pytest.approx(0.18)}


def test_run_error_is_reported_and_cost_kept(db, seasons):
    reports = make_reports(db, seasons, FakeAnalyst(error="L'IA a refusé de faire ce bilan."))
    created = reports.create({"seasonId": season_id(seasons, "2025-2026"), "name": "Essai"})
    done = reports.run(created["id"], {})
    assert done["status"] == "error"
    assert done["error"] == "L'IA a refusé de faire ce bilan."
    assert done["result"] is None
    assert done["aiCost"] == pytest.approx(0.01)


def test_only_one_official_report_per_season(db, seasons):
    reports = make_reports(db, seasons, FakeAnalyst())
    sid = season_id(seasons, "2025-2026")
    first = reports.create({"seasonId": sid, "name": "A", "state": "officiel"})
    second = reports.create({"seasonId": sid, "name": "B"})
    other = reports.create({"seasonId": season_id(seasons, "2024-2025"), "name": "C", "state": "officiel"})
    reports.update(second["id"], {"name": "B", "state": "officiel"})
    states = {r["name"]: r["state"] for r in reports.list(sid)}
    assert states == {"A": "valide", "B": "officiel"}
    assert reports.get(other["id"])["state"] == "officiel"
    assert first["state"] == "officiel"


def test_validation(db, seasons):
    reports = make_reports(db, seasons, FakeAnalyst())
    sid = season_id(seasons, "2025-2026")
    with pytest.raises(ReportError):
        reports.create({"seasonId": sid, "name": " "})
    with pytest.raises(ReportError):
        reports.create({"seasonId": sid, "name": "X", "state": "final"})
    with pytest.raises(ReportError):
        reports.create({"seasonId": sid, "name": "X", "model": "gpt"})
    with pytest.raises(ReportError):
        reports.create({"seasonId": 999, "name": "X"})


def test_deleting_season_deletes_its_reports(db, seasons):
    reports = make_reports(db, seasons, FakeAnalyst())
    sid = season_id(seasons, "2025-2026")
    reports.create({"seasonId": sid, "name": "A"})
    seasons.delete(sid)
    assert reports.list(sid) == []


def test_cost_in_euros():
    class Usage:
        input_tokens = 30_000
        output_tokens = 4_000
        cache_creation_input_tokens = 0
        cache_read_input_tokens = 0

    # Sonnet : 30k x 2 $ + 4k x 10 $ par million = 0,10 $.
    assert _cost("claude-sonnet-5-5", Usage()) == pytest.approx(0.10 * 0.86)
    assert _cost("claude-opus-4-8", Usage()) == pytest.approx((0.15 + 0.10) * 0.86)


def test_api_and_downloads(db, seasons):
    reports = make_reports(db, seasons, FakeAnalyst({"VIR PIZZA AG 29 NOV": "Réception AG"}))
    app = FastAPI()
    FinancialReportsReceiver(client=reports, app=app)
    client = TestClient(app)
    sid = season_id(seasons, "2025-2026")

    listing = client.get("/financial-reports", params={"seasonId": sid}).json()
    assert [m["id"] for m in listing["models"]] == ["haiku", "sonnet", "fable"]
    assert listing["reports"] == []

    created = client.post("/financial-reports", json={"seasonId": sid, "name": "Bilan"}).json()
    assert client.get(f"/financial-reports/{created['id']}/download").status_code == 400
    run = client.post(f"/financial-reports/{created['id']}/run", json={"model": "haiku", "prompt": "Court"}).json()
    assert run["status"] == "idle" and run["result"]["verification"]["ok"]

    xlsx = client.get(f"/financial-reports/{created['id']}/download", params={"format": "xlsx"})
    assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK"
    pdf = client.get(f"/financial-reports/{created['id']}/download", params={"format": "pdf"})
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"

    assert client.put(f"/financial-reports/{created['id']}", json={"name": "Bilan", "state": "nul"}).status_code == 400
    assert client.delete(f"/financial-reports/{created['id']}").json() == {"deleted": created["id"]}
    assert client.get(f"/financial-reports/{created['id']}").status_code == 404


def test_counts_per_season(db, seasons):
    """Nombre de bilans par saison, affiche dans le choix de la saison."""
    reports = make_reports(db, seasons, FakeAnalyst({}))
    first, second = season_id(seasons, "2024-2025"), season_id(seasons, "2025-2026")
    reports.create({"seasonId": first, "name": "A"})
    reports.create({"seasonId": first, "name": "B"})
    reports.create({"seasonId": second, "name": "C"})
    assert reports.counts() == {first: 2, second: 1}


def test_settings_open_is_kept(db, seasons):
    """La zone "Réglages de l'IA" pliee ou depliee est retenue par bilan."""
    reports = make_reports(db, seasons, FakeAnalyst({}))
    created = reports.create({"seasonId": season_id(seasons, "2025-2026"), "name": "A"})
    assert reports.get(created["id"])["settingsOpen"] is True
    assert reports.set_settings_open(created["id"], False) == {"settingsOpen": False}
    again = reports.get(created["id"])
    assert again["settingsOpen"] is False and again["updatedAt"] == created["updatedAt"]


def test_preset_prompts_common_to_all_reports(db, seasons):
    presets = make_reports(db, seasons, analyst=None).models()["presetPrompts"]
    assert [p["id"] for p in presets] == ["preset-1", "preset-2"]
    assert presets[1]["prompt"] == "sqslqmqmlqmlqmqlqqlqlqlq\nmmxmsùùsùs\nxxxxxxxx"
