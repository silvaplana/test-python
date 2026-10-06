"""Tests des saisons (Finances > Saisons) : fiches creees/modifiees/supprimees,
soldes de fin de saison calcules depuis l'historique des comptes ou saisis,
licencies FFST de la saison en cours.
Lancer depuis backend/ : PYTHONPATH=src venv/bin/python -m pytest tests"""

from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bankstatements import BankStatements
from database import Database
from seasons import SeasonError, SeasonNotFoundError, Seasons, SeasonsReceiver

TODAY = date(2026, 10, 6)


@pytest.fixture
def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    database.migrate()
    # Compte courant (1) et Livret Bleu (2), un releve chacun puis des
    # operations (montants en centimes).
    with database.connect() as connection:
        connection.execute("INSERT INTO bank_accounts (id, number, name, kind) VALUES (1, '01', 'Compte courant', 'checking')")
        connection.execute("INSERT INTO bank_accounts (id, number, name, kind) VALUES (2, '02', 'Livret Bleu', 'savings')")
        connection.execute(
            "INSERT INTO bank_statements VALUES (1, 1, '2025-06-01', 100000, '2026-09-30', 0, 'cc.pdf', 'x')"
        )
        connection.execute(
            "INSERT INTO bank_statements VALUES (2, 2, '2025-06-01', 50000, '2026-09-30', 0, 'bleu.pdf', 'x')"
        )
        operations = [
            (1, "2025-06-10", -20000),  # saison 2024-2025
            (1, "2025-09-15", 300000),  # saison 2025-2026
            (2, "2026-01-05", 1500),
            (1, "2026-06-30", -80000),
            (1, "2026-09-10", 250000),  # saison 2026-2027 (en cours)
        ]
        for position, (account, day, amount) in enumerate(operations):
            connection.execute(
                """INSERT INTO bank_operations (account_id, statement_id, position, date, value_date, label, amount)
                   VALUES (?, ?, ?, ?, ?, 'OP', ?)""",
                (account, account, position, day, day, amount),
            )
    return database


@pytest.fixture
def seasons(db):
    return Seasons(db=db, ledger=BankStatements(db).get_ledger, today=lambda: TODAY)


def season(name, start, end, **extra):
    return {"name": name, "startDate": start, "endDate": end, **extra}


def test_computed_end_balances(seasons):
    seasons.create(season("2025-2026", "2025-07-01", "2026-06-30"))
    seasons.create(season("2026-2027", "2026-07-01", "2027-06-30"))
    past, current = seasons.get_seasons()["seasons"]

    assert not past["current"]
    # Courant 1000 - 200 + 3000 - 800, Livret Bleu 500 + 15.
    assert past["balance"] == {"total": 3515.0, "asOf": "2026-06-30", "auto": True, "computed": 3515.0}
    # Saison en cours : solde a ce jour.
    assert current["current"]
    assert current["balance"]["total"] == 6015.0
    assert current["balance"]["asOf"] == "2026-09-10"


def test_season_before_history_and_future_season_have_no_balance(seasons):
    seasons.create(season("2023-2024", "2023-07-01", "2024-06-30"))
    seasons.create(season("2027-2028", "2027-07-01", "2028-06-30"))
    old, future = seasons.get_seasons()["seasons"]
    assert old["balance"]["total"] is None
    assert future["balance"]["total"] is None


def test_manual_balance_overrides_computed(seasons):
    created = seasons.create(season("2025-2026", "2025-07-01", "2026-06-30", endBalance=1734.56, aiCost=3.2))
    assert created["balance"]["total"] == 1734.56
    assert not created["balance"]["auto"]
    assert created["balance"]["asOf"] is None
    assert created["balance"]["computed"] == 3515.0
    assert created["aiCost"] == 3.2

    # Retour au calcul : solde efface.
    updated = seasons.update(created["id"], season("2025-2026", "2025-07-01", "2026-06-30"))
    assert updated["balance"]["auto"]
    assert updated["balance"]["total"] == 3515.0


def test_series_one_point_per_day(seasons):
    series = seasons.get_seasons()["series"]
    assert series[0] == {"date": "2025-06-10", "total": 1300.0}
    assert series[-1] == {"date": "2026-09-10", "total": 6015.0}
    assert len(series) == 5


def test_validation(seasons):
    seasons.create(season("2025-2026", "2025-07-01", "2026-06-30"))
    with pytest.raises(SeasonError, match="existe déjà"):
        seasons.create(season("2025-2026", "2026-07-01", "2027-06-30"))
    with pytest.raises(SeasonError, match="chevauchent la saison 2025-2026"):
        seasons.create(season("2026-2027", "2026-06-01", "2027-06-30"))
    with pytest.raises(SeasonError, match="après la date de début"):
        seasons.create(season("2026-2027", "2027-06-30", "2026-07-01"))
    with pytest.raises(SeasonError, match="obligatoire"):
        seasons.create(season(" ", "2026-07-01", "2027-06-30"))


def test_update_keeps_own_dates_and_delete(seasons):
    created = seasons.create(season("2025-2026", "2025-07-01", "2026-06-30"))
    # Modifier une saison sans changer ses dates : pas de chevauchement avec elle-meme.
    updated = seasons.update(created["id"], season("2025-2026", "2025-07-01", "2026-06-30", licences=112))
    assert updated["licences"] == 112

    seasons.delete(created["id"])
    assert seasons.get_seasons()["seasons"] == []
    with pytest.raises(SeasonNotFoundError):
        seasons.delete(created["id"])


def test_delete_keeps_bank_operations(seasons, db):
    created = seasons.create(season("2025-2026", "2025-07-01", "2026-06-30"))
    seasons.delete(created["id"])
    with db.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM bank_operations").fetchone()[0] == 5


def test_current_licences(seasons):
    assert seasons.set_current_licences(74) is None  # aucune saison en cours
    seasons.create(season("2025-2026", "2025-07-01", "2026-06-30", licences=112))
    seasons.create(season("2026-2027", "2026-07-01", "2027-06-30"))
    assert seasons.set_current_licences(74)["name"] == "2026-2027"
    past, current = seasons.get_seasons()["seasons"]
    assert (past["licences"], current["licences"]) == (112, 74)


def test_api(seasons):
    app = FastAPI()
    calls = []

    def licences_count():
        calls.append(1)
        if len(calls) > 1:
            raise RuntimeError("FFST injoignable")
        return 74

    SeasonsReceiver(client=seasons, app=app, licences_count=licences_count)
    client = TestClient(app)

    response = client.post("/seasons", json=season("2026-2027", "2026-07-01", "2027-06-30"))
    assert response.status_code == 200
    season_id = response.json()["id"]
    assert client.post("/seasons", json=season("2026-2027", "2027-07-01", "2028-06-30")).status_code == 400

    assert client.post("/seasons/sync-licences").json()["season"]["licences"] == 74
    assert client.post("/seasons/sync-licences").json() == {"season": None, "error": "FFST injoignable"}

    response = client.put(f"/seasons/{season_id}", json=season("2026-2027", "2026-07-01", "2027-06-30", aiCost=1.5))
    assert response.json()["aiCost"] == 1.5
    assert client.get("/seasons").json()["seasons"][0]["aiCost"] == 1.5
    assert client.put("/seasons/999", json=season("x", "2030-07-01", "2031-06-30")).status_code == 404

    assert client.delete(f"/seasons/{season_id}").status_code == 200
    assert client.delete(f"/seasons/{season_id}").status_code == 404


def test_ai_cost_below_one_cent_adds_up(seasons):
    """Un appel a l'IA coute souvent moins d'un centime : ces couts
    s'additionnent quand meme dans le cout de la saison."""
    created = seasons.create(season("2025-2026", "2025-07-01", "2026-06-30"))
    for _ in range(4):
        seasons.add_ai_cost(created["id"], 0.0027)
    assert seasons.get_seasons()["seasons"][0]["aiCost"] == pytest.approx(0.0108)
