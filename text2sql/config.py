"""Paramètres centralisés de l'application (surchargeables par variables d'environnement)."""

import os
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent

# Base de démonstration générée par seed_db.py
DB_DEMO = Path(os.environ.get("TEXT2SQL_DB", RACINE / "retail.db"))

# Modèle Claude et paramètres d'appel
MODELE = os.environ.get("TEXT2SQL_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("TEXT2SQL_EFFORT", "low")
MAX_TOKENS = 16000

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
    """Vrai si une clé API Anthropic est configurée (sinon : mode démo)."""
    return bool(os.environ.get("ANTHROPIC_API_KEY"))
