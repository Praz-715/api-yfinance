"""Shared enums and envelope models used across all endpoints."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class SignalType(str, Enum):
    """Discrete trading signal classification."""

    STRONG_BUY = "strong_buy"
    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"
    STRONG_SELL = "strong_sell"


class TrendDirection(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    SIDEWAYS = "sideways"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Interval(str, Enum):
    """Supported sampling intervals (mapped to provider-native values)."""

    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    H1 = "1h"
    D1 = "1d"
    WK1 = "1wk"
    MO1 = "1mo"


class ResponseMeta(BaseModel):
    """Provenance metadata attached to every successful data response."""

    model_config = ConfigDict(extra="forbid")

    symbol: str | None = Field(default=None, description="Canonical IDX symbol, e.g. BBCA.JK.")
    exchange: str = Field(default="IDX", description="Source exchange identifier.")
    currency: str = Field(default="IDR", description="Currency of all monetary values.")
    timezone: str = Field(default="Asia/Jakarta", description="Time zone of all timestamps.")
    source: str = Field(description="Upstream data provider that served the data.")
    generated_at: datetime = Field(description="UTC instant the response was produced.")
    cached: bool = Field(default=False, description="Whether the payload was served from cache.")
    disclaimer: str = Field(
        default=(
            "Data is provided for informational purposes only and may be delayed. "
            "It is not investment advice."
        ),
    )


class Envelope(BaseModel, Generic[T]):
    """Uniform success envelope: ``{ meta, data }``."""

    model_config = ConfigDict(extra="forbid")

    meta: ResponseMeta
    data: T


class ErrorBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(description="Stable machine-readable error code.")
    message: str = Field(description="Safe, human-readable explanation.")
    request_id: str = Field(description="Correlation id for support/debugging.")
    details: dict[str, object] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    """Uniform error envelope returned for every non-2xx response."""

    model_config = ConfigDict(extra="forbid")

    error: ErrorBody


class PaginationMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total_items: int = Field(ge=0)
    total_pages: int = Field(ge=0)
    has_next: bool
    has_previous: bool
