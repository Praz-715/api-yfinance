"""Input-validation tests: ticker, date range, and pagination parameters."""

from __future__ import annotations

import pytest


def test_valid_symbol_returns_quote(client):
    resp = client.get("/api/v1/stock/BBCA")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["symbol"] == "BBCA.JK"
    assert body["meta"]["currency"] == "IDR"
    assert body["meta"]["timezone"] == "Asia/Jakarta"


def test_lowercase_symbol_is_normalised(client):
    resp = client.get("/api/v1/stock/bbca")
    assert resp.status_code == 200
    assert resp.json()["data"]["symbol"] == "BBCA.JK"


@pytest.mark.parametrize("bad", ["TOOLONGSYMBOL", "AB$C", "12345678901234"])
def test_invalid_symbol_rejected(client, bad):
    resp = client.get(f"/api/v1/stock/{bad}")
    assert resp.status_code in (404, 422)
    if resp.status_code == 422:
        assert resp.json()["error"]["code"] in ("invalid_ticker", "validation_error")


def test_history_start_after_end_rejected(client):
    resp = client.get("/api/v1/history/BBCA", params={"start": "2024-12-31", "end": "2024-01-01"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


def test_history_pagination(client):
    resp = client.get("/api/v1/history/BBCA", params={"page": 1, "page_size": 50})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["pagination"]["page"] == 1
    assert data["pagination"]["page_size"] == 50
    assert len(data["bars"]) <= 50


def test_history_invalid_page_size_rejected(client):
    resp = client.get("/api/v1/history/BBCA", params={"page_size": 99999})
    assert resp.status_code == 422


def test_history_invalid_interval_rejected(client):
    resp = client.get("/api/v1/history/BBCA", params={"interval": "7y"})
    assert resp.status_code == 422
