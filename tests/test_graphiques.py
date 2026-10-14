"""Tests du choix automatique de graphique."""

import pandas as pd
import pytest

from text2sql.graphiques import (
    PALETTE,
    choisir_graphique,
    construire_graphique,
    est_temporelle,
    regrouper_series,
)


def test_valeur_unique_donne_un_indicateur():
    choix = choisir_graphique(pd.DataFrame({"chiffre_affaires": [123.4]}))
    assert choix.type == "kpi"


@pytest.mark.parametrize("df", [
    None,
    pd.DataFrame(),
    pd.DataFrame({"message": ["Question hors du périmètre de la base"]}),
    pd.DataFrame({"magasin": ["A"], "ca": [10.0]}),          # une seule ligne
    pd.DataFrame({"nom": ["A", "B"], "ville": ["X", "Y"]}),  # aucune mesure
])
def test_pas_de_graphique(df):
    assert choisir_graphique(df) is None


def test_categorie_valeur_donne_des_barres():
    choix = choisir_graphique(pd.DataFrame({"magasin": ["A", "B"], "ca": [10.0, 20.0]}))
    assert (choix.type, choix.x, choix.y) == ("barres", "magasin", "ca")


def test_serie_temporelle_donne_une_ligne():
    choix = choisir_graphique(pd.DataFrame({"mois": ["2025-01", "2025-02"], "ca": [1.0, 2.0]}))
    assert (choix.type, choix.x, choix.y) == ("ligne", "mois", "ca")


def test_temps_et_categorie_donnent_plusieurs_lignes():
    df = pd.DataFrame({"mois": ["2025-01", "2025-01", "2025-02"], "region": ["N", "S", "N"],
                       "ca": [1.0, 2.0, 3.0]})
    choix = choisir_graphique(df)
    assert (choix.type, choix.serie) == ("lignes", "region")


@pytest.mark.parametrize("nom, valeurs, attendu", [
    ("mois", [1, 2], True),
    ("x", ["2025-01-03", "2025-02-01"], True),
    ("magasin", ["Paris", "Lyon"], False),
])
def test_est_temporelle(nom, valeurs, attendu):
    assert est_temporelle(pd.Series(valeurs, name=nom)) is attendu


def test_regroupement_au_dela_de_huit_series():
    df = pd.DataFrame({"mois": ["2025-01"] * 12, "serie": [f"s{i}" for i in range(12)],
                       "ca": list(range(12))})
    regroupe = regrouper_series(df, "serie", "ca")
    assert regroupe["serie"].nunique() == 8
    assert "Autres" in set(regroupe["serie"])
    assert regroupe["ca"].sum() == df["ca"].sum()


@pytest.mark.parametrize("theme", ["clair", "sombre"])
def test_construction_sans_erreur(theme):
    df = pd.DataFrame({"mois": ["2025-01", "2025-02"], "region": ["N", "N"], "ca": [1.0, 2.0]})
    spec = construire_graphique(df, choisir_graphique(df), theme).to_dict()
    assert PALETTE[theme][0] in str(spec)
