"""Fixtures partagées : petite base vide et base de démo générée une fois par session."""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import seed_db  # noqa: E402


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
    """Base de démonstration complète (générée par seed_db)."""
    chemin = tmp_path_factory.mktemp("retail") / "retail.db"
    seed_db.main(chemin)
    return chemin
