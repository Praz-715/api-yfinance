"""Market-data service.

Sits between the routers and the provider manager. Responsibilities:

* caching of normalised chart payloads (provider-agnostic, serialisable);
* turning charts into the public :class:`Quote` and :class:`HistoryData` shapes;
* mapping API intervals/ranges to provider-native parameters.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from app.core.cache import CacheBackend
from app.core.config import Settings
from app.core.exceptions import InsufficientDataError
from app.schemas.common import Interval, PaginationMeta
from app.schemas.stock import HistoryData, OHLCVBar, Quote
from app.services.providers.base import ChartResult, MarketMeta, OHLCV_COLUMNS
from app.services.providers.manager import ProviderManager
from app.utils.timeutils import epoch_to_jakarta, is_market_open

# Default look-back window per interval, sized so trend/long-MA indicators have
# enough observations (e.g. a 200-period SMA on daily data needs ~1 year).
DEFAULT_RANGE_FOR_INTERVAL: dict[str, str] = {
    "1m": "1d",
    "5m": "5d",
    "15m": "1mo",
    "30m": "1mo",
    "1h": "3mo",
    "1d": "1y",
    "1wk": "5y",
    "1mo": "max",
}


@dataclass(slots=True)
class SourceInfo:
    """Provenance details propagated into the response envelope."""

    symbol: str
    source: str
    currency: str
    exchange: str
    cached: bool


class MarketDataService:
    def __init__(self, providers: ProviderManager, cache: CacheBackend, settings: Settings) -> None:
        self._providers = providers
        self._cache = cache
        self._settings = settings

    # ----------------------------------------------------------- chart + cache
    async def get_chart(
        self,
        symbol: str,
        *,
        interval: str,
        range_: str | None = None,
        period1: int | None = None,
        period2: int | None = None,
        ttl_seconds: int | None = None,
    ) -> tuple[ChartResult, bool]:
        """Return ``(chart, cached)`` for the given parameters, using the cache."""
        key = f"chart:{symbol}:{interval}:{range_}:{period1}:{period2}"
        cached_payload = await self._cache.get(key)
        if cached_payload is not None:
            return _deserialize_chart(cached_payload), True

        chart = await self._providers.get_chart(
            symbol,
            range_=range_,
            interval=interval,
            period1=period1,
            period2=period2,
        )
        ttl = ttl_seconds if ttl_seconds is not None else self._settings.cache_default_ttl_seconds
        await self._cache.set(key, _serialize_chart(chart), ttl)
        return chart, False

    async def get_analysis_chart(self, symbol: str, interval: Interval) -> tuple[ChartResult, bool]:
        """Fetch a chart sized appropriately for indicator computation."""
        range_ = DEFAULT_RANGE_FOR_INTERVAL.get(interval.value, "1y")
        chart, cached = await self.get_chart(
            symbol,
            interval=interval.value,
            range_=range_,
            ttl_seconds=self._settings.history_cache_ttl_seconds,
        )
        if chart.frame.empty:
            raise InsufficientDataError()
        return chart, cached

    # -------------------------------------------------------------------- quote
    async def get_quote(self, symbol: str) -> tuple[Quote, SourceInfo]:
        chart, cached = await self.get_chart(
            symbol,
            interval="5m",
            range_="1d",
            ttl_seconds=self._settings.quote_cache_ttl_seconds,
        )
        quote = _build_quote(symbol, chart)
        info = SourceInfo(
            symbol=chart.meta.symbol,
            source=chart.source,
            currency=chart.meta.currency,
            exchange=chart.meta.exchange,
            cached=cached,
        )
        return quote, info

    # ------------------------------------------------------------------ history
    async def get_history(
        self,
        symbol: str,
        *,
        start: datetime,
        end: datetime,
        interval: Interval,
        page: int,
        page_size: int,
    ) -> tuple[HistoryData, SourceInfo]:
        from app.utils.timeutils import to_epoch_seconds

        chart, cached = await self.get_chart(
            symbol,
            interval=interval.value,
            period1=to_epoch_seconds(start),
            period2=to_epoch_seconds(end),
            ttl_seconds=self._settings.history_cache_ttl_seconds,
        )

        frame = chart.frame
        if frame.empty:
            raise InsufficientDataError()

        # Hard cap to protect memory/payload size on the serverless runtime.
        if len(frame) > self._settings.max_history_rows:
            frame = frame.iloc[-self._settings.max_history_rows :]

        total_items = len(frame)
        total_pages = (total_items + page_size - 1) // page_size
        offset = (page - 1) * page_size
        page_frame = frame.iloc[offset : offset + page_size]

        bars = [
            OHLCVBar(
                timestamp=ts.to_pydatetime(),
                open=float(row.open),
                high=float(row.high),
                low=float(row.low),
                close=float(row.close),
                volume=int(row.volume),
            )
            for ts, row in zip(page_frame.index, page_frame.itertuples(index=False))
        ]

        pagination = PaginationMeta(
            page=page,
            page_size=page_size,
            total_items=total_items,
            total_pages=total_pages,
            has_next=page < total_pages,
            has_previous=page > 1,
        )
        history = HistoryData(
            symbol=chart.meta.symbol,
            interval=interval,
            start=start,
            end=end,
            pagination=pagination,
            bars=bars,
        )
        info = SourceInfo(
            symbol=chart.meta.symbol,
            source=chart.source,
            currency=chart.meta.currency,
            exchange=chart.meta.exchange,
            cached=cached,
        )
        return history, info


# --------------------------------------------------------------------- helpers
def _build_quote(symbol: str, chart: ChartResult) -> Quote:
    meta = chart.meta
    frame = chart.frame

    price = meta.regular_market_price
    if price is None and not frame.empty:
        price = float(frame["close"].iloc[-1])
    if price is None:
        raise InsufficientDataError()

    previous_close = meta.previous_close
    change = change_percent = None
    if previous_close not in (None, 0):
        change = round(price - previous_close, 4)
        change_percent = round((change / previous_close) * 100.0, 4)

    day_open = day_high = day_low = volume = None
    if not frame.empty:
        day_open = float(frame["open"].dropna().iloc[0]) if frame["open"].notna().any() else None
        day_high = float(frame["high"].max()) if frame["high"].notna().any() else None
        day_low = float(frame["low"].min()) if frame["low"].notna().any() else None
        volume = int(frame["volume"].sum())

    market_time = epoch_to_jakarta(meta.regular_market_time) if meta.regular_market_time else None

    return Quote(
        symbol=meta.symbol or symbol,
        name=meta.short_name,
        price=round(float(price), 4),
        previous_close=round(previous_close, 4) if previous_close is not None else None,
        change=change,
        change_percent=change_percent,
        day_open=day_open,
        day_high=day_high,
        day_low=day_low,
        volume=volume,
        market_time=market_time,
        is_market_open=is_market_open(),
    )


def _serialize_chart(chart: ChartResult) -> dict:
    frame = chart.frame
    return {
        "meta": {
            "symbol": chart.meta.symbol,
            "currency": chart.meta.currency,
            "exchange": chart.meta.exchange,
            "exchange_timezone": chart.meta.exchange_timezone,
            "instrument_type": chart.meta.instrument_type,
            "short_name": chart.meta.short_name,
            "regular_market_price": chart.meta.regular_market_price,
            "previous_close": chart.meta.previous_close,
            "regular_market_time": chart.meta.regular_market_time,
        },
        "source": chart.source,
        "index": [int(ts.value // 1_000_000_000) for ts in frame.index],
        **{col: frame[col].tolist() for col in OHLCV_COLUMNS},
    }


def _deserialize_chart(payload: dict) -> ChartResult:
    raw_meta = payload["meta"]
    meta = MarketMeta(**raw_meta)
    index = pd.to_datetime(pd.Series(payload["index"], dtype="int64"), unit="s", utc=True)
    frame = pd.DataFrame({col: payload[col] for col in OHLCV_COLUMNS})
    frame.index = pd.DatetimeIndex(index, name="timestamp")
    frame = frame.astype("float64")
    return ChartResult(meta=meta, frame=frame, source=payload["source"])
