"""Fixtures partagées : petite base vide, bases de démo et profils pointant vers elles."""

import dataclasses
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import seed_banque  # noqa: E402
import seed_db  # noqa: E402
from text2sql.config import DOSSIER_PROFILS  # noqa: E402
from text2sql.profils import Profil, lire_profil  # noqa: E402


@pytest.fixture
def base_vide(tmp_path) -> Path:
    """Base minimale : une table t avec deux lignes."""
    chemin = tmp_path / "vide.db"
    with sqlite3.connect(chemin) as conn:
        conn.execute("CREATE TABLE t (id INTEGER)")
        conn.executemany("INSERT INTO t VALUES (?)", [(1,), (2,)])
    return chemin


@pytest.fixture(scope="session")
def base_retail(tmp_path_factory) -> Path:
    """Base de démonstration retail (générée par seed_db)."""
    chemin = tmp_path_factory.mktemp("retail") / "retail.db"
    seed_db.main(chemin)
    return chemin


@pytest.fixture(scope="session")
def base_banque(tmp_path_factory) -> Path:
    """Base de démonstration bancaire (générée par seed_banque)."""
    chemin = tmp_path_factory.mktemp("banque") / "banque.db"
    seed_banque.main(chemin)
    return chemin


@pytest.fixture(scope="session")
def profil_retail(base_retail) -> Profil:
    return dataclasses.replace(lire_profil(DOSSIER_PROFILS / "retail.toml"), base=base_retail)


@pytest.fixture(scope="session")
def profil_banque(base_banque) -> Profil:
    return dataclasses.replace(lire_profil(DOSSIER_PROFILS / "banque.toml"), base=base_banque)
