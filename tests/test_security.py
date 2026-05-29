"""Security control tests: auth gating, headers, bot protection, payload limits."""

from __future__ import annotations


def test_missing_api_key_rejected(client_factory):
    client = client_factory(api_key=False)
    resp = client.get("/api/v1/stock/BBCA")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "authentication_failed"


def test_invalid_api_key_rejected(client_factory):
    client = client_factory(api_key=False)
    resp = client.get("/api/v1/stock/BBCA", headers={"X-API-Key": "wrong-key"})
    assert resp.status_code == 401


def test_security_headers_present(client):
    resp = client.get("/api/v1/stock/BBCA")
    assert resp.status_code == 200
    headers = resp.headers
    assert "content-security-policy" in headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert headers["referrer-policy"] == "no-referrer"
    assert "strict-transport-security" in headers
    assert "permissions-policy" in headers
    assert "x-request-id" in headers


def test_blocked_user_agent_rejected(client_factory):
    client = client_factory(api_key=True)
    resp = client.get("/api/v1/stock/BBCA", headers={"User-Agent": "sqlmap/1.7"})
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "forbidden"


def test_suspicious_query_rejected(client):
    resp = client.get("/api/v1/stock/BBCA", params={"q": "union select * from users"})
    assert resp.status_code == 403


def test_payload_too_large_rejected(client):
    oversized = "x" * 20_000
    resp = client.post("/api/v1/auth/token", content=oversized)
    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == "payload_too_large"


def test_health_is_open(client_factory):
    client = client_factory(api_key=False)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_error_response_has_request_id(client_factory):
    client = client_factory(api_key=False)
    resp = client.get("/api/v1/stock/BBCA")
    assert "request_id" in resp.json()["error"]
    assert resp.headers.get("x-request-id")
