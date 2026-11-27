"""Speicherzugriff. API und Auswertung kennen nur das ``Repository``-Interface."""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from datetime import date
from typing import Iterable, Protocol

from app.core.models import Entry, Goal, User


class Repository(Protocol):
    def get_user(self, user_id: int) -> User | None: ...
    def default_user(self) -> User: ...
    def update_profile(self, user_id: int, *, name: str, height_cm: float | None) -> User: ...
    def get_user_by_username(self, username: str) -> User | None: ...
    def create_user(self, username: str, name: str, role: str) -> User: ...
    def adopt_default_user(self, username: str) -> User | None: ...
    def touch_user(self, user_id: int, role: str) -> User: ...

    def list_entries(self, user_id: int) -> list[Entry]: ...
    def get_entry(self, user_id: int, day: date) -> Entry | None: ...
    def upsert_entry(self, user_id: int, entry: Entry) -> Entry: ...
    def delete_entry(self, user_id: int, day: date) -> bool: ...
    def import_entries(self, user_id: int, entries: Iterable[Entry], overwrite: bool) -> dict: ...

    def get_goal(self, user_id: int) -> Goal | None: ...
    def set_goal(self, user_id: int, goal: Goal) -> Goal: ...
    def clear_goal(self, user_id: int) -> None: ...


def _entry(row: sqlite3.Row) -> Entry:
    return Entry(
        date=date.fromisoformat(row["date"]),
        weight_kg=row["weight_kg"],
        waist_cm=row["waist_cm"],
        body_fat_pct=row["body_fat_pct"],
        note=row["note"],
        source=row["source"],
    )


def _user(row: sqlite3.Row) -> User:
    return User(
        id=row["id"], name=row["name"], role=row["role"],
        height_cm=row["height_cm"], unit=row["unit"], username=row["username"],
    )


class NameTakenError(Exception):
    """Anzeigename ist schon an einen anderen Nutzer vergeben."""


class SqliteRepository:
    """Repository auf einer SQLite-Verbindung. Schreibzugriffe sind serialisiert."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self._lock = threading.RLock()

    def _all(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self.conn.execute(sql, params).fetchall()

    def _one(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        with self._lock:
            return self.conn.execute(sql, params).fetchone()

    # --- Nutzer ---------------------------------------------------------------
    def get_user(self, user_id: int) -> User | None:
        row = self._one("SELECT * FROM user WHERE id = ?", (user_id,))
        return _user(row) if row else None

    def default_user(self) -> User:
        row = self._one("SELECT * FROM user ORDER BY id LIMIT 1")
        return _user(row)

    def update_profile(self, user_id: int, *, name: str, height_cm: float | None) -> User:
        try:
            with self._lock:
                self.conn.execute(
                    "UPDATE user SET name = ?, height_cm = ? WHERE id = ?",
                    (name, height_cm, user_id),
                )
        except sqlite3.IntegrityError:
            raise NameTakenError(name) from None
        return self.get_user(user_id)  # type: ignore[return-value]

    def get_user_by_username(self, username: str) -> User | None:
        row = self._one("SELECT * FROM user WHERE username = ?", (username,))
        return _user(row) if row else None

    def create_user(self, username: str, name: str, role: str) -> User:
        """Legt einen Nutzer an. Ist der Anzeigename vergeben, wird eine Ziffer angehängt.
        Legt ein paralleler Aufruf denselben Login gleichzeitig an, wird dieser zurückgegeben."""
        base = (name or username).strip()[:60] or username
        with self._lock:
            for n in range(1, 1000):
                candidate = base if n == 1 else f"{base[:56]} {n}"
                try:
                    self.conn.execute(
                        "INSERT INTO user (name, username, role) VALUES (?, ?, ?)",
                        (candidate, username, role),
                    )
                    break
                except sqlite3.IntegrityError:
                    existing = self.get_user_by_username(username)
                    if existing:  # gleichzeitiger Erst-Login
                        return existing
                    # sonst war nur der Anzeigename vergeben → nächste Ziffer
            else:
                raise RuntimeError("Kein freier Anzeigename gefunden")
        return self.get_user_by_username(username)  # type: ignore[return-value]

    def adopt_default_user(self, username: str) -> User | None:
        """Ordnet den ersten Nutzer (Standardnutzer aus dem lokalen Betrieb) samt Daten diesem
        Login zu – nur, solange er noch keinem Login gehört. Sonst None."""
        try:
            with self._lock:
                cur = self.conn.execute(
                    "UPDATE user SET username = ? WHERE username IS NULL "
                    "AND id = (SELECT MIN(id) FROM user)",
                    (username,),
                )
        except sqlite3.IntegrityError:  # Login existiert inzwischen schon
            return self.get_user_by_username(username)
        return self.get_user_by_username(username) if cur.rowcount else None

    def touch_user(self, user_id: int, role: str) -> User:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            self.conn.execute(
                "UPDATE user SET role = ?, last_seen_at = ? WHERE id = ?", (role, now, user_id)
            )
        return self.get_user(user_id)  # type: ignore[return-value]

    # --- Einträge -------------------------------------------------------------
    def list_entries(self, user_id: int) -> list[Entry]:
        rows = self._all("SELECT * FROM entry WHERE user_id = ? ORDER BY date", (user_id,))
        return [_entry(r) for r in rows]

    def get_entry(self, user_id: int, day: date) -> Entry | None:
        row = self._one(
            "SELECT * FROM entry WHERE user_id = ? AND date = ?", (user_id, day.isoformat())
        )
        return _entry(row) if row else None

    _UPSERT = """
        INSERT INTO entry (user_id, date, weight_kg, waist_cm, body_fat_pct, note, source)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (user_id, date) DO UPDATE SET
            weight_kg = excluded.weight_kg,
            waist_cm = excluded.waist_cm,
            body_fat_pct = excluded.body_fat_pct,
            note = excluded.note,
            source = excluded.source,
            updated_at = datetime('now')
    """

    def _params(self, user_id: int, e: Entry) -> tuple:
        return (user_id, e.date.isoformat(), e.weight_kg, e.waist_cm, e.body_fat_pct,
                e.note, e.source)

    def upsert_entry(self, user_id: int, entry: Entry) -> Entry:
        with self._lock:
            self.conn.execute(self._UPSERT, self._params(user_id, entry))
        return self.get_entry(user_id, entry.date)  # type: ignore[return-value]

    def delete_entry(self, user_id: int, day: date) -> bool:
        with self._lock:
            cur = self.conn.execute(
                "DELETE FROM entry WHERE user_id = ? AND date = ?", (user_id, day.isoformat())
            )
        return cur.rowcount > 0

    def import_entries(self, user_id: int, entries: Iterable[Entry], overwrite: bool) -> dict:
        """Importiert in einer Transaktion. Ohne ``overwrite`` bleiben vorhandene Tage unverändert."""
        created = updated = skipped = 0
        with self._lock:
            self.conn.execute("BEGIN")
            try:
                for e in entries:
                    exists = self.conn.execute(
                        "SELECT 1 FROM entry WHERE user_id = ? AND date = ?",
                        (user_id, e.date.isoformat()),
                    ).fetchone()
                    if exists and not overwrite:
                        skipped += 1
                        continue
                    self.conn.execute(self._UPSERT, self._params(user_id, e))
                    if exists:
                        updated += 1
                    else:
                        created += 1
                self.conn.execute("COMMIT")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise
        return {"created": created, "updated": updated, "skipped": skipped}

    # --- Ziel -----------------------------------------------------------------
    def get_goal(self, user_id: int) -> Goal | None:
        row = self._one(
            "SELECT * FROM goal WHERE user_id = ? AND active = 1 ORDER BY id DESC LIMIT 1",
            (user_id,),
        )
        if not row:
            return None
        return Goal(
            target_weight_kg=row["target_weight_kg"],
            target_date=date.fromisoformat(row["target_date"]) if row["target_date"] else None,
            start_date=date.fromisoformat(row["start_date"]),
            start_weight_kg=row["start_weight_kg"],
        )

    def set_goal(self, user_id: int, goal: Goal) -> Goal:
        with self._lock:
            self.conn.execute("BEGIN")
            try:
                self.conn.execute("UPDATE goal SET active = 0 WHERE user_id = ?", (user_id,))
                self.conn.execute(
                    "INSERT INTO goal (user_id, target_weight_kg, target_date, start_date, "
                    "start_weight_kg) VALUES (?, ?, ?, ?, ?)",
                    (user_id, goal.target_weight_kg,
                     goal.target_date.isoformat() if goal.target_date else None,
                     goal.start_date.isoformat(), goal.start_weight_kg),
                )
                self.conn.execute("COMMIT")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise
        return goal

    def clear_goal(self, user_id: int) -> None:
        with self._lock:
            self.conn.execute("UPDATE goal SET active = 0 WHERE user_id = ?", (user_id,))
