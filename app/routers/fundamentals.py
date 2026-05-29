"""Fundamentals router: full fundamental snapshot and multi-symbol comparison.

Heavy endpoints (extra upstream calls + parsing) — protected by the heavy rate
limit and the ``analysis`` scope. Results are cached with a long TTL because
fundamental data changes slowly.
"""

# `from __future__ import annotations` is intentionally omitted (see stock.py):
# FastAPI needs Path/Query/response annotations resolved at import time.

from fastapi import APIRouter, Depends, Path, Query, Request

from app.core.config import get_settings
from app.core.exceptions import ValidationError
from app.dependencies import get_fundamentals
from app.routers.helpers import meta_from_source
from app.schemas.common import Envelope
from app.schemas.fundamentals import CompareRow, Fundamentals
from app.security.dependencies import require_analysis
from app.security.rate_limit import limiter
from app.services.fundamentals import FundamentalsService
from app.utils.ticker import normalize_symbol

router = APIRouter(tags=["fundamentals"])

_settings = get_settings()
_SymbolPath = Path(..., min_length=1, max_length=12, examples=["BBCA"], description="IDX ticker symbol.")

# Upper bound on a single comparison request to keep the upstream fan-out bounded.
MAX_COMPARE_SYMBOLS = 10


@router.get(
    "/fundamentals/{symbol}",
    response_model=Envelope[Fundamentals],
    dependencies=[Depends(require_analysis)],
    summary="Full fundamental snapshot (valuation, profitability, health, growth)",
)
@limiter.limit(_settings.rate_limit_heavy)
async def get_fundamentals_endpoint(
    request: Request,
    symbol: str = _SymbolPath,
    service: FundamentalsService = Depends(get_fundamentals),
) -> Envelope[Fundamentals]:
    normalized = normalize_symbol(symbol)
    data, info = await service.get_fundamentals(normalized)
    return Envelope(meta=meta_from_source(info), data=data)


@router.get(
    "/compare",
    response_model=Envelope[list[CompareRow]],
    dependencies=[Depends(require_analysis)],
    summary="Compare headline fundamentals across multiple symbols",
)
@limiter.limit(_settings.rate_limit_heavy)
async def compare_endpoint(
    request: Request,
    symbols: str = Query(..., description="Comma-separated IDX tickers, e.g. BBCA,BBRI,BMRI.", examples=["BBCA,BBRI,BMRI"]),
    service: FundamentalsService = Depends(get_fundamentals),
) -> Envelope[list[CompareRow]]:
    raw = [s for s in (part.strip() for part in symbols.split(",")) if s]
    if not raw:
        raise ValidationError("Provide at least one symbol in `symbols`.")
    if len(raw) > MAX_COMPARE_SYMBOLS:
        raise ValidationError(f"At most {MAX_COMPARE_SYMBOLS} symbols may be compared per request.")

    # Validate/normalise every symbol up front (deduplicated, order preserved).
    seen: set[str] = set()
    normalized: list[str] = []
    for item in raw:
        canonical = normalize_symbol(item)
        if canonical not in seen:
            seen.add(canonical)
            normalized.append(canonical)

    rows = await service.get_comparison(normalized)
    return Envelope(meta=meta_from_source(_compare_meta()), data=rows)


def _compare_meta():
    from app.services.market_data import SourceInfo

    return SourceInfo(symbol=None, source="yahoo_finance", currency="IDR", exchange="IDX", cached=False)
