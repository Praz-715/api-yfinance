"""JWT authentication flow tests: issuance, refresh, and scope enforcement."""

from __future__ import annotations

from tests.conftest import VALID_API_KEY


def _issue(client, scopes):
    return client.post(
        "/api/v1/auth/token",
        json={"scopes": scopes},
        headers={"X-API-Key": VALID_API_KEY},
    )


def test_issue_token_requires_api_key(client_factory):
    client = client_factory(api_key=False)
    resp = client.post("/api/v1/auth/token", json={"scopes": ["read"]})
    assert resp.status_code == 401


def test_issue_and_use_access_token(client_factory):
    issuer = client_factory(api_key=False)
    token_resp = _issue(issuer, ["read", "analysis"])
    assert token_resp.status_code == 200
    tokens = token_resp.json()
    assert tokens["token_type"] == "bearer"
    assert tokens["expires_in"] > 0

    caller = client_factory(api_key=False)
    resp = caller.get(
        "/api/v1/stock/BBCA",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert resp.status_code == 200


def test_refresh_token_flow(client_factory):
    issuer = client_factory(api_key=False)
    tokens = _issue(issuer, ["read"]).json()

    refresher = client_factory(api_key=False)
    resp = refresher.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert resp.status_code == 200
    assert "access_token" in resp.json()


def test_invalid_refresh_token_rejected(client_factory):
    client = client_factory(api_key=False)
    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": "not-a-real-token-string"})
    assert resp.status_code == 401


def test_access_token_used_as_refresh_is_rejected(client_factory):
    issuer = client_factory(api_key=False)
    tokens = _issue(issuer, ["read"]).json()
    client = client_factory(api_key=False)
    # Presenting an *access* token to the refresh endpoint must fail (type check).
    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["access_token"]})
    assert resp.status_code == 401


def test_scope_enforced_on_heavy_endpoint(client_factory):
    issuer = client_factory(api_key=False)
    # Mint a token WITHOUT the analysis scope.
    tokens = _issue(issuer, ["read"]).json()

    caller = client_factory(api_key=False)
    resp = caller.get(
        "/api/v1/technical/BBCA",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "forbidden"
