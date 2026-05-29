"""Schemas for technical analysis, signals, and market-wide screeners."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import Interval, RiskLevel, SignalType, TrendDirection


class MovingAverages(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sma_20: float | None = None
    sma_50: float | None = None
    sma_200: float | None = None
    ema_12: float | None = None
    ema_26: float | None = None


class MACDValue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    macd: float | None = None
    signal: float | None = None
    histogram: float | None = None


class BollingerBands(BaseModel):
    model_config = ConfigDict(extra="forbid")

    upper: float | None = None
    middle: float | None = None
    lower: float | None = None
    bandwidth: float | None = Field(default=None, description="(upper-lower)/middle.")
    percent_b: float | None = Field(default=None, description="Position of price within the bands [0,1].")


class SupportResistance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    support: list[float] = Field(default_factory=list)
    resistance: list[float] = Field(default_factory=list)
    pivot: float | None = None


class TrendInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    direction: TrendDirection
    strength: float = Field(ge=0.0, le=1.0, description="Normalised trend strength [0,1].")
    slope: float = Field(description="Slope of the linear regression of close prices.")


class VolumeAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    latest_volume: int
    average_volume: float
    relative_volume: float = Field(description="latest / average volume.")
    spike_detected: bool


class TechnicalIndicators(BaseModel):
    """The full technical-indicator bundle for a symbol."""

    model_config = ConfigDict(extra="forbid")

    last_price: float
    moving_averages: MovingAverages
    rsi_14: float | None = None
    macd: MACDValue
    bollinger_bands: BollingerBands
    atr_14: float | None = None
    annualized_volatility: float | None = None
    support_resistance: SupportResistance
    trend: TrendInfo
    volume: VolumeAnalysis
    sample_size: int = Field(description="Number of bars used in the computation.")
    interval: Interval


class SignalComponent(BaseModel):
    """One contributing factor in the composite signal."""

    model_config = ConfigDict(extra="forbid")

    name: str
    signal: SignalType
    weight: float
    rationale: str


class TradingSignal(BaseModel):
    """Composite trading signal with confidence and risk classification."""

    model_config = ConfigDict(extra="forbid")

    symbol: str
    signal: SignalType
    confidence: float = Field(ge=0.0, le=1.0)
    risk_level: RiskLevel
    score: float = Field(description="Net weighted score in the range [-1, 1].")
    trend: TrendDirection
    components: list[SignalComponent]
    interval: Interval
    evaluated_at: datetime


class MarketMover(BaseModel):
    """A single row in a market screener (gainers/losers/unusual volume)."""

    model_config = ConfigDict(extra="forbid")

    symbol: str
    price: float
    change: float | None = None
    change_percent: float | None = None
    volume: int | None = None
    relative_volume: float | None = None


class MarketSummary(BaseModel):
    """Aggregate snapshot of the tracked IDX universe."""

    model_config = ConfigDict(extra="forbid")

    universe_size: int
    evaluated: int
    advancers: int
    decliners: int
    unchanged: int
    average_change_percent: float | None = None
    is_market_open: bool
    top_gainers: list[MarketMover]
    top_losers: list[MarketMover]
