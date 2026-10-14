"""Tests du pipeline : schéma, import, boucle de correction (modèle simulé), démo, journal."""

import json
from types import SimpleNamespace

import pytest

from text2sql import base, demo, llm
from text2sql.journal import journaliser

# --- Schéma ------------------------------------------------------------------

def test_schema_retail_complet(base_retail):
    schema = base.lire_schema(base_retail)
    for table in ("magasins", "produits", "clients", "ventes"):
        assert f"Table {table}" in schema
    assert "'Électronique'" in schema
    assert "du 2025-01-01 au 2025-12-31" in schema


def test_volumes_du_seed(base_retail):
    df = base.executer_requete(base_retail, "SELECT (SELECT COUNT(*) FROM ventes) AS n, "
                                            "(SELECT COUNT(*) FROM magasins) AS m")
    assert (df.n[0], df.m[0]) == (20_000, 10)


# --- Import de fichiers ------------------------------------------------------

def test_import_csv(tmp_path):
    csv = b"Date de commande;Client;Montant TTC\n03/02/2025;Alice;12,5\n04/02/2025;Bob;8\n"
    chemin = base.importer_fichiers([("Commandes 2025.csv", csv)], tmp_path / "i.db")
    assert base.lister_tables(chemin) == ["commandes_2025"]
    df = base.executer_requete(chemin, "SELECT date_de_commande, client FROM commandes_2025")
    assert df.date_de_commande.tolist() == ["2025-02-03", "2025-02-04"]


def test_import_base_sqlite(tmp_path, base_vide):
    chemin = base.importer_fichiers([("ma_base.db", base_vide.read_bytes())], tmp_path / "i.db")
    assert base.lister_tables(chemin) == ["t"]


def test_import_format_refuse(tmp_path):
    with pytest.raises(base.ImportInvalide):
        base.importer_fichiers([("rapport.pdf", b"%PDF-1.7")], tmp_path / "i.db")


@pytest.mark.parametrize("brut, attendu", [
    ("Montant TTC (€)", "montant_ttc"),
    ("2025 ventes", "t_2025_ventes"),
    ("Région", "region"),
])
def test_normaliser_nom(brut, attendu):
    assert base.normaliser_nom(brut) == attendu


# --- Boucle de correction avec un modèle simulé ---------------------------

def _simuler_modele(monkeypatch, reponses):
    """Remplace l'appel API par une suite de réponses ; renvoie la liste des conversations reçues."""
    iterateur, appels = iter(reponses), []

    def faux_appel(client, systeme, messages, conso):
        appels.append(messages)
        conso.ajouter(SimpleNamespace(input_tokens=100, output_tokens=20,
                                      cache_read_input_tokens=0, cache_creation_input_tokens=0))
        return next(iterateur)

    monkeypatch.setattr(llm, "appeler_modele", faux_appel)
    return appels


def test_correction_automatique_reussie(monkeypatch, base_retail):
    appels = _simuler_modele(monkeypatch, ["SELECT nom FROM magasin", "DROP TABLE ventes",
                                           "SELECT nom FROM magasins"])
    res = llm.generer_et_executer(None, "systeme", [], "liste des magasins", base_retail)
    assert res.succes and res.tentatives == 3 and len(res.df) == 10
    assert "no such table" in appels[1][-1]["content"]      # l'erreur est renvoyée au modèle
    assert res.consommation.entree == 300


def test_echec_apres_deux_corrections(monkeypatch, base_retail):
    _simuler_modele(monkeypatch, ["SELECT x FROM y"] * 3)
    res = llm.generer_et_executer(None, "systeme", [], "question", base_retail)
    assert not res.succes and res.tentatives == 3 and "no such table" in res.erreur


def test_historique_transmis_pour_les_questions_de_suivi(monkeypatch, base_retail):
    appels = _simuler_modele(monkeypatch, ["SELECT 1"])
    historique = [{"role": "user", "content": "CA en septembre"},
                  {"role": "assistant", "content": "SELECT 1"}]
    llm.generer_et_executer(None, "systeme", historique, "et pour octobre ?", base_retail)
    assert appels[0][:2] == historique and appels[0][-1]["content"] == "et pour octobre ?"


def test_prompt_contient_schema_et_exemples():
    prompt = llm.construire_prompt_systeme("Table ventes : ...")
    assert "Table ventes" in prompt and prompt.count("Question :") == 4


# --- Mode démo ---------------------------------------------------------------

@pytest.mark.parametrize("question", [q for q in demo.QUESTIONS_DEMO if "Supprime" not in q])
def test_questions_demo_executables(question, base_retail):
    res = demo.repondre(question, base_retail)
    assert res.succes and not res.df.empty


def test_demo_tolerante_aux_accents_et_ponctuation(base_retail):
    assert demo.repondre("ca par magasin en septembre", base_retail).succes


def test_demo_bloque_la_suppression(base_retail):
    res = demo.repondre("Supprime toutes les ventes", base_retail)
    assert res.bloquee and not res.succes


def test_demo_question_inconnue(base_retail):
    res = demo.repondre("Quelle est la météo ?", base_retail)
    assert not res.succes and "mode démo" in res.erreur


# --- Journal d'audit ---------------------------------------------------------

def test_journal(tmp_path, base_retail):
    fichier = tmp_path / "journal.jsonl"
    journaliser(demo.repondre("Panier moyen en décembre", base_retail), "demo", str(fichier))
    entree = json.loads(fichier.read_text(encoding="utf-8"))
    assert entree["succes"] and entree["lignes"] == 1 and entree["question"] == "Panier moyen en décembre"


def test_schema_avec_noms_pieges(tmp_path):
    import sqlite3
    chemin = tmp_path / "piege.db"
    with sqlite3.connect(chemin) as conn:
        conn.execute('CREATE TABLE "a""b" ("c""d" TEXT)')
        conn.execute('INSERT INTO "a""b" VALUES (\'x\')')
    assert "Table a\"b (1 lignes)" in base.lire_schema(chemin)


def test_import_colonnes_en_double(tmp_path):
    csv = "Prix €,Prix $,Année,annee\n1,2,3,4\n".encode()
    chemin = base.importer_fichiers([("prix.csv", csv)], tmp_path / "i.db")
    df = base.executer_requete(chemin, "SELECT * FROM prix")
    assert list(df.columns) == ["prix", "prix_2", "annee", "annee_2"]


def test_import_sqlite_corrompue(tmp_path):
    with pytest.raises(base.ImportInvalide):
        base.importer_fichiers([("x.db", b"SQLite format 3\x00" + b"\x00" * 50)], tmp_path / "i.db")


def test_import_melange_sqlite_et_csv(tmp_path, base_vide):
    with pytest.raises(base.ImportInvalide):
        base.importer_fichiers([("a.db", base_vide.read_bytes()), ("b.csv", b"x\n1\n")], tmp_path / "i.db")


def test_chemin_avec_caracteres_speciaux(tmp_path, base_vide):
    dossier = tmp_path / "dossier #1 ?%"
    dossier.mkdir()
    cible = dossier / "base.db"
    cible.write_bytes(base_vide.read_bytes())
    assert base.lister_tables(cible) == ["t"]
