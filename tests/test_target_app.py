"""Demo target API: auth, CRUD, and fault injection."""

import time

import pytest
from fastapi.testclient import TestClient

from target_app.app import app, reset_state, resolve_bind


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("TARGET_ERROR_RATE", "0")
    monkeypatch.setenv("TARGET_LATENCY_MS", "0")
    monkeypatch.setenv("TARGET_LATENCY_JITTER_MS", "0")
    reset_state()
    with TestClient(app) as test_client:
        yield test_client
    reset_state()


def _auth(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "demo", "password": "demo-pass"},
    )
    assert response.status_code == 200
    token = response.json()["access_token"]
    assert response.json()["token_type"] == "bearer"
    return {"Authorization": f"Bearer {token}"}


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_login_and_bearer_reuse(client):
    headers = _auth(client)
    me = client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json() == {"username": "demo"}
    rejected = client.post(
        "/api/v1/auth/login",
        json={"username": "demo", "password": "wrong"},
    )
    assert rejected.status_code == 401


def test_crud_requires_a_bearer_token(client):
    assert client.get("/api/v1/items").status_code == 401
    headers = _auth(client)
    created = client.post(
        "/api/v1/items",
        headers=headers,
        json={"name": "Pad", "sku": "SKU-PAD", "quantity": 3, "notes": "sterile"},
    )
    assert created.status_code == 201
    item_id = created.json()["id"]
    fetched = client.get(f"/api/v1/items/{item_id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "Pad"
    replaced = client.put(
        f"/api/v1/items/{item_id}",
        headers=headers,
        json={"name": "Pad-2", "sku": "SKU-PAD", "quantity": 5},
    )
    assert replaced.status_code == 200
    assert replaced.json()["quantity"] == 5
    patched = client.patch(
        f"/api/v1/items/{item_id}",
        headers=headers,
        json={"quantity": 1},
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "Pad-2"
    assert patched.json()["quantity"] == 1
    listed = client.get("/api/v1/items", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["count"] >= 1
    assert any(item["id"] == item_id for item in listed.json()["items"])
    deleted = client.delete(f"/api/v1/items/{item_id}", headers=headers)
    assert deleted.status_code == 204
    assert client.get(f"/api/v1/items/{item_id}", headers=headers).status_code == 404
    assert client.delete(f"/api/v1/items/{item_id}", headers=headers).status_code == 404


def test_validation_error(client):
    headers = _auth(client)
    response = client.post(
        "/api/v1/items",
        headers=headers,
        json={"name": "", "sku": "SKU", "quantity": -1},
    )
    assert response.status_code == 422


def test_status_and_latency_injection(client):
    headers = _auth(client)
    injected = client.get(
        "/api/v1/items",
        headers={**headers, "x-inject-status": "503"},
    )
    assert injected.status_code == 503
    health = client.get(
        "/health",
        headers={"x-inject-status": "500", "x-inject-latency-ms": "2000"},
    )
    assert health.status_code == 200
    started = time.perf_counter()
    delayed = client.get(
        "/api/v1/items",
        headers={**headers, "x-inject-latency-ms": "250"},
    )
    elapsed = time.perf_counter() - started
    assert delayed.status_code == 200
    assert elapsed >= 0.2


def test_random_error_rate_skips_health_and_login(monkeypatch):
    monkeypatch.setenv("TARGET_ERROR_RATE", "1")
    monkeypatch.setenv("TARGET_LATENCY_MS", "0")
    monkeypatch.setenv("TARGET_LATENCY_JITTER_MS", "0")
    reset_state()
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "demo", "password": "demo-pass"},
        )
        assert login.status_code == 200
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        listed = client.get("/api/v1/items", headers=headers)
        assert listed.status_code == 500
        assert listed.json()["detail"] == "injected error"


def test_resolve_bind_stays_local():
    assert resolve_bind("127.0.0.1") == "127.0.0.1"
    with pytest.raises(ValueError, match="localhost"):
        resolve_bind("0.0.0.0")
    assert resolve_bind("0.0.0.0", allow_remote="yes") == "0.0.0.0"
