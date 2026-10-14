"""Paramètres centralisés de l'application (surchargeables par variables d'environnement)."""

import os
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent


def _drapeau(nom: str, defaut: bool) -> bool:
    """Lit une variable d'environnement booléenne (1/0, oui/non, true/false)."""
    valeur = os.environ.get(nom)
    if valeur is None:
        return defaut
    return valeur.strip().lower() in ("1", "true", "oui", "yes", "on")


# Profils métier (glossaire, exemples, gouvernance) et profil affiché par défaut
DOSSIER_PROFILS = Path(os.environ.get("TEXT2SQL_PROFILS", RACINE / "profils"))
PROFIL_DEFAUT = os.environ.get("TEXT2SQL_PROFIL", "banque")

# Fournisseur du modèle : "anthropic" (API Claude), "bedrock" (AWS) ou "vertex" (Google Cloud)
FOURNISSEUR = os.environ.get("TEXT2SQL_FOURNISSEUR", "anthropic").lower()
REGION = os.environ.get("TEXT2SQL_REGION", "")              # ex. eu-west-3 (Bedrock), europe-west1 (Vertex)
PROJET_GCP = os.environ.get("TEXT2SQL_PROJET_GCP", "")      # Vertex uniquement
INFERENCE_GEO = os.environ.get("TEXT2SQL_INFERENCE_GEO", "")  # API Claude : zone d'inférence, si exigée

# Modèle Claude et paramètres d'appel
MODELE = os.environ.get("TEXT2SQL_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("TEXT2SQL_EFFORT", "low")
MAX_TOKENS = 16000

# Confidentialité : ce qui peut quitter le périmètre vers le modèle
ENVOYER_VALEURS_EXEMPLES = _drapeau("TEXT2SQL_VALEURS_EXEMPLES", True)  # valeurs distinctes dans le schéma
SYNTHESE_AUTORISEE = _drapeau("TEXT2SQL_SYNTHESE", True)               # résultats envoyés pour la synthèse

# Robustesse et sécurité
MAX_CORRECTIONS = 2          # essais de correction automatique après un échec
LIMITE_LIGNES = 500          # LIMIT ajouté si absent
TIMEOUT_REQUETE_S = 10       # durée maximale d'exécution d'une requête SQL
TAILLE_MAX_IMPORT_MO = 200   # taille maximale d'un fichier importé

# Journal d'audit des requêtes (JSON Lines) ; vide = désactivé
JOURNAL = os.environ.get("TEXT2SQL_JOURNAL", str(RACINE / "logs" / "requetes.jsonl"))

# Tarifs indicatifs en $ par million de tokens (entrée, sortie, lecture cache, écriture cache)
TARIFS = {
    "claude-opus-5-5": (4.00, 20.00, 0.20, 5.00),
}


def cle_api_disponible() -> bool:
    """Vrai si le modèle est joignable : clé API Claude, ou fournisseur cloud configuré."""
    if FOURNISSEUR in ("bedrock", "vertex"):
        return bool(REGION)
    return bool(os.environ.get("ANTHROPIC_API_KEY"))
