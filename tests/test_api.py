"""API-Tests. Brauchen fastapi und httpx (pip install -r requirements-dev.txt)."""
from datetime import date, timedelta

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

TODAY = date.today()


@pytest.fixture
def client(tmp_path, monkeypatch):
    import app.main as main
    from app.core.config import Settings

    monkeypatch.setattr(main, "settings", Settings(data_dir=tmp_path, db_file="t.db"))
    with TestClient(main.app) as c:
        yield c


def put(client, day, weight, **extra):
    return client.put(f"/api/entries/{day.isoformat()}", json={"weight_kg": weight, **extra})


def test_health_and_frontend(client):
    assert client.get("/api/health").json()["schema_version"] == 2
    assert "heimlich" in client.get("/").text


def test_entry_crud(client):
    assert put(client, TODAY, 80.123, waist_cm=90, note=" hi ").json()["weight_kg"] == 80.12
    assert client.get(f"/api/entries/{TODAY}").json()["note"] == "hi"
    assert put(client, TODAY, 79).status_code == 200
    assert len(client.get("/api/entries").json()) == 1
    assert client.delete(f"/api/entries/{TODAY}").status_code == 204
    assert client.delete(f"/api/entries/{TODAY}").status_code == 404


def test_entry_validation(client):
    assert put(client, TODAY, 5).status_code == 422
    assert put(client, TODAY, 80, waist_cm=5).status_code == 422
    assert put(client, TODAY + timedelta(days=5), 80).status_code == 422


def test_summary_goal_profile(client):
    for i in range(30):
        put(client, TODAY - timedelta(days=29 - i), 90 - 0.1 * i)
    client.put("/api/profile", json={"name": "Testperson", "height_cm": 180})
    r = client.put("/api/goal", json={"target_weight_kg": 85,
                                      "target_date": (TODAY + timedelta(days=120)).isoformat()})
    assert r.status_code == 200
    s = client.get("/api/summary", params={"today": TODAY.isoformat()}).json()
    assert s["stats"]["count"] == 30 and s["stats"]["bmi"] is not None
    assert s["goal"]["projected_date"] is not None
    assert client.get("/api/summary", params={"method": "sma7"}).status_code == 200
    assert client.get("/api/summary", params={"method": "x"}).status_code == 422
    assert client.delete("/api/goal").status_code == 204
    assert client.get("/api/goal").json() is None


def test_goal_needs_entries(client):
    assert client.put("/api/goal", json={"target_weight_kg": 80}).status_code == 409


def test_csv_import_export(client):
    csv = "date;weight_kg;waist_cm;note\n2026-01-01;80,5;90;\n2026-01-02;80,1;;x\n2026-01-03;oops;;\n"
    r = client.post("/api/import", content=csv.encode(), headers={"Content-Type": "text/csv"})
    body = r.json()
    assert body["created"] == 2 and len(body["errors"]) == 1
    exported = client.get("/api/export.csv")
    assert "2026-01-01;80,5;90;" in exported.text
    assert client.post("/api/import", content=b"foo\n1").status_code == 422


# --- Proxy-Modus ------------------------------------------------------------------
@pytest.fixture
def proxy_client(tmp_path, monkeypatch):
    import app.main as main
    from app.core.config import Settings

    s = Settings(data_dir=tmp_path, db_file="p.db", auth_mode="proxy", auth_required_group="users",
                 auth_adopt_default_user="", auth_logout_url="https://auth.example.org/logout",
                 auth_trusted_proxies=())
    monkeypatch.setattr(main, "settings", s)
    with TestClient(main.app) as c:
        yield c


def as_user(name, groups="users"):
    return {"Remote-User": name, "Remote-Groups": groups, "Remote-Name": name.title()}


def test_proxy_requires_login(proxy_client):
    assert proxy_client.get("/api/entries").status_code == 401
    assert proxy_client.get("/api/me", headers={"Remote-User": "anna", "Remote-Groups": "gaeste"}).status_code == 403
    h = proxy_client.get("/api/health").json()
    assert h["auth_mode"] == "proxy" and "data_dir" not in h


def test_proxy_me_and_separation(proxy_client):
    anna, bert = as_user("anna", "users,admins"), as_user("bert")
    me = proxy_client.get("/api/me", headers=anna).json()
    assert me == {"username": "anna", "name": "Anna", "role": "admin", "auth_mode": "proxy",
                  "logout_url": "https://auth.example.org/logout"}
    assert proxy_client.put(f"/api/entries/{TODAY}", json={"weight_kg": 70}, headers=anna).status_code == 200
    assert proxy_client.get("/api/entries", headers=bert).json() == []
    assert proxy_client.get("/api/summary", headers=bert).json()["stats"] is None
    assert str(TODAY) not in proxy_client.get("/api/export.csv", headers=bert).text
    assert proxy_client.delete(f"/api/entries/{TODAY}", headers=bert).status_code == 404
    assert len(proxy_client.get("/api/entries", headers=anna).json()) == 1


def test_proxy_profile_name_conflict(proxy_client):
    proxy_client.get("/api/me", headers=as_user("anna"))
    r = proxy_client.put("/api/profile", json={"name": "Anna", "height_cm": None}, headers=as_user("bert"))
    assert r.status_code == 409


def test_none_mode_me(client):
    me = client.get("/api/me").json()
    assert me["auth_mode"] == "none" and me["logout_url"] is None
