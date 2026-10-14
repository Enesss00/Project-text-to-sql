"""Mode démo : questions pré-enregistrées, utilisables sans clé API.

Le SQL est fixé à l'avance mais passe par exactement le même pipeline
(filtre de sécurité, connexion verrouillée, graphiques) que le mode connecté.
"""

import sqlite3
import unicodedata
from pathlib import Path

import pandas as pd

from text2sql import base
from text2sql.llm import Resultat
from text2sql.securite import RequeteRefusee, securiser_requete

QUESTIONS_DEMO = {
    "CA par magasin en septembre ?": (
        "SELECT m.nom AS magasin, ROUND(SUM(v.montant), 2) AS chiffre_affaires\n"
        "FROM ventes v JOIN magasins m ON m.id = v.magasin_id\n"
        "WHERE strftime('%m', v.date) = '09'\n"
        "GROUP BY m.nom ORDER BY chiffre_affaires DESC"),
    "Et pour octobre ?": (
        "SELECT m.nom AS magasin, ROUND(SUM(v.montant), 2) AS chiffre_affaires\n"
        "FROM ventes v JOIN magasins m ON m.id = v.magasin_id\n"
        "WHERE strftime('%m', v.date) = '10'\n"
        "GROUP BY m.nom ORDER BY chiffre_affaires DESC"),
    "Évolution mensuelle du chiffre d'affaires": (
        "SELECT strftime('%Y-%m', date) AS mois, ROUND(SUM(montant), 2) AS chiffre_affaires\n"
        "FROM ventes GROUP BY mois ORDER BY mois"),
    "CA mensuel par région": (
        "SELECT strftime('%Y-%m', v.date) AS mois, m.region, ROUND(SUM(v.montant), 2) AS chiffre_affaires\n"
        "FROM ventes v JOIN magasins m ON m.id = v.magasin_id\n"
        "GROUP BY mois, m.region ORDER BY mois"),
    "Top 10 des produits en Électronique": (
        "SELECT p.nom AS produit, ROUND(SUM(v.montant), 2) AS chiffre_affaires\n"
        "FROM ventes v JOIN produits p ON p.id = v.produit_id\n"
        "WHERE p.categorie = 'Électronique'\n"
        "GROUP BY p.nom ORDER BY chiffre_affaires DESC LIMIT 10"),
    "Panier moyen en décembre": (
        "SELECT ROUND(AVG(montant), 2) AS panier_moyen FROM ventes\n"
        "WHERE strftime('%m', date) = '12'"),
    "Supprime toutes les ventes": "DELETE FROM ventes",
}


def _normaliser(texte: str) -> str:
    """Minuscules sans accents ni ponctuation finale, pour une recherche tolérante."""
    sans_accents = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode()
    return " ".join(sans_accents.lower().strip(" ?!.").split())


_INDEX = {_normaliser(q): sql for q, sql in QUESTIONS_DEMO.items()}


def repondre(question: str, chemin_db: Path) -> Resultat:
    """Répond à une question de démo avec le pipeline d'exécution réel."""
    res = Resultat(question=question, tentatives=1)
    sql = _INDEX.get(_normaliser(question))
    if sql is None:
        res.erreur = ("En mode démo, seules les questions suggérées sont disponibles. "
                      "Ajoutez une clé ANTHROPIC_API_KEY pour poser vos propres questions.")
        return res
    res.sql = sql
    try:
        res.sql = securiser_requete(sql)
        res.df = base.executer_requete(chemin_db, res.sql)
    except (RequeteRefusee, sqlite3.Error, pd.errors.DatabaseError) as e:
        res.erreur, res.bloquee = str(e), isinstance(e, RequeteRefusee)
    return res
