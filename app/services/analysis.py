"""Analysis service: assembles indicator bundles and composite trading signals.

The signal engine combines five independent technical factors (RSI, MACD,
moving-average structure, Bollinger position, regression trend) into a single
weighted score in ``[-1, 1]``, which is mapped to a discrete signal together with
a confidence value and a volatility-derived risk classification. The logic is
fully deterministic and explainable — every contributing factor is returned in
``components`` with its own sub-signal, weight, and rationale.
"""

from __future__ import annotations

import math

from app.core.exceptions import InsufficientDataError
from app.schemas.analysis import (
    BollingerBands,
    MACDValue,
    MovingAverages,
    SignalComponent,
    SupportResistance,
    TechnicalIndicators,
    TradingSignal,
    TrendInfo,
    VolumeAnalysis,
)
from app.schemas.common import Interval, RiskLevel, SignalType, TrendDirection
from app.services import indicators as ind
from app.services.providers.base import ChartResult
from app.utils.timeutils import now_utc

# Relative weights of each factor in the composite score (sum to 1.0).
_WEIGHTS = {
    "rsi": 0.20,
    "macd": 0.25,
    "moving_average": 0.25,
    "bollinger": 0.15,
    "trend": 0.15,
}


def _score_to_signal(score: float) -> SignalType:
    if score >= 0.5:
        return SignalType.STRONG_BUY
    if score >= 0.15:
        return SignalType.BUY
    if score <= -0.5:
        return SignalType.STRONG_SELL
    if score <= -0.15:
        return SignalType.SELL
    return SignalType.HOLD


def _clip(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def compute_technical(chart: ChartResult, interval: Interval) -> TechnicalIndicators:
    """Compute the full indicator bundle for ``chart``."""
    frame = chart.frame
    close = frame["close"]
    if close.dropna().shape[0] < 2:
        raise InsufficientDataError()

    last_price = ind.safe_float(close.dropna().iloc[-1])
    if last_price is None:
        raise InsufficientDataError()

    macd_line, signal_line, histogram = ind.macd(close)
    upper, middle, lower = ind.bollinger_bands(close)

    upper_v = ind._last(upper)
    middle_v = ind._last(middle)
    lower_v = ind._last(lower)
    bandwidth = percent_b = None
    if None not in (upper_v, middle_v, lower_v) and middle_v:
        bandwidth = round((upper_v - lower_v) / middle_v, 6)
        span = upper_v - lower_v
        if span:
            percent_b = round((last_price - lower_v) / span, 6)

    supports, resistances, pivot = ind.support_resistance(frame)
    direction, strength, slope = ind.detect_trend(close)
    latest_vol, avg_vol, rel_vol, spike = ind.volume_analysis(frame)

    return TechnicalIndicators(
        last_price=round(last_price, 4),
        moving_averages=MovingAverages(
            sma_20=_round(ind._last(ind.sma(close, 20))),
            sma_50=_round(ind._last(ind.sma(close, 50))),
            sma_200=_round(ind._last(ind.sma(close, 200))),
            ema_12=_round(ind._last(ind.ema(close, 12))),
            ema_26=_round(ind._last(ind.ema(close, 26))),
        ),
        rsi_14=_round(ind._last(ind.rsi(close)), 4),
        macd=MACDValue(
            macd=_round(ind._last(macd_line), 6),
            signal=_round(ind._last(signal_line), 6),
            histogram=_round(ind._last(histogram), 6),
        ),
        bollinger_bands=BollingerBands(
            upper=_round(upper_v),
            middle=_round(middle_v),
            lower=_round(lower_v),
            bandwidth=bandwidth,
            percent_b=percent_b,
        ),
        atr_14=_round(ind._last(ind.atr(frame)), 4),
        annualized_volatility=_round(ind.annualized_volatility(close, interval.value), 6),
        support_resistance=SupportResistance(support=supports, resistance=resistances, pivot=pivot),
        trend=TrendInfo(direction=direction, strength=strength, slope=slope),
        volume=VolumeAnalysis(
            latest_volume=latest_vol,
            average_volume=avg_vol,
            relative_volume=rel_vol,
            spike_detected=spike,
        ),
        sample_size=int(close.dropna().shape[0]),
        interval=interval,
    )


def compute_signal(chart: ChartResult, interval: Interval) -> TradingSignal:
    """Derive the composite trading signal from the indicator bundle."""
    tech = compute_technical(chart, interval)
    components: list[SignalComponent] = []
    # Maps each included component name to its raw contribution in [-1, 1].
    contributions: dict[str, float] = {}

    def add(name: str, contrib: float, rationale: str) -> None:
        contributions[name] = contrib
        components.append(
            SignalComponent(
                name=name,
                signal=_score_to_signal(contrib),
                weight=_WEIGHTS[name],
                rationale=rationale,
            )
        )

    # 1) RSI: oversold favours buying, overbought favours selling.
    if tech.rsi_14 is not None:
        if tech.rsi_14 <= 30:
            rsi_contrib = 1.0
        elif tech.rsi_14 >= 70:
            rsi_contrib = -1.0
        else:
            rsi_contrib = _clip((50.0 - tech.rsi_14) / 20.0)
        add("rsi", rsi_contrib, f"RSI(14) = {tech.rsi_14:.1f}")

    # 2) MACD: histogram sign and magnitude relative to price.
    if tech.macd.histogram is not None and tech.last_price:
        normalized = tech.macd.histogram / (tech.last_price * 0.01)  # per 1% of price
        add("macd", _clip(math.tanh(normalized)), f"MACD histogram = {tech.macd.histogram:.4f}")

    # 3) Moving-average structure: price vs SMA50, plus golden/death alignment.
    sma50 = tech.moving_averages.sma_50
    sma200 = tech.moving_averages.sma_200
    if sma50:
        ma_contrib = _clip((tech.last_price - sma50) / sma50 * 5.0)
        if sma200:
            ma_contrib = _clip(ma_contrib + (0.3 if sma50 > sma200 else -0.3))
        add(
            "moving_average",
            ma_contrib,
            "Price above SMA50" if tech.last_price > sma50 else "Price below SMA50",
        )

    # 4) Bollinger %b: below lower band oversold, above upper band overbought.
    if tech.bollinger_bands.percent_b is not None:
        pb = tech.bollinger_bands.percent_b
        add("bollinger", _clip((0.5 - pb) * 2.0), f"Bollinger %b = {pb:.2f}")

    # 5) Regression trend, weighted by its goodness of fit (strength).
    if tech.trend.direction is TrendDirection.BULLISH:
        trend_contrib = tech.trend.strength
    elif tech.trend.direction is TrendDirection.BEARISH:
        trend_contrib = -tech.trend.strength
    else:
        trend_contrib = 0.0
    add("trend", trend_contrib, f"{tech.trend.direction.value} (R²={tech.trend.strength:.2f})")

    score = _clip(sum(c.weight * contributions[c.name] for c in components))
    confidence = round(min(1.0, abs(score) * 0.7 + tech.trend.strength * 0.3), 4)
    risk = _risk_level(tech.annualized_volatility, tech.atr_14, tech.last_price)

    return TradingSignal(
        symbol=chart.meta.symbol,
        signal=_score_to_signal(score),
        confidence=confidence,
        risk_level=risk,
        score=round(score, 4),
        trend=tech.trend.direction,
        components=components,
        interval=interval,
        evaluated_at=now_utc(),
    )


def _risk_level(vol: float | None, atr: float | None, price: float) -> RiskLevel:
    """Classify risk primarily from annualised volatility, falling back to ATR%."""
    if vol is not None:
        if vol < 0.25:
            return RiskLevel.LOW
        if vol <= 0.45:
            return RiskLevel.MEDIUM
        return RiskLevel.HIGH
    if atr is not None and price:
        atr_pct = atr / price
        if atr_pct < 0.015:
            return RiskLevel.LOW
        if atr_pct <= 0.03:
            return RiskLevel.MEDIUM
        return RiskLevel.HIGH
    return RiskLevel.MEDIUM


def _round(value: float | None, digits: int = 4) -> float | None:
    return round(value, digits) if value is not None else None
