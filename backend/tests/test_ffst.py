"""Tests des utilitaires du module FFST (sans acces au portail FFST).
Lancer depuis backend/ : PYTHONPATH=src venv/bin/python -m pytest tests"""

import pytest

from ffst.ffst import normaliser_nom, normaliser_ville


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
