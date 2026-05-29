"""Application-scoped dependency providers.

Singleton services (cache, provider manager, market-data service, screener) are
created once during the application lifespan and stored on ``app.state``. These
providers expose them to routers without re-instantiating per request.
"""

from __future__ import annotations

from fastapi import Request

from app.services.fundamentals import FundamentalsService
from app.services.market_data import MarketDataService
from app.services.universe import MarketScreener


def get_market_data(request: Request) -> MarketDataService:
    return request.app.state.market_data


def get_screener(request: Request) -> MarketScreener:
    return request.app.state.screener


def get_fundamentals(request: Request) -> FundamentalsService:
    return request.app.state.fundamentals
