"""Stock data router: realtime quotes and paginated historical OHLCV."""

# NOTE: `from __future__ import annotations` is intentionally NOT used here.
# FastAPI must resolve Enum/Path/Query parameter annotations to real types at
# import time; deferred (string) annotations leave them as unresolved ForwardRefs.

from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Path, Query, Request

from app.core.config import get_settings
from app.core.exceptions import ValidationError
from app.dependencies import get_market_data
from app.routers.helpers import meta_from_source
from app.schemas.common import Envelope, Interval
from app.schemas.stock import HistoryData, Quote
from app.security.dependencies import require_read
from app.security.rate_limit import limiter
from app.services.market_data import MarketDataService
from app.utils.ticker import normalize_symbol
from app.utils.timeutils import JAKARTA_TZ

router = APIRouter(prefix="/stock", tags=["stock"])
history_router = APIRouter(prefix="/history", tags=["history"])

_settings = get_settings()

# Symbol path parameter: bounded length, validated/normalised in the handler.
_SymbolPath = Path(..., min_length=1, max_length=12, examples=["BBCA"], description="IDX ticker symbol.")


@router.get(
    "/{symbol}",
    response_model=Envelope[Quote],
    dependencies=[Depends(require_read)],
    summary="Realtime quote for an IDX symbol",
)
@limiter.limit(_settings.rate_limit_public)
async def get_quote(
    request: Request,
    symbol: str = _SymbolPath,
    market_data: MarketDataService = Depends(get_market_data),
) -> Envelope[Quote]:
    normalized = normalize_symbol(symbol)
    quote, info = await market_data.get_quote(normalized)
    return Envelope(meta=meta_from_source(info), data=quote)


@history_router.get(
    "/{symbol}",
    response_model=Envelope[HistoryData],
    dependencies=[Depends(require_read)],
    summary="Historical OHLCV with pagination",
)
@limiter.limit(_settings.rate_limit_public)
async def get_history(
    request: Request,
    symbol: str = _SymbolPath,
    start: date | None = Query(default=None, description="Start date (inclusive), Jakarta time."),
    end: date | None = Query(default=None, description="End date (inclusive), Jakarta time."),
    interval: Interval = Query(default=Interval.D1, description="Sampling interval."),
    page: int = Query(default=1, ge=1, le=100_000, description="1-based page index."),
    page_size: int = Query(default=200, ge=1, le=1000, description="Rows per page."),
    market_data: MarketDataService = Depends(get_market_data),
) -> Envelope[HistoryData]:
    normalized = normalize_symbol(symbol)

    # Default window: trailing one year up to today (Jakarta).
    today = datetime.now(tz=JAKARTA_TZ).date()
    end_date = end or today
    start_date = start or (end_date - timedelta(days=365))

    if start_date >= end_date:
        raise ValidationError("`start` must be earlier than `end`.")
    if end_date > today + timedelta(days=1):
        raise ValidationError("`end` cannot be in the future.")

    start_dt = datetime.combine(start_date, datetime.min.time(), tzinfo=JAKARTA_TZ)
    end_dt = datetime.combine(end_date, datetime.max.time(), tzinfo=JAKARTA_TZ)

    history, info = await market_data.get_history(
        normalized,
        start=start_dt,
        end=end_dt,
        interval=interval,
        page=page,
        page_size=page_size,
    )
    return Envelope(meta=meta_from_source(info), data=history)
