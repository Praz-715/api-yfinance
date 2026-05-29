"""Schemas for fundamental analysis (valuation, profitability, health, growth)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CompanyProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    sector: str | None = None
    industry: str | None = None
    employees: int | None = None
    country: str | None = None
    website: str | None = None
    summary: str | None = None


class Valuation(BaseModel):
    """Valuation multiples."""

    model_config = ConfigDict(extra="forbid")

    market_cap: float | None = None
    enterprise_value: float | None = None
    trailing_pe: float | None = None
    forward_pe: float | None = None
    peg_ratio: float | None = None
    price_to_book: float | None = None
    price_to_sales: float | None = None
    ev_to_ebitda: float | None = None
    ev_to_revenue: float | None = None


class Profitability(BaseModel):
    """Return and margin ratios (decimal fractions, e.g. 0.23 = 23%)."""

    model_config = ConfigDict(extra="forbid")

    return_on_equity: float | None = None
    return_on_assets: float | None = None
    profit_margin: float | None = None
    gross_margin: float | None = None
    operating_margin: float | None = None
    ebitda_margin: float | None = None


class PerShare(BaseModel):
    model_config = ConfigDict(extra="forbid")

    eps_trailing: float | None = None
    eps_forward: float | None = None
    book_value: float | None = None
    revenue_per_share: float | None = None


class FinancialHealth(BaseModel):
    """Liquidity, leverage, and cash-generation metrics (values in issuer currency)."""

    model_config = ConfigDict(extra="forbid")

    total_cash: float | None = None
    total_debt: float | None = None
    net_debt: float | None = None
    debt_to_equity: float | None = None
    current_ratio: float | None = None
    quick_ratio: float | None = None
    operating_cash_flow: float | None = None
    free_cash_flow: float | None = None


class Growth(BaseModel):
    """Growth rates (decimal fractions) plus the underlying annual series."""

    model_config = ConfigDict(extra="forbid")

    revenue_growth_yoy: float | None = None
    earnings_growth_yoy: float | None = None
    revenue_cagr_3y: float | None = None
    revenue_cagr_5y: float | None = None
    net_income_cagr_3y: float | None = None
    free_cash_flow_cagr_3y: float | None = None
    revenue_history: list[float | None] = Field(default_factory=list, description="Oldest → newest annual revenue.")
    net_income_history: list[float | None] = Field(default_factory=list, description="Oldest → newest annual net income.")


class DividendInfo(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    rate: float | None = None
    yield_: float | None = Field(default=None, alias="yield")
    payout_ratio: float | None = None
    five_year_avg_yield: float | None = None
    ex_dividend_date: datetime | None = None


class MarketStats(BaseModel):
    model_config = ConfigDict(extra="forbid")

    beta: float | None = None
    fifty_two_week_high: float | None = None
    fifty_two_week_low: float | None = None
    fifty_day_average: float | None = None
    two_hundred_day_average: float | None = None
    shares_outstanding: float | None = None
    float_shares: float | None = None
    average_volume: float | None = None


class Fundamentals(BaseModel):
    """The complete fundamental snapshot for a symbol."""

    model_config = ConfigDict(extra="forbid")

    symbol: str
    currency: str
    profile: CompanyProfile
    valuation: Valuation
    profitability: Profitability
    per_share: PerShare
    financial_health: FinancialHealth
    growth: Growth
    dividend: DividendInfo
    market: MarketStats


class CompareRow(BaseModel):
    """A compact, comparison-friendly row of headline metrics."""

    model_config = ConfigDict(extra="forbid")

    symbol: str
    name: str | None = None
    sector: str | None = None
    market_cap: float | None = None
    trailing_pe: float | None = None
    forward_pe: float | None = None
    price_to_book: float | None = None
    peg_ratio: float | None = None
    return_on_equity: float | None = None
    return_on_assets: float | None = None
    profit_margin: float | None = None
    revenue_growth_yoy: float | None = None
    earnings_growth_yoy: float | None = None
    debt_to_equity: float | None = None
    dividend_yield: float | None = None
    beta: float | None = None
    error: str | None = Field(default=None, description="Populated if this symbol could not be resolved.")
