"""Tests du filtre de sécurité SQL (python -m pytest)."""

import sqlite3

import pytest

from text2sql.securite import (
    RequeteRefusee,
    ajouter_limit,
    nettoyer_sql,
    ouvrir_connexion_securisee,
    ouvrir_lecture_seule,
    securiser_requete,
    valider_sql,
)

# --- Requêtes acceptées -----------------------------------------------------

@pytest.mark.parametrize("sql", [
    "SELECT * FROM ventes",
    "select nom from magasins",
    "  SELECT 1  ",
    "WITH t AS (SELECT magasin_id FROM ventes) SELECT COUNT(*) FROM t",
    "SELECT date_inscription FROM clients",          # 'date' n'est pas un mot interdit
    "SELECT montant AS updated_total FROM ventes",    # 'updated_total' ≠ UPDATE
    "SELECT replace(nom, '_', ' ') FROM produits",   # fonction replace() autorisée
])
def test_requetes_lecture_acceptees(sql):
    assert valider_sql(sql) == sql.strip()


# --- Requêtes refusées ------------------------------------------------------

@pytest.mark.parametrize("sql", [
    "DROP TABLE ventes",
    "DELETE FROM ventes",
    "UPDATE produits SET prix = 0",
    "INSERT INTO magasins VALUES (99, 'x', 'y', 'z')",
    "ALTER TABLE ventes ADD COLUMN x",
    "PRAGMA table_info(ventes)",
    "CREATE TABLE x (id INTEGER)",
    "ATTACH DATABASE 'autre.db' AS autre",
    "REPLACE INTO magasins VALUES (1, 'x', 'y', 'z')",
    "VACUUM",
    "EXPLAIN SELECT 1",
    "",
    "   ",
])
def test_requetes_non_select_refusees(sql):
    with pytest.raises(RequeteRefusee):
        valider_sql(sql)


@pytest.mark.parametrize("sql", [
    "SELECT 1; DROP TABLE ventes",
    "SELECT 1;",
    "SELECT * FROM ventes; DELETE FROM ventes",
])
def test_point_virgule_refuse(sql):
    with pytest.raises(RequeteRefusee, match=";"):
        valider_sql(sql)


@pytest.mark.parametrize("sql", [
    "WITH x AS (DELETE FROM ventes RETURNING *) SELECT * FROM x",
    "SELECT * FROM ventes WHERE id IN (SELECT id FROM ventes) UNION SELECT 1 FROM pragma_table_info('ventes')",
    "select 1 union select 2 from (drop table ventes)",
    "WITH x AS (SELECT 1) REPLACE INTO magasins VALUES (1, 'a', 'b', 'c')",
])
def test_mots_interdits_caches_refuses(sql):
    with pytest.raises(RequeteRefusee):
        valider_sql(sql)


@pytest.mark.parametrize("sql", [
    "SELECT 1 -- ; DROP TABLE ventes",
    "SELECT /* commentaire */ 1",
])
def test_commentaires_refuses(sql):
    with pytest.raises(RequeteRefusee):
        valider_sql(sql)


# --- LIMIT ------------------------------------------------------------------

def test_limit_ajoute_si_absent():
    assert ajouter_limit("SELECT * FROM ventes").endswith("LIMIT 500")


@pytest.mark.parametrize("sql", [
    "SELECT * FROM ventes LIMIT 10",
    "SELECT * FROM ventes limit 10 offset 20",
    "SELECT * FROM ventes LIMIT 5, 10",
])
def test_limit_conserve_si_present(sql):
    assert ajouter_limit(sql) == sql


def test_limit_de_sous_requete_ne_compte_pas():
    sql = "SELECT * FROM (SELECT * FROM ventes LIMIT 10) ORDER BY id"
    assert ajouter_limit(sql).endswith("LIMIT 500")


def test_securiser_requete_valide_puis_limite():
    assert securiser_requete("SELECT 1") == "SELECT 1\nLIMIT 500"
    with pytest.raises(RequeteRefusee):
        securiser_requete("DROP TABLE ventes")


# --- Nettoyage de la réponse du modèle --------------------------------------

def test_nettoyer_retire_balises_et_point_virgule():
    assert nettoyer_sql("```sql\nSELECT 1;\n```") == "SELECT 1"
    assert nettoyer_sql("SELECT 1 ;  ") == "SELECT 1"


# --- Lecture seule au niveau de SQLite ---------------------------------------

def test_connexion_en_lecture_seule(base_vide):
    conn = ouvrir_lecture_seule(base_vide)
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        conn.execute("INSERT INTO t VALUES (1)")
    conn.close()


# --- Autorisateur SQLite (2e couche, indépendante du filtre) ----------------

@pytest.mark.parametrize("sql", [
    "INSERT INTO t VALUES (1)",
    "DELETE FROM t",
    "SELECT * FROM pragma_table_info('t')",
    "ATTACH DATABASE ':memory:' AS autre",
    "CREATE TEMP TABLE x (id INTEGER)",
])
def test_autorisateur_bloque_hors_lecture(base_vide, sql):
    conn = ouvrir_connexion_securisee(base_vide)
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute(sql)
    conn.close()


def test_autorisateur_laisse_passer_les_lectures(base_vide):
    conn = ouvrir_connexion_securisee(base_vide)
    sql = "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < 3) SELECT COUNT(*) FROM n"
    assert conn.execute(sql).fetchone() == (3,)
    assert conn.execute("SELECT COUNT(*), UPPER('a') FROM t").fetchone() == (2, "A")
    conn.close()


def test_requete_trop_longue_interrompue(base_vide):
    conn = ouvrir_connexion_securisee(base_vide, timeout_s=0.2)
    sql = "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n) SELECT MAX(i) FROM n"
    with pytest.raises(sqlite3.OperationalError, match="interrupted"):
        conn.execute(sql).fetchone()
    conn.close()
