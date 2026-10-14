"""Profils métier : glossaire, exemples, questions de démo et gouvernance, lus depuis profils/*.toml."""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from text2sql.config import DOSSIER_PROFILS, RACINE


class ProfilInvalide(Exception):
    """Levée quand un fichier de profil est mal formé."""


@dataclass(frozen=True)
class Profil:
    """Configuration métier d'une base : tout ce qui adapte l'outil à un domaine."""
    cle: str
    nom: str
    description: str
    base: Path
    glossaire: dict[str, str] = field(default_factory=dict)
    exemples: tuple[tuple[str, str], ...] = ()
    questions_demo: tuple[tuple[str, str], ...] = ()
    colonnes_protegees: frozenset[str] = frozenset()


def _paires(entrees: list[dict], section: str, cle: str) -> tuple[tuple[str, str], ...]:
    """Convertit une liste [[section]] en paires (question, sql) validées."""
    try:
        return tuple((e["question"], e["sql"].strip()) for e in entrees)
    except (KeyError, TypeError, AttributeError) as e:
        raise ProfilInvalide(f"Profil {cle} : chaque [[{section}]] doit avoir question et sql.") from e


def lire_profil(chemin: Path) -> Profil:
    """Lit un fichier de profil TOML."""
    try:
        donnees = tomllib.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise ProfilInvalide(f"Profil {chemin.name} illisible : {e}") from e
    cle = chemin.stem
    base = Path(donnees.get("base", f"{cle}.db"))
    colonnes = donnees.get("gouvernance", {}).get("colonnes_protegees", [])
    return Profil(
        cle=cle,
        nom=donnees.get("nom", cle),
        description=donnees.get("description", ""),
        base=base if base.is_absolute() else RACINE / base,
        glossaire={str(k): str(v) for k, v in donnees.get("glossaire", {}).items()},
        exemples=_paires(donnees.get("exemples", []), "exemples", cle),
        questions_demo=_paires(donnees.get("demo", []), "demo", cle),
        colonnes_protegees=frozenset(c.lower() for c in colonnes),
    )


def lister_profils(dossier: Path = DOSSIER_PROFILS) -> dict[str, Profil]:
    """Tous les profils disponibles, indexés par nom de fichier (sans extension)."""
    return {p.stem: lire_profil(p) for p in sorted(dossier.glob("*.toml"))}
