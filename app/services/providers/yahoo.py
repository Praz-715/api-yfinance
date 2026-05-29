"""Yahoo Finance market-data provider.

Uses Yahoo's public ``/v8/finance/chart`` endpoint, which returns instrument
metadata together with timestamped OHLCV arrays and does not require an
authenticated crumb. Two interchangeable hosts (``query1``/``query2``) are tried
in turn, each guarded by its own circuit breaker, giving host-level failover in
addition to the provider-level failover handled by the manager.

Indonesian equities are addressed with the Jakarta exchange suffix, e.g.
``BBCA.JK``.
"""

from __future__ import annotations

import asyncio

import httpx
import pandas as pd

from app.core.circuit_breaker import CircuitBreaker, CircuitOpenError
from app.core.config import Settings
from app.core.exceptions import UpstreamError, UpstreamTimeoutError
from app.core.logging import get_logger
from app.services.providers.base import ChartResult, MarketDataProvider, MarketMeta, OHLCV_COLUMNS

logger = get_logger("provider.yahoo")

_HOSTS: tuple[str, ...] = ("query1.finance.yahoo.com", "query2.finance.yahoo.com")

# A realistic browser User-Agent; Yahoo rejects empty/无 UAs.
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class YahooFinanceProvider(MarketDataProvider):
    name = "yahoo_finance"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._timeout = settings.provider_timeout_seconds
        self._max_retries = settings.provider_max_retries
        self._backoff = settings.provider_backoff_seconds
        self._breakers: dict[str, CircuitBreaker] = {
            host: CircuitBreaker(
                name=f"yahoo:{host}",
                failure_threshold=settings.circuit_breaker_failure_threshold,
                reset_seconds=settings.circuit_breaker_reset_seconds,
            )
            for host in _HOSTS
        }

    async def fetch_chart(
        self,
        client: httpx.AsyncClient,
        symbol: str,
        *,
        range_: str | None = None,
        interval: str = "1d",
        period1: int | None = None,
        period2: int | None = None,
    ) -> ChartResult:
        params: dict[str, str | int] = {
            "interval": interval,
            "includePrePost": "false",
            "events": "div,split",
        }
        if period1 is not None and period2 is not None:
            params["period1"] = period1
            params["period2"] = period2
        else:
            params["range"] = range_ or "1mo"

        last_error: Exception | None = None
        for host in _HOSTS:
            breaker = self._breakers[host]
            if not await breaker.allow():
                last_error = CircuitOpenError(host)
                continue
            try:
                payload = await self._request(client, host, symbol, params)
                await breaker.record_success()
                return self._parse(payload, symbol)
            except UpstreamTimeoutError as exc:
                await breaker.record_failure()
                last_error = exc
            except UpstreamError as exc:
                await breaker.record_failure()
                last_error = exc

        if isinstance(last_error, UpstreamTimeoutError):
            raise last_error
        raise UpstreamError("Yahoo Finance is unavailable.") from last_error

    async def _request(
        self,
        client: httpx.AsyncClient,
        host: str,
        symbol: str,
        params: dict[str, str | int],
    ) -> dict:
        url = f"https://{host}/v8/finance/chart/{symbol}"
        attempt = 0
        while True:
            try:
                response = await client.get(
                    url,
                    params=params,
                    headers={"User-Agent": _UA, "Accept": "application/json"},
                    timeout=self._timeout,
                )
            except httpx.TimeoutException as exc:
                raise UpstreamTimeoutError() from exc
            except httpx.HTTPError as exc:
                raise UpstreamError("Network error contacting Yahoo Finance.") from exc

            # 404/400 are deterministic (bad symbol) — do not retry.
            if response.status_code in (400, 404):
                raise UpstreamError("The requested symbol was not found upstream.")

            # Retry transient server/Throttle responses with backoff.
            if response.status_code >= 500 or response.status_code == 429:
                if attempt < self._max_retries:
                    attempt += 1
                    await asyncio.sleep(self._backoff * attempt)
                    continue
                raise UpstreamError(f"Yahoo Finance responded with status {response.status_code}.")

            if response.status_code != 200:
                raise UpstreamError(f"Yahoo Finance responded with status {response.status_code}.")

            try:
                return response.json()
            except ValueError as exc:
                raise UpstreamError("Yahoo Finance returned a malformed response.") from exc

    def _parse(self, payload: dict, symbol: str) -> ChartResult:
        chart = (payload or {}).get("chart") or {}
        if chart.get("error"):
            raise UpstreamError("Yahoo Finance reported an error for this symbol.")

        results = chart.get("result") or []
        if not results:
            raise UpstreamError("Yahoo Finance returned no data for this symbol.")

        result = results[0]
        raw_meta = result.get("meta") or {}
        meta = MarketMeta(
            symbol=str(raw_meta.get("symbol", symbol)),
            currency=str(raw_meta.get("currency", "IDR")),
            exchange=str(raw_meta.get("fullExchangeName") or raw_meta.get("exchangeName") or "IDX"),
            exchange_timezone=str(raw_meta.get("exchangeTimezoneName", "Asia/Jakarta")),
            instrument_type=str(raw_meta.get("instrumentType", "EQUITY")),
            short_name=raw_meta.get("shortName") or raw_meta.get("longName"),
            regular_market_price=_as_float(raw_meta.get("regularMarketPrice")),
            previous_close=_as_float(
                raw_meta.get("previousClose", raw_meta.get("chartPreviousClose"))
            ),
            regular_market_time=_as_int(raw_meta.get("regularMarketTime")),
        )

        timestamps = result.get("timestamp") or []
        quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
        frame = self._build_frame(timestamps, quote)
        return ChartResult(meta=meta, frame=frame, source=self.name)

    @staticmethod
    def _build_frame(timestamps: list[int], quote: dict) -> pd.DataFrame:
        index = pd.to_datetime(pd.Series(timestamps, dtype="float64"), unit="s", utc=True)
        frame = pd.DataFrame(
            {
                "open": quote.get("open") or [],
                "high": quote.get("high") or [],
                "low": quote.get("low") or [],
                "close": quote.get("close") or [],
                "volume": quote.get("volume") or [],
            },
        )
        # Align lengths defensively in case Yahoo returns ragged arrays.
        if len(frame) != len(index):
            n = min(len(frame), len(index))
            frame = frame.iloc[:n].copy()
            index = index.iloc[:n]
        frame.index = pd.DatetimeIndex(index, name="timestamp")
        frame = frame[list(OHLCV_COLUMNS)].astype("float64")
        # Drop rows without a close price (non-trading slots) and forward-fill OHLC.
        frame = frame.dropna(subset=["close"])
        frame["volume"] = frame["volume"].fillna(0.0)
        return frame


def _as_float(value: object) -> float | None:
    try:
        if value is None:
            return None
        result = float(value)  # type: ignore[arg-type]
        return result if result == result else None  # filter NaN
    except (TypeError, ValueError):
        return None


def _as_int(value: object) -> int | None:
    f = _as_float(value)
    return int(f) if f is not None else None
