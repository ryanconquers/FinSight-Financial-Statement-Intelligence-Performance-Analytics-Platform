"""SQLite connection setup for FinSight."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
SCHEMA_VERSION = 1


def validate_database_path(path: str | Path) -> None:
    """Fail before serving requests when configured storage violates policy."""
    import os

    configured_path = str(path)
    if not configured_path.strip():
        raise ValueError("FINSIGHT_DATABASE_PATH must be a non-empty SQLite file path.")
    if os.getenv("FINSIGHT_REQUIRE_PERSISTENT_STORAGE", "").lower() not in {"1", "true", "yes"}:
        return
    if configured_path == ":memory:":
        raise ValueError("Persistent storage is required; configure FINSIGHT_DATABASE_PATH on a durable mounted volume.")
    expanded = Path(configured_path).expanduser()
    if not expanded.is_absolute():
        raise ValueError("Persistent storage requires an absolute FINSIGHT_DATABASE_PATH on a durable mounted volume.")
    resolved = expanded.resolve()
    ephemeral_roots = (Path("/tmp"), Path("/var/tmp"))
    is_ephemeral = any(expanded == root or root in expanded.parents or resolved == root.resolve() or root.resolve() in resolved.parents for root in ephemeral_roots)
    if is_ephemeral:
        raise ValueError("Persistent storage is required; configure FINSIGHT_DATABASE_PATH on a durable mounted volume.")


def connect_database(path: str | Path) -> sqlite3.Connection:
    """Open and initialize a versioned SQLite database safely.

    SQLite on a persistent mounted volume is supported for a single API service.
    Set ``FINSIGHT_REQUIRE_PERSISTENT_STORAGE=1`` in production to reject ephemeral
    paths instead of silently accepting a temporary database.
    """
    configured_path = str(path)
    validate_database_path(configured_path)
    if configured_path != ":memory:":
        Path(configured_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(configured_path, timeout=30)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA journal_mode = WAL")
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if version > SCHEMA_VERSION:
            raise RuntimeError(f"Database schema version {version} is newer than supported version {SCHEMA_VERSION}.")
        if version < 1:
            migration = (
                "BEGIN IMMEDIATE;\n"
                + SCHEMA_PATH.read_text(encoding="utf-8")
                + f"\nPRAGMA user_version = {SCHEMA_VERSION};\nCOMMIT;"
            )
            connection.executescript(migration)
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        connection.close()
        raise
    return connection


def backup_database(source: sqlite3.Connection, destination: str | Path) -> None:
    """Create a consistent SQLite backup using SQLite's online backup API."""
    target_path = Path(destination).expanduser()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if target_path.exists():
        raise FileExistsError(f"Backup destination already exists and will not be overwritten: {target_path}")
    target = sqlite3.connect(str(target_path))
    try:
        source.backup(target)
    finally:
        target.close()
