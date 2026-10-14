"""Application Streamlit de text-to-SQL : question en français → SQL (Claude) → SQLite.

Lancement : streamlit run app.py
Sans accès au modèle (clé API ou fournisseur cloud), l'application démarre en mode démo.
"""

import tempfile
from pathlib import Path

import anthropic
import streamlit as st

from text2sql import base, demo, graphiques, llm
from text2sql.config import (
    ENVOYER_VALEURS_EXEMPLES,
    FOURNISSEUR,
    MAX_CORRECTIONS,
    PROFIL_DEFAUT,
    REGION,
    SYNTHESE_AUTORISEE,
    TAILLE_MAX_IMPORT_MO,
    cle_api_disponible,
)
from text2sql.journal import journaliser
from text2sql.llm import Consommation, Resultat
from text2sql.profils import Profil, lister_profils

SOURCE_IMPORT = "Mes fichiers (CSV ou SQLite)"
LIBELLES_FOURNISSEUR = {"anthropic": "API Claude", "bedrock": "AWS Bedrock", "vertex": "Google Vertex AI"}


# --- Profils et état de session ----------------------------------------------

@st.cache_resource(show_spinner=False)
def profils() -> dict[str, Profil]:
    return lister_profils()


def initialiser_session() -> None:
    """Valeurs par défaut de l'état de session."""
    disponibles = profils()
    if not disponibles:
        st.error("Aucun profil métier trouvé : ajoutez un fichier .toml dans le dossier profils/.")
        st.stop()
    st.session_state.setdefault("profil", PROFIL_DEFAUT if PROFIL_DEFAUT in disponibles else next(iter(disponibles)))
    st.session_state.setdefault("chemin_import", None)       # base créée à partir des fichiers importés
    st.session_state.setdefault("signature_import", None)
    st.session_state.setdefault("messages", [])               # pour l'affichage
    st.session_state.setdefault("historique", [])             # paires question/SQL pour le modèle
    st.session_state.setdefault("consommation", Consommation())
    st.session_state.setdefault("question_suggeree", None)


def reinitialiser_conversation() -> None:
    """Efface l'historique de conversation (garde la source de données)."""
    st.session_state.messages = []
    st.session_state.historique = []


def profil_courant() -> Profil:
    return profils()[st.session_state.profil]


def sur_import() -> bool:
    """Vrai quand l'utilisateur travaille sur ses propres fichiers."""
    return st.session_state.chemin_import is not None


def chemin_courant() -> Path:
    return st.session_state.chemin_import if sur_import() else profil_courant().base


def protegees_courantes() -> frozenset[str]:
    """Colonnes protégées : celles du profil (les fichiers importés n'en déclarent pas)."""
    return frozenset() if sur_import() else profil_courant().colonnes_protegees


def mode_api() -> bool:
    return cle_api_disponible()


def theme_actuel() -> str:
    """Thème Streamlit courant, pour choisir les couleurs des graphiques."""
    return "sombre" if getattr(st.context.theme, "type", None) == "dark" else "clair"


@st.cache_data(show_spinner=False)
def schema_en_cache(chemin: str, _version: float, protegees: frozenset[str], valeurs: bool) -> str:
    """Schéma de la base, recalculé seulement si le fichier ou la gouvernance change."""
    return base.lire_schema(Path(chemin), protegees, valeurs)


def schema_courant() -> str:
    chemin = chemin_courant()
    return schema_en_cache(str(chemin), chemin.stat().st_mtime, protegees_courantes(), ENVOYER_VALEURS_EXEMPLES)


# --- Authentification (SSO, optionnelle) -------------------------------------

def sso_configure() -> bool:
    """Vrai si un fournisseur OIDC est déclaré dans .streamlit/secrets.toml ([auth])."""
    try:
        return "auth" in st.secrets
    except Exception:  # pas de fichier de secrets : SSO désactivé
        return False


def utilisateur_connecte() -> str | None:
    """Exige la connexion SSO si elle est configurée ; renvoie l'identité de l'utilisateur."""
    if not sso_configure():
        return None
    if not st.user.is_logged_in:
        st.title("📊 Text-to-SQL")
        st.write("Connectez-vous avec votre compte d'entreprise pour continuer.")
        st.button("Se connecter", on_click=st.login, type="primary")
        st.stop()
    return st.user.get("email") or st.user.get("name")


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
    st.session_state.update(chemin_import=chemin, signature_import=signature)
    reinitialiser_conversation()


def _source_changee() -> None:
    """Callback du sélecteur de source : change de profil ou passe aux fichiers importés."""
    choix = st.session_state.source
    if choix != SOURCE_IMPORT:
        cle = next(k for k, p in profils().items() if p.nom == choix)
        st.session_state.update(profil=cle, chemin_import=None, signature_import=None)
    reinitialiser_conversation()


def choisir_source() -> None:
    """Sélection de la source : un profil métier (base de démo) ou les fichiers de l'utilisateur."""
    st.sidebar.subheader("Données")
    if sur_import() and not mode_api():   # l'import exige l'accès au modèle
        st.session_state.update(chemin_import=None, signature_import=None, source=profil_courant().nom)
    options = [p.nom for p in profils().values()] + ([SOURCE_IMPORT] if mode_api() else [])
    actuel = SOURCE_IMPORT if sur_import() else profil_courant().nom
    st.sidebar.selectbox("Source", options, index=options.index(actuel), key="source",
                         on_change=_source_changee, label_visibility="collapsed")
    if st.session_state.source == SOURCE_IMPORT:
        fichiers = st.sidebar.file_uploader("Une table par fichier CSV, ou une base SQLite",
                                            type=["csv", "txt", "db", "sqlite", "sqlite3"],
                                            accept_multiple_files=True)
        if fichiers:
            importer_donnees(fichiers)
    else:
        st.sidebar.caption(profil_courant().description)


def afficher_schema_et_glossaire() -> None:
    """Explorateurs du schéma transmis au modèle et du glossaire métier."""
    with st.sidebar.expander("Schéma détecté"):
        st.text(schema_courant())
    glossaire = profil_courant().glossaire
    if glossaire:
        with st.sidebar.expander("Glossaire métier"):
            for terme, definition in glossaire.items():
                st.markdown(f"**{terme}** : {definition}")


def afficher_confidentialite() -> None:
    """Ce qui quitte le périmètre vers le modèle, et ce qui reste dans la base."""
    if not mode_api():
        return
    envoye = ["la question", "le schéma (noms de tables et colonnes)"]
    if ENVOYER_VALEURS_EXEMPLES:
        envoye.append("quelques valeurs de référence (catégories, plages de dates)")
    if SYNTHESE_AUTORISEE and st.session_state.get("synthese_active", True):
        envoye.append("les 50 premières lignes du résultat, pour la synthèse")
    protegees = protegees_courantes()
    with st.sidebar.expander("🔐 Confidentialité"):
        st.markdown("**Envoyé au modèle** : " + ", ".join(envoye) + ".")
        st.markdown("**Jamais envoyé** : le contenu des tables"
                    + (f", les colonnes protégées ({len(protegees)})." if protegees else "."))
        st.caption(f"Modèle hébergé via {LIBELLES_FOURNISSEUR.get(FOURNISSEUR, FOURNISSEUR)}"
                   + (f", région {REGION}." if REGION else "."))


def afficher_consommation() -> None:
    """Tokens et coût estimé cumulés sur la session."""
    conso = st.session_state.consommation
    total = conso.entree + conso.cache_lu + conso.cache_ecrit + conso.sortie
    st.sidebar.subheader("Consommation de la session")
    col1, col2 = st.sidebar.columns(2)
    col1.metric("Tokens", f"{total:,}".replace(",", " "))
    col2.metric("Coût estimé", f"{conso.cout():.3f} $")


def afficher_barre_laterale(utilisateur: str | None) -> None:
    with st.sidebar:
        st.title("📊 Text-to-SQL")
        if mode_api():
            st.success(f"Connecté à Claude · {LIBELLES_FOURNISSEUR.get(FOURNISSEUR, FOURNISSEUR)}", icon="✅")
        else:
            st.info("**Mode démo** : questions pré-enregistrées, sans accès au modèle. "
                    "Configurez une clé API ou un fournisseur cloud pour poser vos propres questions.", icon="🎬")
    choisir_source()
    afficher_schema_et_glossaire()
    if mode_api():
        if SYNTHESE_AUTORISEE:
            st.sidebar.toggle("Synthèse en langage naturel", value=True, key="synthese_active")
        afficher_confidentialite()
        afficher_consommation()
    st.sidebar.button("Nouvelle conversation", on_click=reinitialiser_conversation, width="stretch")
    if utilisateur:
        st.sidebar.caption(f"Connecté : {utilisateur}")
        st.sidebar.button("Se déconnecter", on_click=st.logout)


# --- Affichage d'une réponse ----------------------------------------------

MOTS_MONETAIRES = ("montant", "chiffre", "ca", "prix", "panier", "cout", "revenu", "depense",
                   "encours", "production", "collecte", "solde", "depots", "epargne")
MOTS_POURCENTAGE = ("pct", "taux", "part", "ratio", "pourcentage")


def formater_nombre(valeur, colonne: str = "") -> str:
    """Nombre au format français (espace fine pour les milliers, virgule), avec € ou % selon la colonne."""
    if not isinstance(valeur, (int, float)):
        return str(valeur)
    texte = f"{valeur:,.2f}".replace(",", " ").replace(".", ",").removesuffix(",00")
    mots = colonne.lower().split("_")
    if any(m in MOTS_POURCENTAGE for m in mots):
        return f"{texte} %"
    return f"{texte} €" if any(m in MOTS_MONETAIRES for m in mots) else texte


def afficher_erreur(res: Resultat) -> None:
    """Message clair en cas de requête bloquée ou d'échec définitif."""
    if res.bloquee and "gouvernance" in (res.erreur or ""):
        st.warning(f"🔒 **Données protégées.** {res.erreur}\n\n"
                   "Ces informations personnelles ne sont pas accessibles depuis cet outil.")
    elif res.bloquee:
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
    st.dataframe(df, hide_index=True, width="stretch", column_config=formats)
    if choix:
        st.altair_chart(graphiques.construire_graphique(df, choix, theme_actuel()),
                        width="stretch", theme=None)
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
    """Génère et exécute le SQL avec Claude, puis rédige la synthèse si elle est autorisée."""
    client = llm.creer_client()
    systeme = llm.construire_prompt_systeme(schema_courant(), profil_courant(), base_du_profil=not sur_import())
    try:
        res = llm.generer_et_executer(client, systeme, st.session_state.historique,
                                      question, chemin_courant(), protegees_courantes())
        synthese = SYNTHESE_AUTORISEE and st.session_state.get("synthese_active", True)
        if res.succes and not res.df.empty and synthese:
            res.synthese = llm.resumer_resultat(client, question, res.df, res.consommation)
    except (anthropic.APIError, RuntimeError) as e:
        res = Resultat(question=question, erreur=f"Erreur d'accès au modèle : {e}")
    return res


def traiter_question(question: str, utilisateur: str | None) -> None:
    """Traite une question et met à jour l'affichage, l'historique et le journal."""
    st.session_state.messages.append({"role": "user", "contenu": question})
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        with st.spinner("Analyse de la question…"):
            res = repondre_api(question) if mode_api() else demo.repondre(question, profil_courant())
        afficher_reponse(res, len(st.session_state.messages))
    st.session_state.messages.append({"role": "assistant", "contenu": res})
    st.session_state.consommation.cumuler(res.consommation)
    journaliser(res, "api" if mode_api() else "demo", utilisateur=utilisateur,
                source="import" if sur_import() else st.session_state.profil)
    if res.succes:  # on ne mémorise que les échanges réussis
        st.session_state.historique += [{"role": "user", "content": question},
                                        {"role": "assistant", "content": res.sql}]


# --- Page principale ----------------------------------------------------------

def _suggestion_choisie() -> None:
    """Callback des suggestions : envoie la question puis désélectionne la pastille."""
    st.session_state.question_suggeree = st.session_state.suggestions
    st.session_state.suggestions = None


def afficher_suggestions() -> None:
    """Questions cliquables du profil : à l'accueil, et en permanence en mode démo."""
    if sur_import() or (mode_api() and st.session_state.messages):
        return
    options = [q for q, _ in profil_courant().questions_demo]
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
    utilisateur = utilisateur_connecte()
    initialiser_session()
    if not chemin_courant().exists():
        st.error(f"Base introuvable : {chemin_courant().name}. "
                 "Lancez d'abord `python seed_banque.py` et `python seed_db.py`.")
        st.stop()
    afficher_barre_laterale(utilisateur)
    if not st.session_state.messages:
        afficher_accueil()
    afficher_historique()
    afficher_suggestions()

    question = st.chat_input("Posez votre question (ex. : encours de crédit par agence)")
    question = question or st.session_state.question_suggeree
    st.session_state.question_suggeree = None
    if question:
        traiter_question(question, utilisateur)
        st.rerun()


if __name__ == "__main__":
    main()
