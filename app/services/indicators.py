"""Technical-indicator computations.

Pure functions over a pandas OHLCV ``DataFrame`` (UTC-indexed, columns
``open/high/low/close/volume``). Implementations follow standard definitions:

* RSI and ATR use Wilder's smoothing (``ewm(alpha=1/period)``).
* MACD uses 12/26 EMAs with a 9-period signal line.
* Bollinger Bands use a 20-period SMA with 2 standard deviations.
* Trend is a least-squares regression over the look-back window.

All scalar accessors collapse ``NaN`` to ``None`` so the JSON contract never
emits non-finite numbers.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from app.schemas.common import TrendDirection

# Trading periods per year for annualising volatility, keyed by interval.
PERIODS_PER_YEAR: dict[str, float] = {
    "1m": 252 * 6.5 * 60,
    "5m": 252 * 6.5 * 12,
    "15m": 252 * 6.5 * 4,
    "30m": 252 * 6.5 * 2,
    "1h": 252 * 6.5,
    "1d": 252.0,
    "1wk": 52.0,
    "1mo": 12.0,
}


def safe_float(value: object) -> float | None:
    """Return a finite ``float`` or ``None`` (filters NaN/inf/non-numeric)."""
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _last(series: pd.Series) -> float | None:
    cleaned = series.dropna()
    if cleaned.empty:
        return None
    return safe_float(cleaned.iloc[-1])


def sma(close: pd.Series, window: int) -> pd.Series:
    return close.rolling(window=window, min_periods=window).mean()


def ema(close: pd.Series, span: int) -> pd.Series:
    return close.ewm(span=span, adjust=False, min_periods=span).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    result = 100.0 - (100.0 / (1.0 + rs))
    # When average loss is zero the asset only rose: RSI saturates at 100.
    result = result.where(avg_loss != 0.0, 100.0)
    return result


def macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def bollinger_bands(
    close: pd.Series,
    window: int = 20,
    num_std: float = 2.0,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    middle = close.rolling(window=window, min_periods=window).mean()
    std = close.rolling(window=window, min_periods=window).std(ddof=0)
    upper = middle + num_std * std
    lower = middle - num_std * std
    return upper, middle, lower


def true_range(frame: pd.DataFrame) -> pd.Series:
    prev_close = frame["close"].shift(1)
    ranges = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - prev_close).abs(),
            (frame["low"] - prev_close).abs(),
        ],
        axis=1,
    )
    return ranges.max(axis=1)


def atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    tr = true_range(frame)
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def annualized_volatility(close: pd.Series, interval: str) -> float | None:
    returns = close.pct_change().dropna()
    if len(returns) < 2:
        return None
    periods = PERIODS_PER_YEAR.get(interval, 252.0)
    vol = float(returns.std(ddof=1) * math.sqrt(periods))
    return safe_float(vol)


def support_resistance(frame: pd.DataFrame) -> tuple[list[float], list[float], float | None]:
    """Classic floor-trader pivot levels derived from the last completed bar."""
    if frame.empty:
        return [], [], None
    last = frame.iloc[-1]
    high = safe_float(last["high"])
    low = safe_float(last["low"])
    close = safe_float(last["close"])
    if high is None or low is None or close is None:
        return [], [], None

    pivot = (high + low + close) / 3.0
    r1 = 2 * pivot - low
    s1 = 2 * pivot - high
    r2 = pivot + (high - low)
    s2 = pivot - (high - low)

    supports = sorted({round(v, 4) for v in (s1, s2) if v > 0}, reverse=True)
    resistances = sorted({round(v, 4) for v in (r1, r2) if v > 0})
    return supports, resistances, round(pivot, 4)


def detect_trend(close: pd.Series, window: int = 50) -> tuple[TrendDirection, float, float]:
    """Linear-regression trend over the trailing ``window`` closes.

    Returns ``(direction, strength, slope)`` where ``strength`` is the regression
    R² in ``[0, 1]`` and ``direction`` is decided by the total relative move
    across the window with a small dead-band classifying flat markets as sideways.
    """
    series = close.dropna()
    n = min(len(series), window)
    if n < 3:
        return TrendDirection.SIDEWAYS, 0.0, 0.0

    y = series.iloc[-n:].to_numpy(dtype="float64")
    x = np.arange(n, dtype="float64")
    slope, intercept = np.polyfit(x, y, 1)

    predicted = slope * x + intercept
    ss_res = float(np.sum((y - predicted) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r_squared = 0.0 if ss_tot == 0 else max(0.0, min(1.0, 1.0 - ss_res / ss_tot))

    mean_price = float(y.mean()) or 1.0
    relative_move = (slope * n) / mean_price  # total move over window, normalised

    if relative_move > 0.02:
        direction = TrendDirection.BULLISH
    elif relative_move < -0.02:
        direction = TrendDirection.BEARISH
    else:
        direction = TrendDirection.SIDEWAYS

    return direction, round(r_squared, 4), safe_float(slope) or 0.0


def volume_analysis(
    frame: pd.DataFrame,
    window: int = 20,
    spike_multiplier: float = 2.0,
) -> tuple[int, float, float, bool]:
    """Return ``(latest_volume, average_volume, relative_volume, spike_detected)``."""
    volume = frame["volume"].dropna()
    if volume.empty:
        return 0, 0.0, 0.0, False

    latest = int(volume.iloc[-1])
    lookback = volume.iloc[-(window + 1):-1] if len(volume) > 1 else volume
    average = float(lookback.mean()) if not lookback.empty else float(volume.mean())
    if not math.isfinite(average) or average <= 0:
        return latest, 0.0, 0.0, False

    relative = latest / average
    spike = relative >= spike_multiplier
    return latest, round(average, 2), round(relative, 4), bool(spike)
