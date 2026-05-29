"""Shared helpers for building response envelopes inside routers."""

from __future__ import annotations

from app.schemas.common import ResponseMeta
from app.services.market_data import SourceInfo
from app.utils.timeutils import now_utc


def meta_from_source(info: SourceInfo) -> ResponseMeta:
    """Build a :class:`ResponseMeta` from a service :class:`SourceInfo`."""
    return ResponseMeta(
        symbol=info.symbol,
        exchange=info.exchange,
        currency=info.currency,
        source=info.source,
        generated_at=now_utc(),
        cached=info.cached,
    )


def meta_for(symbol: str | None, source: str, *, cached: bool = False) -> ResponseMeta:
    """Build a :class:`ResponseMeta` for computed/aggregate responses."""
    return ResponseMeta(
        symbol=symbol,
        source=source,
        generated_at=now_utc(),
        cached=cached,
    )
