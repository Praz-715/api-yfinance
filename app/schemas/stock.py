"""Schemas for raw stock data: quotes and historical OHLCV."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import Interval, PaginationMeta


class Quote(BaseModel):
    """A realtime (or last-known) quote snapshot."""

    model_config = ConfigDict(extra="forbid")

    symbol: str
    name: str | None = None
    price: float = Field(description="Most recent traded/last price.")
    previous_close: float | None = None
    change: float | None = Field(default=None, description="Absolute change vs previous close.")
    change_percent: float | None = Field(default=None, description="Percentage change vs previous close.")
    day_open: float | None = None
    day_high: float | None = None
    day_low: float | None = None
    volume: int | None = None
    market_time: datetime | None = Field(default=None, description="Exchange timestamp of the quote.")
    is_market_open: bool = Field(description="Indicative IDX session-open flag.")


class OHLCVBar(BaseModel):
    """A single open/high/low/close/volume observation."""

    model_config = ConfigDict(extra="forbid")

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


class HistoryData(BaseModel):
    """Paginated historical OHLCV series."""

    model_config = ConfigDict(extra="forbid")

    symbol: str
    interval: Interval
    start: datetime
    end: datetime
    pagination: PaginationMeta
    bars: list[OHLCVBar]
