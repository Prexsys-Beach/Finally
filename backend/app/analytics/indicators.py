"""Technical indicators. Pure numpy, no I/O.

Every function is causal: the value at index i uses inputs up to i only, so
nothing looks ahead. Outputs have the input's length, with NaN until a value is
defined (the warm-up).
"""

from __future__ import annotations

import numpy as np

# Bars per trading year. One-minute bars count a 6.5-hour session, which is also
# how the simulator's clock runs; daily bars count trading days.
PERIODS_PER_YEAR = {"1m": 252 * 390, "1d": 252}
BARS_PER_TRADING_DAY = {"1m": 390, "1d": 1}


def _array(values) -> np.ndarray:
    return np.asarray(values, dtype=float)


def log_returns(closes) -> np.ndarray:
    """Log return of each bar from the one before; one shorter than the input."""
    closes = _array(closes)
    return np.diff(np.log(closes)) if closes.size > 1 else np.array([])


def sma(values, n: int) -> np.ndarray:
    values = _array(values)
    out = np.full(values.size, np.nan)
    if values.size >= n:
        total = np.cumsum(np.insert(values, 0, 0.0))
        out[n - 1 :] = (total[n:] - total[:-n]) / n
    return out


def ema(values, n: int) -> np.ndarray:
    """Exponential moving average, seeded with the SMA of the first n values.

    Leading NaNs (another indicator's warm-up) are skipped.
    """
    values = _array(values)
    out = np.full(values.size, np.nan)
    valid = np.flatnonzero(~np.isnan(values))
    if valid.size == 0:
        return out
    first = valid[0]
    if values.size - first < n:
        return out
    alpha = 2 / (n + 1)
    seed = first + n - 1
    out[seed] = values[first : seed + 1].mean()
    for i in range(seed + 1, values.size):
        out[i] = alpha * values[i] + (1 - alpha) * out[i - 1]
    return out


def _wilder(values: np.ndarray, n: int, start: int) -> np.ndarray:
    """Wilder smoothing: mean of the first n values from start, then (prev*(n-1)+x)/n."""
    out = np.full(values.size, np.nan)
    if values.size - start < n:
        return out
    seed = start + n - 1
    out[seed] = values[start : seed + 1].mean()
    for i in range(seed + 1, values.size):
        out[i] = (out[i - 1] * (n - 1) + values[i]) / n
    return out


def rsi(closes, n: int = 14) -> np.ndarray:
    """Relative Strength Index (Wilder). 100 when there were no losses; 50 when flat."""
    closes = _array(closes)
    out = np.full(closes.size, np.nan)
    if closes.size <= n:
        return out
    deltas = np.insert(np.diff(closes), 0, np.nan)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = _wilder(gains, n, start=1)
    avg_loss = _wilder(losses, n, start=1)
    defined = ~np.isnan(avg_gain)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = avg_gain / avg_loss
        values = 100 - 100 / (1 + rs)
    values = np.where(avg_loss == 0, np.where(avg_gain == 0, 50.0, 100.0), values)
    out[defined] = values[defined]
    return out


def macd(closes, fast: int = 12, slow: int = 26, signal: int = 9):
    """MACD line, signal line and histogram."""
    closes = _array(closes)
    line = ema(closes, fast) - ema(closes, slow)
    signal_line = ema(line, signal)
    return line, signal_line, line - signal_line


def bollinger(closes, n: int = 20, k: float = 2.0):
    """Middle (SMA), upper and lower bands, k population standard deviations out."""
    closes = _array(closes)
    middle = sma(closes, n)
    spread = np.full(closes.size, np.nan)
    if closes.size >= n:
        windows = np.lib.stride_tricks.sliding_window_view(closes, n)
        spread[n - 1 :] = windows.std(axis=1)
    return middle, middle + k * spread, middle - k * spread


def atr(high, low, close, n: int = 14) -> np.ndarray:
    """Average True Range (Wilder)."""
    high, low, close = _array(high), _array(low), _array(close)
    if close.size == 0:
        return np.array([])
    previous = np.insert(close[:-1], 0, np.nan)
    true_range = np.nanmax(
        np.vstack([high - low, np.abs(high - previous), np.abs(low - previous)]), axis=0
    )
    return _wilder(true_range, n, start=0)


def realized_volatility(closes, timeframe: str) -> float:
    """Annualized standard deviation of log returns; NaN with fewer than 2 returns."""
    returns = log_returns(closes)
    if returns.size < 2:
        return float("nan")
    return float(returns.std(ddof=1) * np.sqrt(PERIODS_PER_YEAR[timeframe]))
