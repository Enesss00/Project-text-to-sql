"""Sécurité SQL en trois couches.

1. Filtre syntaxique : une seule instruction SELECT/WITH, sans mot-clé dangereux.
2. Autorisateur SQLite : le moteur lui-même refuse toute opération autre que la lecture,
   ainsi que la lecture des colonnes protégées par la gouvernance (données personnelles).
3. Connexion en lecture seule (mode=ro) avec délai maximal d'exécution.
"""

import re
import sqlite3
import time
from pathlib import Path
from urllib.parse import quote

from text2sql.config import LIMITE_LIGNES, TIMEOUT_REQUETE_S

MOTS_INTERDITS = (
    "DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "PRAGMA", "CREATE",
    "ATTACH", "DETACH", "VACUUM", "REINDEX", "TRUNCATE", "GRANT", "REVOKE",
)

# Actions SQLite autorisées par l'autorisateur (lecture uniquement)
ACTIONS_AUTORISEES = {
    sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_FUNCTION,
    getattr(sqlite3, "SQLITE_RECURSIVE", 33),  # CTE récursives (WITH RECURSIVE)
}


class RequeteRefusee(Exception):
    """Levée quand une requête SQL ne passe pas le filtre de sécurité."""


class ColonneProtegee(RequeteRefusee):
    """Levée quand une requête lit une colonne protégée par la gouvernance."""


# --- Couche 1 : filtre syntaxique --------------------------------------------

def nettoyer_sql(texte: str) -> str:
    """Extrait le SQL d'une réponse du modèle (retire balises ``` et ';' final)."""
    texte = texte.strip()
    bloc = re.search(r"```(?:sql)?\s*(.*?)```", texte, re.DOTALL | re.IGNORECASE)
    if bloc:
        texte = bloc.group(1).strip()
    return texte.rstrip().rstrip(";").rstrip()


def valider_sql(sql: str) -> str:
    """Vérifie que la requête est une simple lecture. Lève RequeteRefusee sinon."""
    sql = sql.strip()
    if not sql:
        raise RequeteRefusee("Requête vide.")
    if ";" in sql:
        raise RequeteRefusee("Le caractère ';' est interdit (une seule instruction autorisée).")
    if "--" in sql or "/*" in sql:
        raise RequeteRefusee("Les commentaires SQL sont interdits.")
    if not re.match(r"^(SELECT|WITH)\b", sql, re.IGNORECASE):
        raise RequeteRefusee("Seules les requêtes commençant par SELECT ou WITH sont autorisées.")
    # \bPRAGMA_ couvre aussi les fonctions pragma_xxx(), contournement possible de PRAGMA ;
    # REPLACE n'est interdit que suivi de INTO, la fonction replace() restant autorisée
    interdit = re.search(rf"\b({'|'.join(MOTS_INTERDITS)})\b|\b(PRAGMA)_|\b(REPLACE)\s+INTO\b",
                         sql, re.IGNORECASE)
    if interdit:
        mot = next(g for g in interdit.groups() if g)
        raise RequeteRefusee(f"Mot-clé interdit : {mot.upper()}.")
    return sql


def ajouter_limit(sql: str, limite: int = LIMITE_LIGNES) -> str:
    """Ajoute un LIMIT à la requête principale s'il n'y en a pas déjà un à la fin."""
    if re.search(r"\bLIMIT\s+\d+(\s*(,|OFFSET)\s*\d+)?\s*$", sql, re.IGNORECASE):
        return sql
    return f"{sql}\nLIMIT {limite}"


def securiser_requete(sql: str) -> str:
    """Valide la requête puis garantit la présence d'un LIMIT."""
    return ajouter_limit(valider_sql(sql))


# --- Couches 2 et 3 : connexion verrouillée ----------------------------------

def creer_autorisateur(colonnes_protegees: frozenset[str] = frozenset()):
    """Callback SQLite : lecture seule, et aucune lecture des colonnes « table.colonne » protégées."""
    def autoriser(action, table, colonne, *_):
        if action not in ACTIONS_AUTORISEES:
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_READ and f"{table}.{colonne}".lower() in colonnes_protegees:
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    return autoriser


def traduire_refus(erreur: sqlite3.DatabaseError) -> Exception:
    """Transforme un refus de l'autorisateur sur une colonne en ColonneProtegee explicite."""
    refus = re.search(r"access to (\S+) is prohibited", str(erreur))
    if refus:
        return ColonneProtegee(f"Colonne protégée par la politique de gouvernance : {refus.group(1)}.")
    return erreur


def _limiteur_de_temps(timeout_s: float):
    """Renvoie un callback qui interrompt la requête au-delà de timeout_s secondes."""
    fin = time.monotonic() + timeout_s
    return lambda: 1 if time.monotonic() > fin else 0


def ouvrir_lecture_seule(chemin: Path) -> sqlite3.Connection:
    """Ouvre la base en lecture seule (mode=ro), sans verrou applicatif."""
    return sqlite3.connect(f"file:{quote(str(Path(chemin).resolve()))}?mode=ro", uri=True)


def ouvrir_connexion_securisee(chemin: Path, timeout_s: float = TIMEOUT_REQUETE_S,
                               colonnes_protegees: frozenset[str] = frozenset()) -> sqlite3.Connection:
    """Connexion pour exécuter du SQL généré : lecture seule + autorisateur + délai maximal."""
    conn = ouvrir_lecture_seule(chemin)
    conn.set_authorizer(creer_autorisateur(colonnes_protegees))
    conn.set_progress_handler(_limiteur_de_temps(timeout_s), 10_000)
    return conn
