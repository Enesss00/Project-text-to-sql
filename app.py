"""Application Streamlit de text-to-SQL : question en français → SQL (Claude) → SQLite.

Lancement : streamlit run app.py
Sans clé ANTHROPIC_API_KEY, l'application démarre en mode démo.
"""

import tempfile
from pathlib import Path

import anthropic
import streamlit as st

from text2sql import base, demo, graphiques, llm
from text2sql.config import DB_DEMO, MAX_CORRECTIONS, MODELE, TAILLE_MAX_IMPORT_MO, cle_api_disponible
from text2sql.journal import journaliser
from text2sql.llm import Consommation, Resultat

SUGGESTIONS_API = [
    "CA par magasin en septembre ?",
    "Évolution mensuelle du chiffre d'affaires",
    "CA mensuel par région",
    "Top 10 des produits en Électronique",
    "Panier moyen par catégorie",
    "Quels clients ont dépensé plus de 500 € ?",
]


# --- État de session ----------------------------------------------------------

def initialiser_session() -> None:
    """Valeurs par défaut de l'état de session."""
    st.session_state.setdefault("messages", [])          # pour l'affichage
    st.session_state.setdefault("historique", [])        # paires question/SQL pour le modèle
    st.session_state.setdefault("consommation", Consommation())
    st.session_state.setdefault("chemin_db", DB_DEMO)
    st.session_state.setdefault("base_demo", True)
    st.session_state.setdefault("signature_import", None)
    st.session_state.setdefault("question_suggeree", None)


def reinitialiser_conversation() -> None:
    """Efface l'historique de conversation (garde la source de données)."""
    st.session_state.messages = []
    st.session_state.historique = []


def mode_api() -> bool:
    return cle_api_disponible()


def theme_actuel() -> str:
    """Thème Streamlit courant, pour choisir les couleurs des graphiques."""
    return "sombre" if getattr(st.context.theme, "type", None) == "dark" else "clair"


@st.cache_data(show_spinner=False)
def schema_en_cache(chemin: str, _version: float) -> str:
    """Schéma de la base, recalculé seulement si le fichier change."""
    return base.lire_schema(Path(chemin))


def schema_courant() -> str:
    chemin = Path(st.session_state.chemin_db)
    return schema_en_cache(str(chemin), chemin.stat().st_mtime)


# --- Barre latérale ---------------------------------------------------------

def importer_donnees(fichiers) -> None:
    """Importe les fichiers déposés dans une base temporaire propre à la session."""
    signature = tuple((f.name, f.size) for f in fichiers)
    if signature == st.session_state.signature_import:
        return
    if any(f.size > TAILLE_MAX_IMPORT_MO * 1024 * 1024 for f in fichiers):
        st.sidebar.error(f"Fichier trop volumineux (maximum {TAILLE_MAX_IMPORT_MO} Mo).")
        return
    dossier = Path(tempfile.mkdtemp(prefix="text2sql_"))
    try:
        chemin = base.importer_fichiers([(f.name, f.getvalue()) for f in fichiers], dossier / "import.db")
    except base.ImportInvalide as e:
        st.sidebar.error(str(e))
        return
    st.session_state.update(chemin_db=chemin, base_demo=False, signature_import=signature)
    reinitialiser_conversation()


def choisir_source() -> None:
    """Sélection de la source de données : base de démo ou fichiers de l'utilisateur."""
    st.sidebar.subheader("Données")
    if not mode_api():
        st.sidebar.caption("Base de démo (retail). L'import de vos fichiers nécessite une clé API.")
        return
    source = st.sidebar.radio("Source", ["Base de démo (retail)", "Mes fichiers"],
                              label_visibility="collapsed")
    if source.startswith("Base de démo"):
        if not st.session_state.base_demo:
            st.session_state.update(chemin_db=DB_DEMO, base_demo=True, signature_import=None)
            reinitialiser_conversation()
        return
    fichiers = st.sidebar.file_uploader("CSV (une table par fichier) ou base SQLite",
                                        type=["csv", "txt", "db", "sqlite", "sqlite3"],
                                        accept_multiple_files=True)
    if fichiers:
        importer_donnees(fichiers)


def afficher_schema() -> None:
    """Explorateur du schéma détecté."""
    with st.sidebar.expander("Schéma détecté"):
        st.text(schema_courant())


def afficher_consommation() -> None:
    """Tokens et coût estimé cumulés sur la session."""
    conso = st.session_state.consommation
    total = conso.entree + conso.cache_lu + conso.cache_ecrit + conso.sortie
    st.sidebar.subheader("Consommation de la session")
    col1, col2 = st.sidebar.columns(2)
    col1.metric("Tokens", f"{total:,}".replace(",", " "))
    col2.metric("Coût estimé", f"{conso.cout():.3f} $")


def afficher_barre_laterale() -> None:
    with st.sidebar:
        st.title("📊 Text-to-SQL")
        if mode_api():
            st.success(f"Connecté à Claude · `{MODELE}`", icon="✅")
        else:
            st.info("**Mode démo** : questions pré-enregistrées, sans clé API. "
                    "Définissez `ANTHROPIC_API_KEY` pour poser vos propres questions.", icon="🎬")
    choisir_source()
    afficher_schema()
    if mode_api():
        st.sidebar.toggle("Synthèse en langage naturel", value=True, key="synthese_active")
        afficher_consommation()
    st.sidebar.button("Nouvelle conversation", on_click=reinitialiser_conversation,
                      use_container_width=True)


# --- Affichage d'une réponse ----------------------------------------------

MOTS_MONETAIRES = ("montant", "chiffre", "ca", "prix", "panier", "cout", "revenu", "depense")


def formater_nombre(valeur, colonne: str = "") -> str:
    """Nombre au format français (espace fine pour les milliers, virgule), avec € si monétaire."""
    if not isinstance(valeur, (int, float)):
        return str(valeur)
    texte = f"{valeur:,.2f}".replace(",", "\u202f").replace(".", ",").removesuffix(",00")
    mots = colonne.lower().split("_")
    return f"{texte} €" if any(m in MOTS_MONETAIRES for m in mots) else texte


def afficher_erreur(res: Resultat) -> None:
    """Message clair en cas de requête bloquée ou d'échec définitif."""
    if res.bloquee:
        st.warning(f"🔒 **Requête bloquée par le filtre de sécurité.** {res.erreur}\n\n"
                   "Seules les lectures de données sont autorisées.")
    elif res.sql:
        st.error("Je n'ai pas réussi à répondre à cette question, même après "
                 f"{MAX_CORRECTIONS} tentatives de correction. Essayez de la reformuler.\n\n"
                 f"Dernière erreur : `{res.erreur}`")
    else:
        st.error(res.erreur)


def afficher_resultats(res: Resultat, index: int) -> None:
    """Indicateur ou tableau + graphique, avec export CSV."""
    df = res.df
    if df.empty:
        st.info("La requête n'a renvoyé aucun résultat.")
        return
    choix = graphiques.choisir_graphique(df)
    if choix and choix.type == "kpi":
        st.metric(choix.y.replace("_", " ").capitalize(), formater_nombre(df.iloc[0, 0], choix.y))
        return
    formats = {c: st.column_config.NumberColumn(format="localized")
               for c in df.select_dtypes("number").columns}
    st.dataframe(df, hide_index=True, use_container_width=True, column_config=formats)
    if choix:
        st.altair_chart(graphiques.construire_graphique(df, choix, theme_actuel()),
                        use_container_width=True, theme=None)
    st.download_button("⬇️ Exporter en CSV", df.to_csv(index=False).encode("utf-8"),
                       file_name="resultats.csv", mime="text/csv", key=f"export_{index}")


def afficher_reponse(res: Resultat, index: int) -> None:
    """SQL dans un expander, puis synthèse, résultats et métadonnées."""
    if res.sql:
        with st.expander("SQL généré", expanded=not res.succes):
            st.code(res.sql, language="sql")
    if not res.succes:
        afficher_erreur(res)
        return
    if res.synthese:
        st.markdown(res.synthese)
    afficher_resultats(res, index)
    details = [f"{len(res.df)} ligne(s)", f"{res.tentatives} tentative(s)"]
    if res.consommation.entree:
        details.append(f"≈ {res.consommation.cout():.4f} $")
    st.caption(" · ".join(details))


# --- Traitement d'une question -----------------------------------------------

def repondre_api(question: str) -> Resultat:
    """Génère et exécute le SQL avec Claude, puis rédige la synthèse si demandée."""
    client = anthropic.Anthropic()
    systeme = llm.construire_prompt_systeme(schema_courant(), st.session_state.base_demo)
    try:
        res = llm.generer_et_executer(client, systeme, st.session_state.historique,
                                      question, st.session_state.chemin_db)
        if res.succes and not res.df.empty and st.session_state.get("synthese_active", True):
            res.synthese = llm.resumer_resultat(client, question, res.df, res.consommation)
    except (anthropic.APIError, RuntimeError) as e:
        res = Resultat(question=question, erreur=f"Erreur de l'API Claude : {e}")
    return res


def traiter_question(question: str) -> None:
    """Traite une question et met à jour l'affichage, l'historique et le journal."""
    st.session_state.messages.append({"role": "user", "contenu": question})
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        with st.spinner("Analyse de la question…"):
            res = repondre_api(question) if mode_api() else demo.repondre(question, st.session_state.chemin_db)
        afficher_reponse(res, len(st.session_state.messages))
    st.session_state.messages.append({"role": "assistant", "contenu": res})
    st.session_state.consommation.cumuler(res.consommation)
    journaliser(res, "api" if mode_api() else "demo")
    if res.succes:  # on ne mémorise que les échanges réussis
        st.session_state.historique += [{"role": "user", "content": question},
                                        {"role": "assistant", "content": res.sql}]


# --- Page principale ----------------------------------------------------------

def _suggestion_choisie() -> None:
    """Callback des suggestions : envoie la question puis désélectionne la pastille."""
    st.session_state.question_suggeree = st.session_state.suggestions
    st.session_state.suggestions = None


def afficher_suggestions() -> None:
    """Questions cliquables : à l'accueil, et en permanence en mode démo."""
    if not st.session_state.base_demo:
        return
    if mode_api() and st.session_state.messages:
        return
    options = SUGGESTIONS_API if mode_api() else list(demo.QUESTIONS_DEMO)
    st.pills("Essayez :", options, key="suggestions", on_change=_suggestion_choisie)


def afficher_accueil() -> None:
    st.markdown("### Posez vos questions à vos données, en français")
    st.caption("Claude traduit votre question en SQL, l'exécute en lecture seule "
               "et choisit le graphique adapté.")


def afficher_historique() -> None:
    for i, message in enumerate(st.session_state.messages):
        with st.chat_message(message["role"]):
            if message["role"] == "user":
                st.markdown(message["contenu"])
            else:
                afficher_reponse(message["contenu"], i)


def main() -> None:
    st.set_page_config(page_title="Text-to-SQL", page_icon="📊", layout="centered")
    if not DB_DEMO.exists():
        st.error(f"Base introuvable : {DB_DEMO}. Lancez d'abord `python seed_db.py`.")
        st.stop()
    initialiser_session()
    afficher_barre_laterale()
    if not st.session_state.messages:
        afficher_accueil()
    afficher_historique()
    afficher_suggestions()

    question = st.chat_input("Posez votre question (ex. : CA par magasin en septembre ?)")
    question = question or st.session_state.question_suggeree
    st.session_state.question_suggeree = None
    if question:
        traiter_question(question)
        st.rerun()


if __name__ == "__main__":
    main()
