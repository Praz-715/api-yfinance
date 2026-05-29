"""CORS and strict origin-validation tests."""

from __future__ import annotations

from tests.conftest import ALLOWED_ORIGIN


def test_allowed_origin_gets_cors_header(client_factory):
    client = client_factory(api_key=True, origin=ALLOWED_ORIGIN)
    resp = client.get("/api/v1/stock/BBCA")
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == ALLOWED_ORIGIN


def test_disallowed_origin_is_rejected(client_factory):
    client = client_factory(api_key=True, origin="https://evil.example.com")
    resp = client.get("/api/v1/stock/BBCA")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "origin_not_allowed"


def test_null_origin_is_rejected(client_factory):
    client = client_factory(api_key=True, origin="null")
    resp = client.get("/api/v1/stock/BBCA")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "origin_not_allowed"


def test_ip_origin_is_rejected(client_factory):
    client = client_factory(api_key=True, origin="http://203.0.113.10")
    resp = client.get("/api/v1/stock/BBCA")
    assert resp.status_code == 403


def test_preflight_allowed_origin(client_factory):
    client = client_factory(api_key=False)
    resp = client.options(
        "/api/v1/stock/BBCA",
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.status_code in (200, 204)
    assert resp.headers.get("access-control-allow-origin") == ALLOWED_ORIGIN


def test_no_cors_header_for_disallowed_preflight(client_factory):
    client = client_factory(api_key=False)
    resp = client.options(
        "/api/v1/stock/BBCA",
        headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.headers.get("access-control-allow-origin") != "https://evil.example.com"
