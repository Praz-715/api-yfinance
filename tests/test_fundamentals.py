"""Tests for the fundamentals endpoints and the quoteSummary extraction."""

from __future__ import annotations

import pytest


def _raw(value):
    """Wrap a value the way Yahoo's formatted quoteSummary does."""
    return {"raw": value, "fmt": str(value)}


def _income(rev, ni):
    return {"totalRevenue": _raw(rev), "netIncome": _raw(ni)}


def _cashflow(ocf, capex):
    return {"totalCashFromOperatingActivities": _raw(ocf), "capitalExpenditures": _raw(capex)}


SAMPLE_MODULES = {
    "price": {"symbol": "BBCA.JK", "longName": "Bank Central Asia Tbk", "currency": "IDR", "marketCap": _raw(1.2e15)},
    "assetProfile": {
        "sector": "Financial Services",
        "industry": "Banks - Regional",
        "fullTimeEmployees": 25000,
        "country": "Indonesia",
        "website": "https://www.bca.co.id",
        "longBusinessSummary": "Bank Central Asia provides banking products and services.",
    },
    "summaryDetail": {
        "trailingPE": _raw(22.5),
        "forwardPE": _raw(20.1),
        "priceToSalesTrailing12Months": _raw(9.8),
        "dividendRate": _raw(200.0),
        "dividendYield": _raw(0.023),
        "payoutRatio": _raw(0.45),
        "beta": _raw(1.1),
        "fiftyTwoWeekHigh": _raw(10800.0),
        "fiftyTwoWeekLow": _raw(8000.0),
        "averageVolume": _raw(50_000_000),
        "exDividendDate": _raw(1_710_000_000),
    },
    "financialData": {
        "returnOnEquity": _raw(0.22),
        "returnOnAssets": _raw(0.03),
        "profitMargins": _raw(0.45),
        "grossMargins": _raw(0.0),
        "operatingMargins": _raw(0.55),
        "totalCash": _raw(112_000_000_000_000),
        "totalDebt": _raw(2_700_000_000_000),
        "debtToEquity": _raw(15.4),
        "currentRatio": _raw(1.3),
        "quickRatio": _raw(1.1),
        "freeCashflow": _raw(40_000_000_000_000),
        "operatingCashflow": _raw(60_000_000_000_000),
        "revenueGrowth": _raw(0.12),
        "earningsGrowth": _raw(0.10),
        "revenuePerShare": _raw(850.0),
    },
    "defaultKeyStatistics": {
        "pegRatio": _raw(1.6),
        "priceToBook": _raw(4.5),
        "enterpriseValue": _raw(1.1e15),
        "enterpriseToEbitda": _raw(15.0),
        "trailingEps": _raw(400.0),
        "forwardEps": _raw(450.0),
        "bookValue": _raw(2000.0),
        "sharesOutstanding": _raw(123_000_000_000),
        "floatShares": _raw(60_000_000_000),
    },
    "incomeStatementHistory": {
        "incomeStatementHistory": [
            _income(80_000, 50_000),  # newest
            _income(70_000, 44_000),
            _income(62_000, 38_000),
            _income(55_000, 33_000),  # oldest
        ]
    },
    "cashflowStatementHistory": {
        "cashflowStatements": [
            _cashflow(60_000, -10_000),
            _cashflow(52_000, -9_000),
            _cashflow(45_000, -8_000),
            _cashflow(40_000, -7_000),
        ]
    },
}


@pytest.fixture
def fundamentals_app(app_instance):
    """Patch the provider's quoteSummary call with the deterministic sample."""

    async def fake_quote_summary(symbol, modules=None):
        return SAMPLE_MODULES

    app_instance.state.providers.get_quote_summary = fake_quote_summary
    return app_instance


@pytest.fixture
def f_client(fundamentals_app, client_factory):
    # client_factory builds a TestClient from app_instance; both fixtures share
    # the same patched app because app_instance is function-scoped.
    return client_factory(api_key=True)


def test_fundamentals_endpoint(f_client):
    resp = f_client.get("/api/v1/fundamentals/BBCA")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["symbol"] == "BBCA.JK"
    assert data["profile"]["sector"] == "Financial Services"
    assert data["valuation"]["trailing_pe"] == 22.5
    assert data["valuation"]["peg_ratio"] == 1.6
    assert data["profitability"]["return_on_equity"] == 0.22
    assert data["financial_health"]["total_cash"] == 112_000_000_000_000
    assert data["financial_health"]["total_debt"] == 2_700_000_000_000
    # net_debt = debt - cash (negative here: cash-rich bank)
    assert data["financial_health"]["net_debt"] == 2_700_000_000_000 - 112_000_000_000_000
    assert data["dividend"]["yield"] == 0.023
    assert data["market"]["fifty_two_week_high"] == 10800.0


def test_fundamentals_cagr_computed(f_client):
    data = f_client.get("/api/v1/fundamentals/BBCA").json()["data"]
    g = data["growth"]
    # Revenue grew 55000 -> 80000 over 3 periods => CAGR ~ 13.3%
    assert g["revenue_cagr_3y"] is not None and 0.12 < g["revenue_cagr_3y"] < 0.15
    assert g["net_income_cagr_3y"] is not None
    assert g["free_cash_flow_cagr_3y"] is not None
    assert g["revenue_history"] == [55_000, 62_000, 70_000, 80_000]  # oldest -> newest
    assert g["revenue_growth_yoy"] == 0.12  # from financialData


def test_compare_endpoint(f_client):
    resp = f_client.get("/api/v1/compare", params={"symbols": "BBCA,BBRI,BMRI"})
    assert resp.status_code == 200
    rows = resp.json()["data"]
    assert len(rows) == 3
    for row in rows:
        assert row["symbol"].endswith(".JK")
        assert row["trailing_pe"] == 22.5
        assert row["return_on_equity"] == 0.22


def test_compare_rejects_too_many(f_client):
    many = ",".join(f"SYM{i}" for i in range(11))
    resp = f_client.get("/api/v1/compare", params={"symbols": many})
    assert resp.status_code == 422


def test_compare_requires_symbols(f_client):
    resp = f_client.get("/api/v1/compare", params={"symbols": " , , "})
    assert resp.status_code == 422


def test_fundamentals_requires_analysis_scope(fundamentals_app, client_factory):
    from tests.conftest import VALID_API_KEY

    issuer = client_factory(api_key=False)
    tokens = issuer.post(
        "/api/v1/auth/token", json={"scopes": ["read"]}, headers={"X-API-Key": VALID_API_KEY}
    ).json()
    caller = client_factory(api_key=False)
    resp = caller.get(
        "/api/v1/fundamentals/BBCA",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert resp.status_code == 403
