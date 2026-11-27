"""SQLite-Verbindung und Migrationen.

Jede Migration ist ein SQL-Block mit fortlaufender Nummer. Beim Start werden alle noch nicht
angewendeten Migrationen in einer Transaktion ausgeführt; die erreichte Nummer steht in
``meta.schema_version``. Bestehende Migrationen nie ändern, nur neue anhängen.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

MIGRATIONS: list[str] = [
    # 1: Grundschema
    """
    CREATE TABLE user (
        id            INTEGER PRIMARY KEY,
        name          TEXT NOT NULL UNIQUE,
        password_hash TEXT,
        role          TEXT NOT NULL DEFAULT 'user',
        height_cm     REAL,
        unit          TEXT NOT NULL DEFAULT 'kg',
        created_at    TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE TABLE entry (
        id           INTEGER PRIMARY KEY,
        user_id      INTEGER NOT NULL REFERENCES user(id) ON DELETE CASCADE,
        date         TEXT NOT NULL,
        weight_kg    REAL NOT NULL,
        body_fat_pct REAL,
        waist_cm     REAL,
        note         TEXT NOT NULL DEFAULT '',
        source       TEXT NOT NULL DEFAULT 'manual',
        created_at   TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at   TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE (user_id, date)
    );
    CREATE TABLE goal (
        id               INTEGER PRIMARY KEY,
        user_id          INTEGER NOT NULL REFERENCES user(id) ON DELETE CASCADE,
        target_weight_kg REAL NOT NULL,
        target_date      TEXT,
        start_date       TEXT NOT NULL,
        start_weight_kg  REAL NOT NULL,
        active           INTEGER NOT NULL DEFAULT 1,
        created_at       TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX idx_goal_user_active ON goal(user_id, active);
    """,
    # 2: Anmeldung über einen vorgeschalteten Proxy (AUTH_MODE=proxy)
    """
    ALTER TABLE user ADD COLUMN username TEXT;
    CREATE UNIQUE INDEX idx_user_username ON user(username);
    ALTER TABLE user ADD COLUMN last_seen_at TEXT;
    """,
]

DEFAULT_USER = "standard"


def connect(path: Path | str) -> sqlite3.Connection:
    """Öffnet die Datenbank (legt sie bei Bedarf an) und bringt das Schema auf Stand."""
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    if str(path) != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    migrate(conn)
    return conn


def schema_version(conn: sqlite3.Connection) -> int:
    conn.execute("CREATE TABLE IF NOT EXISTS meta (schema_version INTEGER NOT NULL)")
    row = conn.execute("SELECT schema_version FROM meta").fetchone()
    return row[0] if row else 0


def migrate(conn: sqlite3.Connection) -> int:
    current = schema_version(conn)
    for number, sql in enumerate(MIGRATIONS, start=1):
        if number <= current:
            continue
        conn.execute("BEGIN")
        try:
            for statement in filter(str.strip, sql.split(";")):
                conn.execute(statement)
            conn.execute("DELETE FROM meta")
            conn.execute("INSERT INTO meta (schema_version) VALUES (?)", (number,))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        current = number
    if current > len(MIGRATIONS):
        raise RuntimeError(
            f"Datenbank hat Schema-Version {current}, diese Programmversion kennt nur "
            f"{len(MIGRATIONS)}. Bitte die neuere Programmversion verwenden."
        )
    ensure_default_user(conn)
    return current


def ensure_default_user(conn: sqlite3.Connection) -> None:
    """Phase 1: genau ein Standardnutzer, der später das erste Admin-Konto wird."""
    if conn.execute("SELECT 1 FROM user LIMIT 1").fetchone() is None:
        conn.execute(
            "INSERT INTO user (name, role) VALUES (?, 'admin')", (DEFAULT_USER,)
        )
