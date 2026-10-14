"""Application Streamlit de text-to-SQL : question en français → SQL (Claude) → SQLite.

Lancement : streamlit run app.py
"""

import os
import re
import sqlite3
from contextlib import closing
from pathlib import Path

import anthropic
import pandas as pd
import streamlit as st

# --- Configuration ---------------------------------------------------------

DB_PATH = Path(os.environ.get("TEXT2SQL_DB", "retail.db"))
MODELE = "claude-opus-5-5"
MAX_CORRECTIONS = 2  # nombre d'essais de correction automatique après un échec
LIMITE_LIGNES = 500

MOTS_INTERDITS = (
    "DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "PRAGMA", "CREATE", "REPLACE",
    "ATTACH", "DETACH", "VACUUM", "REINDEX", "TRUNCATE", "GRANT", "REVOKE",
)

EXEMPLES_FEW_SHOT = [
    (
        "Quel est le chiffre d'affaires total ?",
        "SELECT ROUND(SUM(montant), 2) AS chiffre_affaires FROM ventes",
    ),
    (
        "CA par magasin en mars",
        "SELECT m.nom AS magasin, ROUND(SUM(v.montant), 2) AS chiffre_affaires\n"
        "FROM ventes v JOIN magasins m ON m.id = v.magasin_id\n"
        "WHERE strftime('%m', v.date) = '03'\n"
        "GROUP BY m.nom ORDER BY chiffre_affaires DESC",
    ),
    (
        "Évolution mensuelle des ventes de la catégorie Sport",
        "SELECT strftime('%Y-%m', v.date) AS mois, ROUND(SUM(v.montant), 2) AS chiffre_affaires\n"
        "FROM ventes v JOIN produits p ON p.id = v.produit_id\n"
        "WHERE p.categorie = 'Sport'\n"
        "GROUP BY mois ORDER BY mois",
    ),
    (
        "Top 5 des produits les plus vendus en quantité",
        "SELECT p.nom AS produit, SUM(v.quantite) AS quantite_vendue\n"
        "FROM ventes v JOIN produits p ON p.id = v.produit_id\n"
        "GROUP BY p.nom ORDER BY quantite_vendue DESC LIMIT 5",
    ),
]


class RequeteRefusee(Exception):
    """Levée quand une requête SQL ne passe pas le filtre de sécurité."""


# --- Sécurité : validation de la requête -----------------------------------

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
    # \bPRAGMA_ couvre aussi les fonctions pragma_xxx(), contournement possible de PRAGMA
    interdit = re.search(rf"\b({'|'.join(MOTS_INTERDITS)})\b|\b(PRAGMA)_", sql, re.IGNORECASE)
    if interdit:
        mot = interdit.group(1) or interdit.group(2)
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


# --- Base de données --------------------------------------------------------

def ouvrir_connexion() -> sqlite3.Connection:
    """Ouvre la base SQLite en lecture seule (mode=ro)."""
    return sqlite3.connect(f"file:{DB_PATH.resolve()}?mode=ro", uri=True)


def executer_requete(sql: str) -> pd.DataFrame:
    """Exécute une requête déjà validée et renvoie un DataFrame."""
    with closing(ouvrir_connexion()) as conn:
        return pd.read_sql_query(sql, conn)


def decrire_table(conn: sqlite3.Connection, table: str) -> str:
    """Décrit une table (colonnes, types, valeurs possibles des petites colonnes texte)."""
    lignes = [f"Table {table} :"]
    for _, nom, type_col, *_ in conn.execute(f"PRAGMA table_info('{table}')"):
        detail = f"  - {nom} {type_col}"
        if type_col.upper() == "TEXT":
            valeurs = conn.execute(f'SELECT DISTINCT "{nom}" FROM "{table}" LIMIT 16').fetchall()
            if len(valeurs) <= 15:
                detail += f" (valeurs : {', '.join(repr(v[0]) for v in valeurs)})"
        lignes.append(detail)
    return "\n".join(lignes)


@st.cache_data
def lire_schema() -> str:
    """Lit automatiquement le schéma de la base via PRAGMA, plus la période couverte."""
    with closing(ouvrir_connexion()) as conn:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
        description = "\n\n".join(decrire_table(conn, t) for t in tables)
        debut, fin = conn.execute("SELECT MIN(date), MAX(date) FROM ventes").fetchone()
    return f"{description}\n\nLes ventes couvrent la période du {debut} au {fin}."


# --- Prompt et appel au modèle ----------------------------------------------

def construire_prompt_systeme(schema: str) -> str:
    """Assemble le prompt système : rôle, règles, schéma et exemples few-shot."""
    exemples = "\n\n".join(f"Question : {q}\nSQL :\n{s}" for q, s in EXEMPLES_FEW_SHOT)
    return f"""Tu traduis des questions en français en requêtes SQL pour SQLite.

Règles :
- Réponds UNIQUEMENT avec la requête SQL : aucune explication, aucun texte, aucune balise markdown.
- Une seule requête, en lecture seule, commençant par SELECT ou WITH, sans point-virgule ni commentaire.
- Les dates sont du texte au format YYYY-MM-DD : utilise strftime() pour filtrer par mois ou année.
- « CA » ou « chiffre d'affaires » = SUM(ventes.montant). Arrondis les montants à 2 décimales.
- Donne des alias lisibles en snake_case aux colonnes calculées.
- Pour une série temporelle, mets la colonne de temps en premier et trie par cette colonne.
- Les questions de suivi (« et pour octobre ? ») modifient la requête précédente de la conversation.
- Si la question ne peut pas être traduite avec ce schéma, réponds :
  SELECT 'Question hors du périmètre de la base' AS message

Schéma de la base :
{schema}

Exemples :

{exemples}"""


def appeler_modele(client: anthropic.Anthropic, systeme: str, messages: list[dict]) -> str:
    """Envoie la conversation au modèle et renvoie le SQL nettoyé."""
    reponse = client.beta.messages.create(
        model=MODELE,
        max_tokens=16000,
        system=[{"type": "text", "text": systeme, "cache_control": {"type": "ephemeral"}}],
        messages=messages,
        output_config={"effort": "low"},
        # Si un filtre de sécurité refuse la requête, l'API bascule sur un autre modèle.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if reponse.stop_reason == "refusal":
        raise RuntimeError("Le modèle a refusé de répondre à cette question.")
    texte = "".join(b.text for b in reponse.content if b.type == "text")
    return nettoyer_sql(texte)


def message_correction(erreur: str) -> str:
    """Message renvoyé au modèle pour qu'il corrige sa requête."""
    return (f"Cette requête a échoué avec l'erreur suivante : {erreur}\n"
            "Corrige-la. Réponds uniquement avec la requête SQL corrigée.")


def generer_et_executer(client, systeme, historique, question):
    """Génère le SQL, l'exécute, et retente jusqu'à MAX_CORRECTIONS fois en cas d'erreur.

    Renvoie (sql, dataframe, erreur) : dataframe vaut None si tout a échoué.
    """
    messages = historique + [{"role": "user", "content": question}]
    sql, erreur = "", ""
    for _ in range(1 + MAX_CORRECTIONS):
        sql = appeler_modele(client, systeme, messages)
        try:
            sql_sur = securiser_requete(sql)
            return sql_sur, executer_requete(sql_sur), None
        except (RequeteRefusee, sqlite3.Error, pd.errors.DatabaseError) as e:
            erreur = str(e)
            messages = messages + [
                {"role": "assistant", "content": sql or "(réponse vide)"},
                {"role": "user", "content": message_correction(erreur)},
            ]
    return sql, None, erreur


# --- Choix automatique du graphique ----------------------------------------

NOMS_TEMPORELS = ("date", "jour", "semaine", "mois", "trimestre", "annee", "année", "month", "year", "day")


def est_temporelle(colonne: pd.Series) -> bool:
    """Vrai si la colonne ressemble à une dimension de temps (nom ou format de date)."""
    if any(mot in str(colonne.name).lower() for mot in NOMS_TEMPORELS):
        return True
    valeurs = colonne.dropna().astype(str)
    return not valeurs.empty and valeurs.str.match(r"^\d{4}-\d{2}(-\d{2})?").all()


def choisir_graphique(df: pd.DataFrame):
    """Renvoie (type, x, y) avec type 'ligne' ou 'barres', ou None si pas de graphique."""
    if df is None or len(df) < 2 or len(df.columns) < 2:
        return None
    numeriques = list(df.select_dtypes("number").columns)
    non_numeriques = [c for c in df.columns if c not in numeriques]
    x = non_numeriques[0] if non_numeriques else df.columns[0]
    candidats_y = [c for c in numeriques if c != x]
    if not candidats_y:
        return None
    return ("ligne" if est_temporelle(df[x]) else "barres"), x, candidats_y[0]


def afficher_graphique(df: pd.DataFrame) -> None:
    """Affiche le graphique adapté aux données, s'il y en a un."""
    choix = choisir_graphique(df)
    if choix is None:
        return
    type_graphique, x, y = choix
    if type_graphique == "ligne":
        st.line_chart(df.sort_values(x), x=x, y=y)
    else:
        st.bar_chart(df, x=x, y=y)


# --- Interface Streamlit ----------------------------------------------------

def afficher_reponse(message: dict) -> None:
    """Affiche une réponse : SQL dans un expander, puis tableau et graphique, ou l'erreur."""
    with st.expander("SQL généré", expanded=message["df"] is None):
        st.code(message["sql"] or "(aucune requête)", language="sql")
    if message["df"] is None:
        st.error("Je n'ai pas réussi à répondre à cette question, même après "
                 f"{MAX_CORRECTIONS} tentatives de correction. Essayez de la reformuler.\n\n"
                 f"Dernière erreur : {message['erreur']}")
        return
    df = message["df"]
    if df.empty:
        st.info("La requête n'a renvoyé aucun résultat.")
        return
    st.dataframe(df, hide_index=True)
    afficher_graphique(df)


def initialiser_session() -> None:
    """Prépare l'historique affiché et l'historique envoyé au modèle."""
    st.session_state.setdefault("messages", [])     # pour l'affichage
    st.session_state.setdefault("historique", [])   # paires question/SQL pour le modèle


def afficher_barre_laterale() -> None:
    """Barre latérale : exemples de questions et réinitialisation."""
    with st.sidebar:
        st.markdown("**Exemples de questions**\n\n"
                    "- CA par magasin en septembre ?\n- Et pour octobre ?\n"
                    "- Évolution mensuelle du CA\n- Top 10 des produits en Électronique")
        if st.button("Nouvelle conversation"):
            st.session_state.messages = []
            st.session_state.historique = []
            st.rerun()


def traiter_question(client, question: str) -> None:
    """Traite une nouvelle question et met à jour les historiques."""
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        with st.spinner("Génération de la requête…"):
            try:
                systeme = construire_prompt_systeme(lire_schema())
                sql, df, erreur = generer_et_executer(
                    client, systeme, st.session_state.historique, question)
            except (anthropic.APIError, RuntimeError) as e:
                sql, df, erreur = "", None, f"Erreur de l'API Claude : {e}"
        message = {"role": "assistant", "sql": sql, "df": df, "erreur": erreur}
        afficher_reponse(message)
    st.session_state.messages.append(message)
    if df is not None:  # on ne mémorise que les échanges réussis
        st.session_state.historique += [
            {"role": "user", "content": question},
            {"role": "assistant", "content": sql},
        ]


def main() -> None:
    st.set_page_config(page_title="Text-to-SQL", page_icon="📊")
    st.title("📊 Interrogez vos ventes en français")

    if not DB_PATH.exists():
        st.error(f"Base introuvable : {DB_PATH}. Lancez d'abord `python seed_db.py`.")
        st.stop()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        st.error("La variable d'environnement ANTHROPIC_API_KEY n'est pas définie.")
        st.stop()

    initialiser_session()
    afficher_barre_laterale()
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            if message["role"] == "user":
                st.markdown(message["content"])
            else:
                afficher_reponse(message)

    question = st.chat_input("Posez votre question (ex. : CA par magasin en septembre ?)")
    if question:
        traiter_question(anthropic.Anthropic(), question)


if __name__ == "__main__":
    main()
