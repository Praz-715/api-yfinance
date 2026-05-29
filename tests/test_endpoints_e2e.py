"""End-to-end coverage of every public endpoint.

Drives the full application stack (middleware, auth, rate limiting, services)
through the synthetic provider and asserts each route's contract: status code and
the uniform ``{meta, data}`` envelope shape. Each test uses its own client (and
therefore its own rate-limit bucket via a unique source IP).
"""

from __future__ import annotations

import pytest

from tests.conftest import ALLOWED_ORIGIN, VALID_API_KEY


def _assert_envelope(payload: dict, *, expect_symbol: bool = True) -> None:
    assert set(payload.keys()) == {"meta", "data"}
    meta = payload["meta"]
    assert meta["currency"] == "IDR"
    assert meta["timezone"] == "Asia/Jakarta"
    assert meta["source"]
    assert "generated_at" in meta
    if expect_symbol:
        assert meta["symbol"]


def test_health(client_factory):
    resp = client_factory(api_key=False).get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_root(client_factory):
    resp = client_factory(api_key=False).get("/")
    assert resp.status_code == 200
    assert resp.json()["status"] == "operational"


def test_quote_endpoint(client):
    resp = client.get("/api/v1/stock/BBCA", headers={"Origin": ALLOWED_ORIGIN})
    assert resp.status_code == 200
    body = resp.json()
    _assert_envelope(body)
    assert body["data"]["symbol"] == "BBCA.JK"
    assert body["data"]["price"] > 0


def test_history_endpoint(client):
    resp = client.get("/api/v1/history/BBCA", params={"page": 1, "page_size": 30})
    assert resp.status_code == 200
    body = resp.json()
    _assert_envelope(body)
    data = body["data"]
    assert data["interval"] == "1d"
    assert data["pagination"]["page"] == 1
    assert len(data["bars"]) <= 30
    if data["bars"]:
        bar = data["bars"][0]
        assert set(bar.keys()) == {"timestamp", "open", "high", "low", "close", "volume"}


def test_technical_endpoint(client):
    resp = client.get("/api/v1/technical/BBCA")
    assert resp.status_code == 200
    body = resp.json()
    _assert_envelope(body)
    data = body["data"]
    assert data["last_price"] > 0
    assert "moving_averages" in data
    assert "macd" in data
    assert "bollinger_bands" in data
    assert data["sample_size"] > 0


def test_signal_endpoint(client):
    resp = client.get("/api/v1/signal/BBCA")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["signal"] in {"strong_buy", "buy", "hold", "sell", "strong_sell"}
    assert 0.0 <= data["confidence"] <= 1.0
    assert data["risk_level"] in {"low", "medium", "high"}
    assert data["components"]


def test_market_summary_endpoint(client):
    resp = client.get("/api/v1/market/summary")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["universe_size"] > 0
    assert data["evaluated"] > 0
    assert isinstance(data["top_gainers"], list)
    assert isinstance(data["top_losers"], list)


@pytest.mark.parametrize("path", ["/api/v1/top-gainers", "/api/v1/top-losers", "/api/v1/unusual-volume"])
def test_movers_endpoints(client, path):
    resp = client.get(path, params={"limit": 5})
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["data"], list)
    assert len(body["data"]) <= 5
    for mover in body["data"]:
        assert mover["symbol"].endswith(".JK")
        assert mover["price"] > 0


def test_auth_token_and_refresh(client_factory):
    issuer = client_factory(api_key=False)
    token_resp = issuer.post(
        "/api/v1/auth/token",
        json={"scopes": ["read", "analysis"]},
        headers={"X-API-Key": VALID_API_KEY},
    )
    assert token_resp.status_code == 200
    tokens = token_resp.json()
    assert tokens["token_type"] == "bearer"
    assert set(tokens["scopes"]) == {"read", "analysis"}

    refresher = client_factory(api_key=False)
    refresh_resp = refresher.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert refresh_resp.status_code == 200
    assert refresh_resp.json()["access_token"]
