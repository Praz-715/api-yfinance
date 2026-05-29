"""Analysis router: technical indicators and composite trading signals.

These are *heavy* endpoints (they fetch an extended history and run pandas/numpy
computations) and are therefore protected by the stricter heavy rate limit and
require the ``analysis`` scope.
"""

# `from __future__ import annotations` is intentionally omitted (see stock.py):
# FastAPI needs real Enum/Path/Query annotations resolved at import time.

from fastapi import APIRouter, Depends, Path, Query, Request

from app.core.config import get_settings
from app.dependencies import get_market_data
from app.routers.helpers import meta_for
from app.schemas.analysis import TechnicalIndicators, TradingSignal
from app.schemas.common import Envelope, Interval
from app.security.dependencies import require_analysis
from app.security.rate_limit import limiter
from app.services import analysis as analysis_service
from app.services.market_data import MarketDataService
from app.utils.ticker import normalize_symbol

router = APIRouter(tags=["analysis"])

_settings = get_settings()
_SymbolPath = Path(..., min_length=1, max_length=12, examples=["BBCA"], description="IDX ticker symbol.")


@router.get(
    "/technical/{symbol}",
    response_model=Envelope[TechnicalIndicators],
    dependencies=[Depends(require_analysis)],
    summary="Full technical-indicator bundle",
)
@limiter.limit(_settings.rate_limit_heavy)
async def get_technical(
    request: Request,
    symbol: str = _SymbolPath,
    interval: Interval = Query(default=Interval.D1, description="Sampling interval."),
    market_data: MarketDataService = Depends(get_market_data),
) -> Envelope[TechnicalIndicators]:
    normalized = normalize_symbol(symbol)
    chart, cached = await market_data.get_analysis_chart(normalized, interval)
    indicators = analysis_service.compute_technical(chart, interval)
    meta = meta_for(chart.meta.symbol, chart.source, cached=cached)
    meta.currency = chart.meta.currency
    meta.exchange = chart.meta.exchange
    return Envelope(meta=meta, data=indicators)


@router.get(
    "/signal/{symbol}",
    response_model=Envelope[TradingSignal],
    dependencies=[Depends(require_analysis)],
    summary="Composite trading signal with confidence and risk",
)
@limiter.limit(_settings.rate_limit_heavy)
async def get_signal(
    request: Request,
    symbol: str = _SymbolPath,
    interval: Interval = Query(default=Interval.D1, description="Sampling interval."),
    market_data: MarketDataService = Depends(get_market_data),
) -> Envelope[TradingSignal]:
    normalized = normalize_symbol(symbol)
    chart, cached = await market_data.get_analysis_chart(normalized, interval)
    signal = analysis_service.compute_signal(chart, interval)
    meta = meta_for(chart.meta.symbol, chart.source, cached=cached)
    meta.currency = chart.meta.currency
    meta.exchange = chart.meta.exchange
    return Envelope(meta=meta, data=signal)
