"""Unit tests for the quantitative indicator and signal engine."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.schemas.common import Interval, RiskLevel, SignalType, TrendDirection
from app.services import analysis as analysis_service
from app.services import indicators as ind
from tests.conftest import build_synthetic_chart


def _series(values: list[float]) -> pd.Series:
    return pd.Series(values, dtype="float64")


def test_sma_matches_manual_mean():
    s = _series([1, 2, 3, 4, 5])
    result = ind.sma(s, 3)
    assert result.iloc[-1] == 4.0  # mean(3,4,5)
    assert pd.isna(result.iloc[0])  # insufficient window


def test_rsi_all_gains_saturates_to_100():
    s = _series([float(i) for i in range(1, 40)])
    rsi = ind.rsi(s, 14).dropna()
    assert rsi.iloc[-1] == 100.0


def test_rsi_bounds():
    s = _series(list(np.cos(np.linspace(0, 20, 100)) * 50 + 100))
    rsi = ind.rsi(s, 14).dropna()
    assert rsi.between(0, 100).all()


def test_macd_components_length():
    s = _series(list(np.linspace(100, 200, 80)))
    macd_line, signal_line, hist = ind.macd(s)
    assert len(macd_line) == len(signal_line) == len(hist) == 80


def test_atr_is_non_negative():
    chart = build_synthetic_chart(n=100)
    atr = ind.atr(chart.frame).dropna()
    assert (atr >= 0).all()


def test_annualized_volatility_positive():
    chart = build_synthetic_chart(n=120)
    vol = ind.annualized_volatility(chart.frame["close"], "1d")
    assert vol is not None and vol >= 0


def test_detect_trend_uptrend_is_bullish():
    s = _series(list(np.linspace(100, 200, 60)))
    direction, strength, slope = ind.detect_trend(s)
    assert direction is TrendDirection.BULLISH
    assert slope > 0
    assert 0.0 <= strength <= 1.0


def test_volume_spike_detected():
    chart = build_synthetic_chart(n=60)
    latest, average, relative, spike = ind.volume_analysis(chart.frame)
    assert spike is True
    assert relative > 2.0


def test_safe_float_filters_nan_inf():
    assert ind.safe_float(float("nan")) is None
    assert ind.safe_float(float("inf")) is None
    assert ind.safe_float("3.5") == 3.5


def test_compute_technical_shapes():
    chart = build_synthetic_chart(n=300)
    tech = analysis_service.compute_technical(chart, Interval.D1)
    assert tech.last_price > 0
    assert tech.rsi_14 is None or 0 <= tech.rsi_14 <= 100
    assert tech.sample_size == 300
    assert tech.support_resistance.pivot is not None


def test_compute_signal_is_well_formed():
    chart = build_synthetic_chart(n=300)
    signal = analysis_service.compute_signal(chart, Interval.D1)
    assert isinstance(signal.signal, SignalType)
    assert 0.0 <= signal.confidence <= 1.0
    assert -1.0 <= signal.score <= 1.0
    assert signal.risk_level in set(RiskLevel)
    assert signal.components  # at least one contributing factor
