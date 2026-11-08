"""Portfolio risk metrics. Pure numpy, no I/O."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np

Z_95 = 1.6448536269514722  # Standard normal quantile at 95%
PDF_Z_95 = 0.10313564037537128  # Standard normal density at Z_95


def aligned_returns(
    closes: Mapping[str, Sequence[tuple[int, float]]],
) -> tuple[list[str], np.ndarray, np.ndarray]:
    """Log returns on the bar times every ticker shares.

    closes maps ticker -> [(time, close)] in time order. Returns the tickers (in
    the given order, minus any without at least two shared bars), the shared
    times after the first, and a (times x tickers) matrix of returns.
    """
    tickers = [t for t in closes if len(closes[t]) >= 2]
    if not tickers:
        return [], np.array([]), np.empty((0, 0))
    shared = set.intersection(*(set(time for time, _ in closes[t]) for t in tickers))
    times = np.array(sorted(shared))
    if times.size < 2:
        return tickers, np.array([]), np.empty((0, len(tickers)))
    columns = []
    for ticker in tickers:
        by_time = dict(closes[ticker])
        columns.append(np.diff(np.log([by_time[time] for time in times])))
    return tickers, times[1:], np.column_stack(columns)


def correlation_matrix(returns: np.ndarray) -> np.ndarray:
    """Pairwise correlation of the columns. A column that never moves correlates as 0."""
    k = returns.shape[1]
    if returns.shape[0] < 2:
        return np.full((k, k), np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        corr = np.corrcoef(returns, rowvar=False).reshape(k, k)
    corr = np.nan_to_num(corr, nan=0.0)
    np.fill_diagonal(corr, 1.0)
    return corr


def beta(asset: np.ndarray, benchmark: np.ndarray) -> float:
    """Sensitivity of the asset's returns to the benchmark's; NaN if the benchmark is flat."""
    if asset.size < 2:
        return float("nan")
    variance = benchmark.var(ddof=1)
    if variance == 0:
        return float("nan")
    return float(np.cov(asset, benchmark, ddof=1)[0, 1] / variance)


def historical_var_es(returns: np.ndarray, level: float = 0.95, scale: float = 1.0):
    """Value at Risk and expected shortfall from the empirical return distribution.

    Both are positive fractions of value lost. scale stretches one-bar figures to
    a longer horizon by the square root of time.
    """
    if returns.size == 0:
        return float("nan"), float("nan")
    cutoff = np.quantile(returns, 1 - level)
    tail = returns[returns <= cutoff]
    return float(-cutoff * scale), float(-tail.mean() * scale)


def parametric_var_es(std: float, scale: float = 1.0):
    """95% Value at Risk and expected shortfall for normal returns with zero mean.

    The mean is left out: estimated from days or weeks of bars it is mostly noise,
    and over a day it is tiny next to the spread.
    """
    sigma = std * scale
    return float(Z_95 * sigma), float(PDF_Z_95 / 0.05 * sigma)


def herfindahl(weights: Sequence[float]) -> float:
    """Concentration of the invested weights: 1 for one position, 1/n for n equal ones."""
    w = np.asarray(weights, dtype=float)
    total = w.sum()
    if total <= 0:
        return float("nan")
    return float(((w / total) ** 2).sum())


def max_drawdown(values: Sequence[float]) -> tuple[float, int, int]:
    """Largest fall from a peak, as a positive fraction, with peak and trough indexes."""
    v = np.asarray(values, dtype=float)
    if v.size == 0:
        return 0.0, 0, 0
    peaks = np.maximum.accumulate(v)
    drawdowns = 1 - v / peaks
    trough = int(drawdowns.argmax())
    peak = int(v[: trough + 1].argmax())
    return float(drawdowns[trough]), peak, trough


def sharpe_ratio(values: Sequence[float], seconds: Sequence[float], seconds_per_year: float):
    """Annualized Sharpe ratio (risk-free rate 0) from irregularly spaced values.

    Return and variance are estimated per second of elapsed time, so uneven
    spacing (snapshots taken after trades) doesn't skew them. NaN if flat.
    """
    v = np.asarray(values, dtype=float)
    t = np.asarray(seconds, dtype=float)
    if v.size < 3:
        return float("nan")
    r = np.diff(np.log(v))
    dt = np.diff(t)
    keep = dt > 0
    r, dt = r[keep], dt[keep]
    if dt.sum() <= 0:
        return float("nan")
    rate = r.sum() / dt.sum()
    variance = ((r - rate * dt) ** 2).sum() / dt.sum()
    if variance <= 0:
        return float("nan")
    return float(rate * seconds_per_year / np.sqrt(variance * seconds_per_year))
