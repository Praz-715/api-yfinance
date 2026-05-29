"""Fundamental-analysis service.

Fetches Yahoo's ``quoteSummary`` modules (via the provider layer), normalises the
deeply-nested ``{raw, fmt}`` payload into a clean, typed :class:`Fundamentals`
snapshot, derives multi-year CAGRs from the statement histories, and caches the
result (fundamentals change slowly, so a long TTL is used). Also provides a
multi-symbol comparison view.
"""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, timezone

from app.core.cache import CacheBackend
from app.core.config import Settings
from app.core.exceptions import AppError
from app.schemas.fundamentals import (
    CompanyProfile,
    CompareRow,
    DividendInfo,
    FinancialHealth,
    Fundamentals,
    Growth,
    MarketStats,
    PerShare,
    Profitability,
    Valuation,
)
from app.services.market_data import SourceInfo
from app.services.providers.manager import ProviderManager
from app.utils.ticker import normalize_symbol


def _num(node: dict | None, key: str) -> float | None:
    """Extract a finite float from a Yahoo ``{raw, fmt}`` node (or plain value)."""
    if not node:
        return None
    value = node.get(key)
    if isinstance(value, dict):
        value = value.get("raw")
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _str(node: dict | None, key: str) -> str | None:
    if not node:
        return None
    value = node.get(key)
    return value if isinstance(value, str) and value.strip() else None


def _cagr(values: list[float | None], years: int) -> float | None:
    """Compound annual growth rate over the positive subset of ``values``."""
    positive = [v for v in values if v is not None and v > 0]
    if len(positive) < 2:
        return None
    periods = min(years, len(positive) - 1)
    if periods <= 0:
        return None
    try:
        return round((positive[-1] / positive[0]) ** (1 / periods) - 1, 6)
    except (ArithmeticError, ValueError):
        return None


def _yoy(values: list[float | None]) -> float | None:
    if len(values) >= 2 and values[-2] and values[-1]:
        return round((values[-1] - values[-2]) / abs(values[-2]), 6)
    return None


class FundamentalsService:
    def __init__(self, providers: ProviderManager, cache: CacheBackend, settings: Settings) -> None:
        self._providers = providers
        self._cache = cache
        self._settings = settings
        self._ttl = settings.fundamentals_cache_ttl_seconds

    async def get_fundamentals(self, symbol: str) -> tuple[Fundamentals, SourceInfo]:
        key = f"fundamentals:{symbol}"
        cached = await self._cache.get(key)
        if cached is not None:
            data = Fundamentals.model_validate(cached)
            return data, _source(data, cached_flag=True)

        modules = await self._providers.get_quote_summary(symbol)
        fundamentals = _extract(symbol, modules)
        await self._cache.set(key, fundamentals.model_dump(mode="json", by_alias=True), self._ttl)
        return fundamentals, _source(fundamentals, cached_flag=False)

    async def get_comparison(self, symbols: list[str]) -> list[CompareRow]:
        """Resolve headline metrics for several symbols concurrently."""
        semaphore = asyncio.Semaphore(self._settings.market_universe_concurrency)

        async def one(symbol: str) -> CompareRow:
            async with semaphore:
                try:
                    data, _ = await self.get_fundamentals(symbol)
                except AppError as exc:
                    return CompareRow(symbol=symbol, error=exc.message)
                return CompareRow(
                    symbol=data.symbol,
                    name=data.profile.name,
                    sector=data.profile.sector,
                    market_cap=data.valuation.market_cap,
                    trailing_pe=data.valuation.trailing_pe,
                    forward_pe=data.valuation.forward_pe,
                    price_to_book=data.valuation.price_to_book,
                    peg_ratio=data.valuation.peg_ratio,
                    return_on_equity=data.profitability.return_on_equity,
                    return_on_assets=data.profitability.return_on_assets,
                    profit_margin=data.profitability.profit_margin,
                    revenue_growth_yoy=data.growth.revenue_growth_yoy,
                    earnings_growth_yoy=data.growth.earnings_growth_yoy,
                    debt_to_equity=data.financial_health.debt_to_equity,
                    dividend_yield=data.dividend.yield_,
                    beta=data.market.beta,
                )

        return list(await asyncio.gather(*(one(s) for s in symbols)))


def _source(data: Fundamentals, *, cached_flag: bool) -> SourceInfo:
    return SourceInfo(
        symbol=data.symbol,
        source="yahoo_finance",
        currency=data.currency,
        exchange="IDX",
        cached=cached_flag,
    )


def _extract(symbol: str, modules: dict) -> Fundamentals:
    """Map raw quoteSummary modules into a clean :class:`Fundamentals`."""
    profile_m = modules.get("assetProfile") or {}
    summary_m = modules.get("summaryDetail") or {}
    financial_m = modules.get("financialData") or {}
    stats_m = modules.get("defaultKeyStatistics") or {}
    price_m = modules.get("price") or {}

    # Annual statement histories (Yahoo returns newest-first; reverse to oldest-first).
    income_rows = (modules.get("incomeStatementHistory") or {}).get("incomeStatementHistory") or []
    cashflow_rows = (modules.get("cashflowStatementHistory") or {}).get("cashflowStatements") or []

    revenue_history = [_num(row, "totalRevenue") for row in reversed(income_rows)]
    net_income_history = [_num(row, "netIncome") for row in reversed(income_rows)]
    fcf_history: list[float | None] = []
    for row in reversed(cashflow_rows):
        ocf = _num(row, "totalCashFromOperatingActivities")
        capex = _num(row, "capitalExpenditures")
        fcf_history.append(ocf + capex if ocf is not None and capex is not None else None)

    total_cash = _num(financial_m, "totalCash")
    total_debt = _num(financial_m, "totalDebt")
    net_debt = total_debt - total_cash if total_cash is not None and total_debt is not None else None

    ex_div_epoch = _num(summary_m, "exDividendDate")
    ex_dividend_date = (
        datetime.fromtimestamp(ex_div_epoch, tz=timezone.utc) if ex_div_epoch else None
    )

    currency = _str(price_m, "currency") or _str(summary_m, "currency") or "IDR"

    return Fundamentals(
        symbol=_str(price_m, "symbol") or symbol,
        currency=currency,
        profile=CompanyProfile(
            name=_str(price_m, "longName") or _str(price_m, "shortName"),
            sector=_str(profile_m, "sector"),
            industry=_str(profile_m, "industry"),
            employees=_int(_num(profile_m, "fullTimeEmployees")),
            country=_str(profile_m, "country"),
            website=_str(profile_m, "website"),
            summary=_str(profile_m, "longBusinessSummary"),
        ),
        valuation=Valuation(
            market_cap=_num(price_m, "marketCap") or _num(summary_m, "marketCap"),
            enterprise_value=_num(stats_m, "enterpriseValue"),
            trailing_pe=_num(summary_m, "trailingPE"),
            forward_pe=_num(summary_m, "forwardPE") or _num(stats_m, "forwardPE"),
            peg_ratio=_num(stats_m, "pegRatio"),
            price_to_book=_num(stats_m, "priceToBook"),
            price_to_sales=_num(summary_m, "priceToSalesTrailing12Months"),
            ev_to_ebitda=_num(stats_m, "enterpriseToEbitda"),
            ev_to_revenue=_num(stats_m, "enterpriseToRevenue"),
        ),
        profitability=Profitability(
            return_on_equity=_num(financial_m, "returnOnEquity"),
            return_on_assets=_num(financial_m, "returnOnAssets"),
            profit_margin=_num(financial_m, "profitMargins") or _num(stats_m, "profitMargins"),
            gross_margin=_num(financial_m, "grossMargins"),
            operating_margin=_num(financial_m, "operatingMargins"),
            ebitda_margin=_num(financial_m, "ebitdaMargins"),
        ),
        per_share=PerShare(
            eps_trailing=_num(stats_m, "trailingEps"),
            eps_forward=_num(stats_m, "forwardEps"),
            book_value=_num(stats_m, "bookValue"),
            revenue_per_share=_num(financial_m, "revenuePerShare"),
        ),
        financial_health=FinancialHealth(
            total_cash=total_cash,
            total_debt=total_debt,
            net_debt=net_debt,
            debt_to_equity=_num(financial_m, "debtToEquity"),
            current_ratio=_num(financial_m, "currentRatio"),
            quick_ratio=_num(financial_m, "quickRatio"),
            operating_cash_flow=_num(financial_m, "operatingCashflow"),
            free_cash_flow=_num(financial_m, "freeCashflow"),
        ),
        growth=Growth(
            revenue_growth_yoy=_num(financial_m, "revenueGrowth") or _yoy(revenue_history),
            earnings_growth_yoy=_num(financial_m, "earningsGrowth") or _yoy(net_income_history),
            revenue_cagr_3y=_cagr(revenue_history, 3),
            revenue_cagr_5y=_cagr(revenue_history, 5),
            net_income_cagr_3y=_cagr(net_income_history, 3),
            free_cash_flow_cagr_3y=_cagr(fcf_history, 3),
            revenue_history=revenue_history,
            net_income_history=net_income_history,
        ),
        dividend=DividendInfo(
            rate=_num(summary_m, "dividendRate") or _num(summary_m, "trailingAnnualDividendRate"),
            yield_=_num(summary_m, "dividendYield"),
            payout_ratio=_num(summary_m, "payoutRatio"),
            five_year_avg_yield=_num(summary_m, "fiveYearAvgDividendYield"),
            ex_dividend_date=ex_dividend_date,
        ),
        market=MarketStats(
            beta=_num(summary_m, "beta") or _num(stats_m, "beta"),
            fifty_two_week_high=_num(summary_m, "fiftyTwoWeekHigh"),
            fifty_two_week_low=_num(summary_m, "fiftyTwoWeekLow"),
            fifty_day_average=_num(summary_m, "fiftyDayAverage"),
            two_hundred_day_average=_num(summary_m, "twoHundredDayAverage"),
            shares_outstanding=_num(stats_m, "sharesOutstanding"),
            float_shares=_num(stats_m, "floatShares"),
            average_volume=_num(summary_m, "averageVolume"),
        ),
    )


def _int(value: float | None) -> int | None:
    return int(value) if value is not None else None
