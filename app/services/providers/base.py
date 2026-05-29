"""Provider interface and normalised data structures.

All providers return the same :class:`ChartResult` shape so the rest of the
application is agnostic to the upstream source. A result couples lightweight
instrument metadata with a pandas ``DataFrame`` of OHLCV observations indexed by
timezone-aware (UTC) timestamps.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx
import pandas as pd

# Canonical OHLCV column order used throughout the application.
OHLCV_COLUMNS: tuple[str, ...] = ("open", "high", "low", "close", "volume")


@dataclass(slots=True)
class MarketMeta:
    """Instrument metadata extracted from a provider response."""

    symbol: str
    currency: str
    exchange: str
    exchange_timezone: str
    instrument_type: str
    short_name: str | None
    regular_market_price: float | None
    previous_close: float | None
    regular_market_time: int | None


@dataclass(slots=True)
class ChartResult:
    """A provider's normalised chart payload."""

    meta: MarketMeta
    frame: pd.DataFrame  # index: tz-aware UTC DatetimeIndex; columns: OHLCV_COLUMNS
    source: str


class MarketDataProvider(ABC):
    """Common contract every market-data provider must satisfy."""

    #: Stable, human-readable provider identifier used in metadata/logs.
    name: str = "abstract"

    @abstractmethod
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
        """Fetch a normalised OHLCV chart for ``symbol``.

        Either ``range_`` (a relative window like ``1mo``) or an explicit
        ``period1``/``period2`` epoch-second range must be supplied. Implementations
        raise :class:`~app.core.exceptions.UpstreamError` /
        :class:`~app.core.exceptions.UpstreamTimeoutError` on failure.
        """
