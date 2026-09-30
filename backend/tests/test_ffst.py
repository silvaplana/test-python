"""Tests des utilitaires du module FFST (sans acces au portail FFST).
Lancer depuis backend/ : PYTHONPATH=src venv/bin/python -m pytest tests"""

import pytest

from ffst.ffst import normaliser_ville


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
