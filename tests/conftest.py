"""Shared pytest fixtures.

Environment variables are set *before* any application module is imported so the
cached settings singleton picks them up. Upstream network access is replaced by a
deterministic synthetic provider, so the entire stack (caching, indicator maths,
screeners, security) is exercised end-to-end without hitting the internet.
"""

from __future__ import annotations

import itertools
import os

# --- Configure the environment BEFORE importing the application ------------
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("API_KEYS", "test-secret-key-0123456789abcdef")
os.environ.setdefault("JWT_SECRET", "0123456789abcdef0123456789abcdef0123456789abcdef")
os.environ.setdefault("ALLOWED_ORIGINS", "https://teguh-prasetyo.com,https://www.teguh-prasetyo.com")
os.environ.setdefault("RATE_LIMIT_HEAVY", "10/minute")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.services.providers.base import ChartResult, MarketMeta  # noqa: E402

VALID_API_KEY = "test-secret-key-0123456789abcdef"
ALLOWED_ORIGIN = "https://teguh-prasetyo.com"

# Monotonic counter so each TestClient gets a unique source IP and therefore an
# isolated rate-limit bucket (prevents cross-test interference).
_ip_counter = itertools.count(1)


def build_synthetic_chart(symbol: str = "BBCA.JK", n: int = 300, start_price: float = 1000.0) -> ChartResult:
    """Construct a deterministic upward-trending OHLCV chart for testing."""
    index = pd.date_range(end="2024-12-31", periods=n, freq="D", tz="UTC")
    # Gentle uptrend plus a deterministic oscillation — no randomness.
    trend = np.linspace(0.0, 0.4 * start_price, n)
    wave = 20.0 * np.sin(np.linspace(0.0, 12.0, n))
    close = start_price + trend + wave
    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(open_, close) + 5.0
    low = np.minimum(open_, close) - 5.0
    volume = np.linspace(1_000_000, 1_500_000, n)
    # A single deliberate volume spike on the last bar.
    volume[-1] = 6_000_000

    frame = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=pd.DatetimeIndex(index, name="timestamp"),
    ).astype("float64")

    meta = MarketMeta(
        symbol=symbol,
        currency="IDR",
        exchange="Jakarta",
        exchange_timezone="Asia/Jakarta",
        instrument_type="EQUITY",
        short_name=symbol.replace(".JK", ""),
        regular_market_price=float(close[-1]),
        previous_close=float(close[-2]),
        regular_market_time=1_735_603_200,
    )
    return ChartResult(meta=meta, frame=frame, source="synthetic")


@pytest.fixture
def app_instance():
    """A fresh app whose provider layer is replaced with synthetic data."""
    from app.main import create_app

    app = create_app()

    async def fake_get_chart(symbol, *, range_=None, interval="1d", period1=None, period2=None):
        return build_synthetic_chart(symbol)

    # Replace the upstream call on the live provider manager singleton.
    app.state.providers.get_chart = fake_get_chart
    return app


@pytest.fixture
def client_factory(app_instance):
    """Factory producing isolated TestClients with optional API-key auth."""

    def _make(*, api_key: bool = True, origin: str | None = None) -> TestClient:
        client = TestClient(app_instance)
        client.headers.update({"X-Forwarded-For": f"203.0.113.{next(_ip_counter) % 250 + 1}"})
        client.headers.update({"User-Agent": "pytest-client/1.0"})
        if api_key:
            client.headers.update({"X-API-Key": VALID_API_KEY})
        if origin:
            client.headers.update({"Origin": origin})
        return client

    return _make


@pytest.fixture
def client(client_factory):
    """Authenticated client for the happy path."""
    return client_factory(api_key=True)
