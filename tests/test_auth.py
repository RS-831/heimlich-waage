"""Nutzer-Ermittlung im Proxy-Modus (ohne Web-Framework testbar)."""
import ipaddress
import sqlite3
from datetime import date

import pytest

from app.core.auth import AuthError, resolve_user
from app.core.config import Settings
from app.core.models import Entry
from app.storage.db import MIGRATIONS, connect, schema_version
from app.storage.repository import NameTakenError, SqliteRepository


@pytest.fixture
def repo(tmp_path):
    return SqliteRepository(connect(tmp_path / "t.db"))


def proxy(**kw) -> Settings:
    base = dict(auth_mode="proxy", auth_admin_group="admins", auth_required_group="",
                auth_adopt_default_user="", auth_trusted_proxies=())
    base.update(kw)
    return Settings(**base)


def login(repo, s, user=None, groups="users", name=None, host="127.0.0.1"):
    h = {}
    if user is not None:
        h["Remote-User"] = user
    if groups is not None:
        h["Remote-Groups"] = groups
    if name is not None:
        h["Remote-Name"] = name
    return resolve_user(repo, s, h, host)


def test_none_mode_ignores_headers(repo):
    s = Settings(auth_mode="none")
    assert resolve_user(repo, s, {"Remote-User": "x"}, "1.2.3.4").id == repo.default_user().id


def test_invalid_mode_aborts():
    with pytest.raises(SystemExit):
        Settings(auth_mode="local")


def test_missing_user_is_401(repo):
    with pytest.raises(AuthError) as e:
        login(repo, proxy())
    assert e.value.status == 401


def test_new_user_created_and_case_insensitive(repo):
    u = login(repo, proxy(), "Anna", name="Anna A.")
    assert (u.username, u.name, u.role) == ("anna", "Anna A.", "user")
    assert login(repo, proxy(), "anna", name="Anders").id == u.id
    # Anzeigename wird später nicht aus dem Header überschrieben
    assert repo.get_user(u.id).name == "Anna A."
    # Header-Namen sind case-insensitiv
    assert resolve_user(repo, proxy(), {"remote-user": "anna"}, None).id == u.id


def test_role_follows_groups(repo):
    assert login(repo, proxy(), "anna", groups="users, admins").role == "admin"
    assert login(repo, proxy(), "anna", groups="users").role == "user"


def test_required_group(repo):
    s = proxy(auth_required_group="users")
    with pytest.raises(AuthError) as e:
        login(repo, s, "anna", groups="gaeste")
    assert e.value.status == 403
    assert login(repo, s, "anna", groups="gaeste,users").username == "anna"


def test_trusted_proxies(repo):
    s = proxy(auth_trusted_proxies=(ipaddress.ip_network("10.0.0.1/32"),))
    with pytest.raises(AuthError) as e:
        login(repo, s, "anna", host="10.0.0.2")
    assert e.value.status == 401
    with pytest.raises(AuthError):
        login(repo, s, "anna", host=None)
    assert login(repo, s, "anna", host="10.0.0.1").username == "anna"


def test_separation(repo):
    s = proxy()
    anna, bert = login(repo, s, "anna"), login(repo, s, "bert")
    repo.upsert_entry(anna.id, Entry(date=date(2026, 11, 1), weight_kg=70))
    assert repo.list_entries(bert.id) == []
    assert repo.delete_entry(bert.id, date(2026, 11, 1)) is False
    assert len(repo.list_entries(anna.id)) == 1


def test_adopt_default_user_once(repo):
    std = repo.default_user()
    repo.upsert_entry(std.id, Entry(date=date(2026, 11, 1), weight_kg=117))
    s = proxy(auth_adopt_default_user="chris")
    other = login(repo, s, "anna")                       # anderer Nutzer zuerst: bekommt nichts
    assert repo.list_entries(other.id) == []
    me = login(repo, s, "chris", name="Chris")
    assert me.id == std.id and me.username == "chris"
    assert len(repo.list_entries(me.id)) == 1
    assert login(repo, s, "chris").id == std.id          # stabil bei weiteren Logins
    assert repo.adopt_default_user("mallory") is None      # keine zweite Übernahme


def test_no_adopt_without_setting(repo):
    std = repo.default_user()
    me = login(repo, proxy(), "chris")
    assert me.id != std.id


def test_name_collision_gets_number(repo):
    s = proxy()
    a = login(repo, s, "anna1", name="Anna")
    b = login(repo, s, "anna2", name="Anna")
    c = login(repo, s, "anna3", name="Anna")
    assert (a.name, b.name, c.name) == ("Anna", "Anna 2", "Anna 3")


def test_concurrent_first_login_returns_same_user(repo):
    first = repo.create_user("anna", "Anna", "user")
    assert repo.create_user("anna", "Anna", "user").id == first.id


def test_profile_name_taken(repo):
    s = proxy()
    login(repo, s, "anna", name="Anna")
    bert = login(repo, s, "bert", name="Bert")
    with pytest.raises(NameTakenError):
        repo.update_profile(bert.id, name="Anna", height_cm=None)


def test_migration_from_version_1_keeps_data(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute("CREATE TABLE meta (schema_version INTEGER NOT NULL)")
    for stmt in filter(str.strip, MIGRATIONS[0].split(";")):
        conn.execute(stmt)
    conn.execute("INSERT INTO meta VALUES (1)")
    conn.execute("INSERT INTO user (name, role) VALUES ('standard', 'admin')")
    conn.execute("INSERT INTO entry (user_id, date, weight_kg) VALUES (1, '2026-11-01', 117.0)")
    conn.close()

    new = connect(path)
    assert schema_version(new) == len(MIGRATIONS) == 2
    repo = SqliteRepository(new)
    assert repo.default_user().username is None
    assert [e.weight_kg for e in repo.list_entries(1)] == [117.0]
    assert new.execute("SELECT COUNT(*) FROM user").fetchone()[0] == 1
