"""IDX universe definition and market-wide screeners.

The screeners (market summary, top gainers/losers, unusual volume) operate over a
curated universe of liquid IDX constituents (LQ45-style). Quotes are fetched
concurrently with a bounded semaphore so a single screener call never opens an
unbounded number of upstream connections on the serverless runtime. Failures for
individual symbols are tolerated — the aggregate is computed from whatever
resolved successfully, and the count of evaluated symbols is reported.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from app.core.cache import CacheBackend
from app.core.config import Settings
from app.core.exceptions import AppError
from app.schemas.analysis import MarketMover, MarketSummary
from app.schemas.common import Interval
from app.schemas.stock import Quote
from app.services.analysis import compute_technical
from app.services.market_data import MarketDataService
from app.utils.ticker import normalize_symbol
from app.utils.timeutils import is_market_open

# Curated, liquid IDX universe (LQ45-style). Stored as canonical ``.JK`` symbols.
IDX_UNIVERSE: tuple[str, ...] = tuple(
    normalize_symbol(base)
    for base in (
        "BBCA", "BBRI", "BMRI", "BBNI", "TLKM", "ASII", "UNVR", "ICBP", "INDF",
        "GGRM", "HMSP", "KLBF", "UNTR", "ANTM", "INKP", "PGAS", "PTBA", "SMGR",
        "ADRO", "MDKA", "AMRT", "CPIN", "TOWR", "EXCL", "ISAT", "JPFA", "MNCN",
        "INCO", "ITMG", "BRPT", "TPIA", "MEDC", "BUKA", "EMTK", "ARTO", "BRIS",
        "TINS", "AKRA", "INTP", "SMRA", "CTRA", "BSDE", "MAPI", "ERAA", "ACES",
    )
)

T = TypeVar("T")


class MarketScreener:
    def __init__(self, market_data: MarketDataService, cache: CacheBackend, settings: Settings) -> None:
        self._market_data = market_data
        self._cache = cache
        self._settings = settings
        self._concurrency = settings.market_universe_concurrency
        self._ttl = settings.market_cache_ttl_seconds

    async def _gather(self, fetch_one: Callable[[str], Awaitable[T]]) -> list[T]:
        """Run ``fetch_one`` across the universe with bounded concurrency."""
        semaphore = asyncio.Semaphore(self._concurrency)

        async def run(symbol: str) -> T | None:
            async with semaphore:
                try:
                    return await fetch_one(symbol)
                except AppError:
                    return None

        results = await asyncio.gather(*(run(sym) for sym in IDX_UNIVERSE))
        return [r for r in results if r is not None]

    async def _quotes(self) -> list[Quote]:
        async def fetch(symbol: str) -> Quote:
            quote, _ = await self._market_data.get_quote(symbol)
            return quote

        return await self._gather(fetch)

    async def get_summary(self) -> MarketSummary:
        cached = await self._cache.get("screener:summary")
        if cached is not None:
            return MarketSummary.model_validate(cached)

        quotes = await self._quotes()
        advancers = sum(1 for q in quotes if (q.change_percent or 0) > 0)
        decliners = sum(1 for q in quotes if (q.change_percent or 0) < 0)
        unchanged = sum(1 for q in quotes if (q.change_percent or 0) == 0)
        changes = [q.change_percent for q in quotes if q.change_percent is not None]
        avg_change = round(sum(changes) / len(changes), 4) if changes else None

        gainers = _movers(quotes, descending=True, limit=10)
        losers = _movers(quotes, descending=False, limit=10)

        summary = MarketSummary(
            universe_size=len(IDX_UNIVERSE),
            evaluated=len(quotes),
            advancers=advancers,
            decliners=decliners,
            unchanged=unchanged,
            average_change_percent=avg_change,
            is_market_open=is_market_open(),
            top_gainers=gainers,
            top_losers=losers,
        )
        await self._cache.set("screener:summary", summary.model_dump(mode="json"), self._ttl)
        return summary

    async def get_top_gainers(self, limit: int = 10) -> list[MarketMover]:
        quotes = await self._quotes()
        return _movers(quotes, descending=True, limit=limit)

    async def get_top_losers(self, limit: int = 10) -> list[MarketMover]:
        quotes = await self._quotes()
        return _movers(quotes, descending=False, limit=limit)

    async def get_unusual_volume(self, limit: int = 10) -> list[MarketMover]:
        """Rank the universe by relative volume (today vs 20-day average)."""
        cache_key = f"screener:unusual_volume:{limit}"
        cached = await self._cache.get(cache_key)
        if cached is not None:
            return [MarketMover.model_validate(m) for m in cached]

        async def fetch(symbol: str) -> MarketMover | None:
            chart, _ = await self._market_data.get_analysis_chart(symbol, Interval.D1)
            tech = compute_technical(chart, Interval.D1)
            return MarketMover(
                symbol=chart.meta.symbol,
                price=tech.last_price,
                volume=tech.volume.latest_volume,
                relative_volume=tech.volume.relative_volume,
            )

        movers = [m for m in await self._gather(fetch) if m is not None]
        movers.sort(key=lambda m: m.relative_volume or 0.0, reverse=True)
        top = movers[:limit]
        await self._cache.set(cache_key, [m.model_dump(mode="json") for m in top], self._ttl)
        return top


def _movers(quotes: list[Quote], *, descending: bool, limit: int) -> list[MarketMover]:
    """Build the top/bottom movers by percentage change."""
    ranked = [q for q in quotes if q.change_percent is not None]
    ranked.sort(key=lambda q: q.change_percent or 0.0, reverse=descending)
    return [
        MarketMover(
            symbol=q.symbol,
            price=q.price,
            change=q.change,
            change_percent=q.change_percent,
            volume=q.volume,
        )
        for q in ranked[:limit]
    ]
