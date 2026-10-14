"""Journal d'audit : chaque question est tracée en JSON Lines (traçabilité, conformité)."""

import json
from datetime import datetime, timezone
from pathlib import Path

from text2sql.config import JOURNAL, MODELE
from text2sql.llm import Resultat


def entree_journal(res: Resultat, mode: str) -> dict:
    """Construit l'entrée de journal d'un résultat (sans les données renvoyées)."""
    return {
        "horodatage": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": mode,
        "modele": MODELE if mode == "api" else None,
        "question": res.question,
        "sql": res.sql,
        "succes": res.succes,
        "bloquee": res.bloquee,
        "erreur": res.erreur,
        "tentatives": res.tentatives,
        "lignes": None if res.df is None else len(res.df),
        "tokens_entree": res.consommation.entree + res.consommation.cache_lu + res.consommation.cache_ecrit,
        "tokens_sortie": res.consommation.sortie,
        "cout_usd": round(res.consommation.cout(), 6),
    }


def journaliser(res: Resultat, mode: str, chemin: str = JOURNAL) -> None:
    """Ajoute une ligne au journal ; ne fait jamais échouer l'application."""
    if not chemin:
        return
    try:
        fichier = Path(chemin)
        fichier.parent.mkdir(parents=True, exist_ok=True)
        with fichier.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entree_journal(res, mode), ensure_ascii=False) + "\n")
    except OSError:
        pass
