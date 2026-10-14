"""Accès aux données : lecture du schéma, exécution sécurisée, import de fichiers."""

import io
import re
import sqlite3
import unicodedata
from contextlib import closing
from pathlib import Path

import pandas as pd

from text2sql.securite import ouvrir_connexion_securisee, ouvrir_lecture_seule

ENTETE_SQLITE = b"SQLite format 3\x00"
MAX_VALEURS_LISTEES = 15


class ImportInvalide(Exception):
    """Levée quand un fichier importé n'est pas exploitable."""


# --- Schéma ------------------------------------------------------------------

def ident(nom: str) -> str:
    """Identifiant SQL entre guillemets, guillemets internes doublés (noms issus d'un fichier importé)."""
    return '"' + nom.replace('"', '""') + '"'


def _colonnes(conn: sqlite3.Connection, table: str) -> list[tuple[str, str]]:
    """Liste (nom, type) des colonnes d'une table, lue via PRAGMA."""
    return [(r[1], r[2] or "TEXT") for r in conn.execute(f"PRAGMA table_info({ident(table)})")]


def _decrire_colonne(conn: sqlite3.Connection, table: str, nom: str, type_col: str) -> str:
    """Une ligne de schéma, enrichie des valeurs possibles ou de l'étendue des dates."""
    detail = f"  - {nom} {type_col}"
    if "date" in nom.lower():
        debut, fin = conn.execute(f"SELECT MIN({ident(nom)}), MAX({ident(nom)}) FROM {ident(table)}").fetchone()
        return f"{detail} (du {debut} au {fin})"
    if type_col.upper() == "TEXT":
        valeurs = conn.execute(
            f"SELECT DISTINCT {ident(nom)} FROM {ident(table)} WHERE {ident(nom)} IS NOT NULL LIMIT ?",
            (MAX_VALEURS_LISTEES + 1,)).fetchall()
        if len(valeurs) <= MAX_VALEURS_LISTEES:
            detail += f" (valeurs : {', '.join(repr(v[0]) for v in valeurs)})"
    return detail


def decrire_table(conn: sqlite3.Connection, table: str) -> str:
    """Décrit une table : nombre de lignes et colonnes enrichies."""
    nb = conn.execute(f"SELECT COUNT(*) FROM {ident(table)}").fetchone()[0]
    lignes = [f"Table {table} ({nb} lignes) :"]
    lignes += [_decrire_colonne(conn, table, nom, t) for nom, t in _colonnes(conn, table)]
    return "\n".join(lignes)


def lister_tables(chemin: Path) -> list[str]:
    """Noms des tables utilisateur de la base."""
    with closing(ouvrir_lecture_seule(chemin)) as conn:
        return [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name")]


def lire_schema(chemin: Path) -> str:
    """Lit automatiquement le schéma complet de la base (PRAGMA) sous forme de texte."""
    tables = lister_tables(chemin)
    with closing(ouvrir_lecture_seule(chemin)) as conn:
        return "\n\n".join(decrire_table(conn, t) for t in tables)


# --- Exécution ---------------------------------------------------------------

def executer_requete(chemin: Path, sql: str) -> pd.DataFrame:
    """Exécute une requête déjà validée sur une connexion verrouillée."""
    with closing(ouvrir_connexion_securisee(chemin)) as conn:
        return pd.read_sql_query(sql, conn)


# --- Import de fichiers utilisateur -----------------------------------------

def normaliser_nom(nom: str) -> str:
    """Transforme un nom libre en identifiant SQL sûr (snake_case ASCII)."""
    ascii_ = unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode()
    propre = re.sub(r"[^a-z0-9]+", "_", ascii_.lower()).strip("_") or "table"
    return f"t_{propre}" if propre[0].isdigit() else propre


def lire_csv(contenu: bytes) -> pd.DataFrame:
    """Lit un CSV en devinant le séparateur et l'encodage (UTF-8 puis Latin-1)."""
    for encodage in ("utf-8-sig", "latin-1"):
        try:
            return pd.read_csv(io.BytesIO(contenu), sep=None, engine="python", encoding=encodage)
        except UnicodeDecodeError:
            continue
        except (pd.errors.ParserError, pd.errors.EmptyDataError) as e:
            raise ImportInvalide(f"CSV illisible : {e}") from e
    raise ImportInvalide("Encodage du CSV non reconnu.")


def noms_uniques(noms: list[str]) -> list[str]:
    """Normalise des noms de colonnes et suffixe les doublons (_2, _3…)."""
    vus, resultat = {}, []
    for nom in map(normaliser_nom, noms):
        vus[nom] = vus.get(nom, 0) + 1
        resultat.append(nom if vus[nom] == 1 else f"{nom}_{vus[nom]}")
    return resultat


def _preparer_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise les noms de colonnes et convertit les dates au format ISO."""
    df.columns = noms_uniques([str(c) for c in df.columns])
    for col in df.columns:
        if "date" in col and not pd.api.types.is_numeric_dtype(df[col]):
            dates = pd.to_datetime(df[col], errors="coerce", dayfirst=True)
            if dates.notna().mean() > 0.9:
                df[col] = dates.dt.strftime("%Y-%m-%d")
    return df


def importer_fichiers(fichiers: list[tuple[str, bytes]], destination: Path) -> Path:
    """Crée une base SQLite à partir de fichiers CSV, ou copie une base SQLite fournie."""
    destination.unlink(missing_ok=True)
    bases = [(n, c) for n, c in fichiers if c.startswith(ENTETE_SQLITE)]
    if bases:
        if len(fichiers) > 1:
            raise ImportInvalide("Importez soit une seule base SQLite, soit un ou plusieurs CSV.")
        destination.write_bytes(bases[0][1])
        try:
            tables = lister_tables(destination)
        except sqlite3.DatabaseError as e:
            raise ImportInvalide(f"Base SQLite illisible : {e}") from e
        if not tables:
            raise ImportInvalide("La base SQLite importée ne contient aucune table.")
        return destination
    with closing(sqlite3.connect(destination)) as conn:
        for nom, contenu in fichiers:
            if not nom.lower().endswith((".csv", ".txt")):
                raise ImportInvalide(f"Format non pris en charge : {nom} (CSV ou SQLite attendu).")
            df = _preparer_dataframe(lire_csv(contenu))
            df.to_sql(normaliser_nom(Path(nom).stem), conn, index=False, if_exists="replace")
        conn.commit()
    return destination
