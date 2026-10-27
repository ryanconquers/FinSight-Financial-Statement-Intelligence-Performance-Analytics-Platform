"""SQLite connection setup for FinSight."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect_database(path: str | Path) -> sqlite3.Connection:
    """Open a SQLite database with foreign-key enforcement enabled."""
    connection = sqlite3.connect(str(path))
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    except Exception:
        connection.close()
        raise
    return connection
