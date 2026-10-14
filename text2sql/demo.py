"""Mode démo : questions pré-enregistrées du profil, utilisables sans clé API.

Le SQL est fixé à l'avance mais passe par exactement le même pipeline
(filtre de sécurité, connexion verrouillée, gouvernance, graphiques) que le mode connecté.
"""

import sqlite3
import unicodedata

import pandas as pd

from text2sql import base
from text2sql.llm import Resultat
from text2sql.profils import Profil
from text2sql.securite import RequeteRefusee, securiser_requete


def normaliser(texte: str) -> str:
    """Minuscules sans accents ni ponctuation finale, pour une recherche tolérante."""
    sans_accents = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode()
    return " ".join(sans_accents.lower().strip(" ?!.").split())


def trouver_sql(question: str, profil: Profil) -> str | None:
    """SQL pré-enregistré correspondant à la question, s'il existe."""
    index = {normaliser(q): sql for q, sql in profil.questions_demo}
    return index.get(normaliser(question))


def repondre(question: str, profil: Profil) -> Resultat:
    """Répond à une question de démo avec le pipeline d'exécution réel."""
    res = Resultat(question=question, tentatives=1)
    sql = trouver_sql(question, profil)
    if sql is None:
        res.erreur = ("En mode démo, seules les questions suggérées sont disponibles. "
                      "Configurez l'accès au modèle pour poser vos propres questions.")
        return res
    res.sql = sql
    try:
        res.sql = securiser_requete(sql)
        res.df = base.executer_requete(profil.base, res.sql, profil.colonnes_protegees)
    except (RequeteRefusee, sqlite3.Error, pd.errors.DatabaseError) as e:
        res.erreur, res.bloquee = str(e), isinstance(e, RequeteRefusee)
    return res
