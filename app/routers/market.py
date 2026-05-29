"""Market-wide screeners: summary, top gainers/losers, unusual volume.

All screeners scan the curated IDX universe and are therefore *heavy*: they use
the stricter heavy rate limit and require the ``analysis`` scope. Results are
cached to keep the upstream fan-out bounded under load.
"""

# `from __future__ import annotations` is intentionally omitted (see stock.py):
# FastAPI needs real Query/response annotations resolved at import time.

from fastapi import APIRouter, Depends, Query, Request

from app.core.config import get_settings
from app.dependencies import get_screener
from app.routers.helpers import meta_for
from app.schemas.analysis import MarketMover, MarketSummary
from app.schemas.common import Envelope
from app.security.dependencies import require_analysis
from app.security.rate_limit import limiter
from app.services.universe import MarketScreener

router = APIRouter(prefix="/market", tags=["market"])
movers_router = APIRouter(tags=["market"])

_settings = get_settings()
_SOURCE = "idx_universe_screener"


@router.get(
    "/summary",
    response_model=Envelope[MarketSummary],
    dependencies=[Depends(require_analysis)],
    summary="Aggregate snapshot of the tracked IDX universe",
)
@limiter.limit(_settings.rate_limit_heavy)
async def market_summary(
    request: Request,
    screener: MarketScreener = Depends(get_screener),
) -> Envelope[MarketSummary]:
    summary = await screener.get_summary()
    return Envelope(meta=meta_for(None, _SOURCE), data=summary)


@movers_router.get(
    "/top-gainers",
    response_model=Envelope[list[MarketMover]],
    dependencies=[Depends(require_analysis)],
    summary="Top gainers by percentage change",
)
@limiter.limit(_settings.rate_limit_heavy)
async def top_gainers(
    request: Request,
    limit: int = Query(default=10, ge=1, le=45),
    screener: MarketScreener = Depends(get_screener),
) -> Envelope[list[MarketMover]]:
    movers = await screener.get_top_gainers(limit)
    return Envelope(meta=meta_for(None, _SOURCE), data=movers)


@movers_router.get(
    "/top-losers",
    response_model=Envelope[list[MarketMover]],
    dependencies=[Depends(require_analysis)],
    summary="Top losers by percentage change",
)
@limiter.limit(_settings.rate_limit_heavy)
async def top_losers(
    request: Request,
    limit: int = Query(default=10, ge=1, le=45),
    screener: MarketScreener = Depends(get_screener),
) -> Envelope[list[MarketMover]]:
    movers = await screener.get_top_losers(limit)
    return Envelope(meta=meta_for(None, _SOURCE), data=movers)


@movers_router.get(
    "/unusual-volume",
    response_model=Envelope[list[MarketMover]],
    dependencies=[Depends(require_analysis)],
    summary="Symbols trading on unusually high relative volume",
)
@limiter.limit(_settings.rate_limit_heavy)
async def unusual_volume(
    request: Request,
    limit: int = Query(default=10, ge=1, le=45),
    screener: MarketScreener = Depends(get_screener),
) -> Envelope[list[MarketMover]]:
    movers = await screener.get_unusual_volume(limit)
    return Envelope(meta=meta_for(None, _SOURCE), data=movers)
