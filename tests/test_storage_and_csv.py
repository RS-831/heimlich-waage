import sqlite3
from datetime import date

import pytest

from app.core.models import Entry, Goal
from app.importers.csv_format import parse_csv, to_csv
from app.storage.db import MIGRATIONS, connect, schema_version
from app.storage.repository import SqliteRepository


@pytest.fixture
def repo(tmp_path):
    return SqliteRepository(connect(tmp_path / "sub" / "test.db"))


def test_migration_creates_schema_and_default_user(tmp_path):
    path = tmp_path / "x.db"
    conn = connect(path)
    assert schema_version(conn) == len(MIGRATIONS)
    conn.close()
    conn = connect(path)  # zweites Öffnen: keine erneute Migration, kein zweiter Nutzer
    assert conn.execute("SELECT COUNT(*) FROM user").fetchone()[0] == 1


def test_newer_schema_is_rejected(tmp_path):
    path = tmp_path / "x.db"
    connect(path).execute("UPDATE meta SET schema_version = 999")
    with pytest.raises(RuntimeError):
        connect(path)


def test_entry_upsert_and_delete(repo):
    uid = repo.default_user().id
    d = date(2026, 11, 1)
    repo.upsert_entry(uid, Entry(date=d, weight_kg=80, note="a"))
    repo.upsert_entry(uid, Entry(date=d, weight_kg=79.5, waist_cm=90, note="b"))
    [e] = repo.list_entries(uid)
    assert (e.weight_kg, e.waist_cm, e.note) == (79.5, 90, "b")
    assert repo.delete_entry(uid, d) is True
    assert repo.delete_entry(uid, d) is False


def test_import_overwrite_flag(repo):
    uid = repo.default_user().id
    repo.upsert_entry(uid, Entry(date=date(2026, 1, 1), weight_kg=80))
    new = [Entry(date=date(2026, 1, 1), weight_kg=81, source="csv"),
           Entry(date=date(2026, 1, 2), weight_kg=82, source="csv")]
    assert repo.import_entries(uid, new, overwrite=False) == {"created": 1, "updated": 0, "skipped": 1}
    assert repo.get_entry(uid, date(2026, 1, 1)).weight_kg == 80
    assert repo.import_entries(uid, new, overwrite=True) == {"created": 0, "updated": 2, "skipped": 0}
    assert repo.get_entry(uid, date(2026, 1, 1)).source == "csv"


def test_goal_replace_and_clear(repo):
    uid = repo.default_user().id
    repo.set_goal(uid, Goal(80, None, date(2026, 1, 1), 90))
    repo.set_goal(uid, Goal(75, date(2026, 6, 1), date(2026, 2, 1), 85))
    assert repo.get_goal(uid).target_weight_kg == 75
    repo.clear_goal(uid)
    assert repo.get_goal(uid) is None


def test_profile(repo):
    uid = repo.default_user().id
    u = repo.update_profile(uid, name="Testperson", height_cm=182)
    assert (u.name, u.height_cm) == ("Testperson", 182)


def test_csv_roundtrip():
    es = [Entry(date=date(2026, 1, 1), weight_kg=80.4, waist_cm=91.5, note="Urlaub; viel Essen"),
          Entry(date=date(2026, 1, 2), weight_kg=80)]
    parsed = parse_csv(to_csv(es))
    assert parsed.errors == []
    assert [(e.date, e.weight_kg, e.waist_cm, e.note) for e in parsed.entries] == \
           [(e.date, e.weight_kg, e.waist_cm, e.note) for e in es]
    assert all(e.source == "csv" for e in parsed.entries)


def test_csv_german_format_and_errors():
    text = ("﻿Datum;Gewicht;Bemerkung\n"
            "01.02.2026;85,3;\n"
            "02.02.2026;abc;\n"
            "03.02.2026;5;\n"
            "\n"
            "01.02.2026;85,1;spätere Messung gilt\n")
    r = parse_csv(text)
    assert [(e.date, e.weight_kg) for e in r.entries] == [(date(2026, 2, 1), 85.1)]
    assert [e.line for e in r.errors] == [3, 4]


def test_csv_comma_and_timestamps():
    r = parse_csv("date,weight\n2026-03-01 07:10,70.5\n")
    assert r.entries[0].date == date(2026, 3, 1)


def test_csv_missing_columns():
    r = parse_csv("foo;bar\n1;2\n")
    assert r.entries == [] and "Spalten fehlen" in r.errors[0].message
