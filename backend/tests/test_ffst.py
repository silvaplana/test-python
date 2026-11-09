"""Tests des utilitaires du module FFST (sans acces au portail FFST).
Lancer depuis backend/ : PYTHONPATH=src venv/bin/python -m pytest tests"""

import pytest

from contextlib import contextmanager
from types import SimpleNamespace

import ffst.ffst as ffst_module
from ffst.ffst import Ffst, FfstLicencieIntrouvableError, normaliser_nom, normaliser_ville


@pytest.mark.parametrize(
    "ville, attendu",
    [
        ("laciotat", "Laciotat"),
        ("  la ciotat ", "La ciotat"),
        ("La Ciotat", "La Ciotat"),
        ("LA CIOTAT", "LA CIOTAT"),
        ("élancourt", "Elancourt"),
        ("Évry", "Evry"),
        ("", ""),
    ],
)
def test_normaliser_ville(ville, attendu):
    assert normaliser_ville(ville) == attendu


@pytest.mark.parametrize(
    "nom, attendu",
    [
        ("M'Hadjou", "M Hadjou"),
        ("M\u2019Hadjou", "M Hadjou"),
        ("N' Diaye ", "N Diaye"),
        ("Barrachina ", "Barrachina"),
        ("Jean-Pierre", "Jean-Pierre"),
        ("", ""),
    ],
)
def test_normaliser_nom(nom, attendu):
    assert normaliser_nom(nom) == attendu


# ----- create_demande_renouvellement : champs HelloAsso manquants -----
# Navigateur et portail FFST simules : seul l'enchainement renouvellement /
# nouvelle demande est teste ici.


@pytest.fixture
def client_simule(monkeypatch):
    page = SimpleNamespace(on=lambda *a: None)
    browser = SimpleNamespace(new_page=lambda: page, close=lambda: None)
    playwright = SimpleNamespace(chromium=SimpleNamespace(launch=lambda: browser))

    @contextmanager
    def faux_sync_playwright():
        yield playwright

    monkeypatch.setattr(ffst_module, "sync_playwright", faux_sync_playwright)
    client = Ffst("a", "b", "c", "mdp")
    client.appels = []
    monkeypatch.setattr(client, "_se_connecter_via_navigateur", lambda page: None)
    return client


def test_renouvellement_accepte_champs_helloasso_vides(client_simule, monkeypatch):
    # Ancien licencie : les champs vides gardent la valeur de l'ancienne licence.
    monkeypatch.setattr(
        client_simule, "_renouveler_via_navigateur", lambda page, nom, prenom, **infos: client_simule.appels.append(infos)
    )
    assert client_simule.create_demande_renouvellement("Dupont", "Jean") == []
    assert client_simule.appels[0]["gender"] is None


def test_nouvelle_demande_exige_champs_helloasso(client_simule, monkeypatch):
    def introuvable(page, nom, prenom, **infos):
        raise FfstLicencieIntrouvableError(nom)

    monkeypatch.setattr(client_simule, "_renouveler_via_navigateur", introuvable)
    monkeypatch.setattr(
        client_simule, "_saisir_nouvelle_demande_via_navigateur", lambda *a, **k: pytest.fail("ne doit pas etre appele")
    )
    with pytest.raises(RuntimeError, match="sexe, date de naissance, adresse"):
        client_simule.create_demande_renouvellement("Dupont", "Jean", city="La Ciotat", postal_code="13600")
