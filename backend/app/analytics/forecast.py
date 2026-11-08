"""Monte Carlo forecasts for a ticker or the portfolio, as ranges, not targets.

Volatility and correlation are estimated from one-minute log returns: a minute
is a minute of trading time both in the simulator and in market hours, so one
estimate serves every data source. Those returns already contain the jumps, so
no separate jump model is added; over a horizon of many minutes their sum is
close to normal. There is no expected return: drift estimated from days or
weeks of prices is mostly noise, and it would make the fan look surer than it
is. Each price path is a martingale, so its mean stays at today's price.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from .risk import aligned_returns

PERCENTILES = (5, 25, 50, 75, 95)
DEFAULT_PATHS = 5000
CHECKPOINTS = 24
MINUTE = 60


@dataclass(frozen=True)
class Horizon:
    label: str
    wall_seconds: int  # How far ahead on the clock
    real_trading_seconds: int  # How much trading that is when markets keep hours


# The simulator trades around the clock, so its trading time equals wall time.
# Real markets trade about 6.5 hours a day, five days a week.
HORIZONS: dict[str, Horizon] = {
    "1h": Horizon("1 hour", 3600, 3600),
    "1d": Horizon("1 day", 86400, 23400),
    "1w": Horizon("1 week", 7 * 86400, 5 * 23400),
}
SIMULATED_MODES = ("simulated", "seeded")


def trading_seconds(horizon: str, mode: str) -> int:
    h = HORIZONS[horizon]
    return h.wall_seconds if mode in SIMULATED_MODES else h.real_trading_seconds


@dataclass(frozen=True)
class Estimate:
    tickers: list[str]
    covariance_per_second: np.ndarray  # Of log returns, per second of trading
    returns: int


def estimate(closes: Mapping[str, Sequence[tuple[int, float]]]) -> Estimate:
    """Covariance of one-minute log returns on shared bars, scaled to one second."""
    tickers, times, returns = aligned_returns(closes)
    if times.size < 2:
        return Estimate(tickers, np.empty((0, 0)), int(times.size))
    covariance = np.atleast_2d(np.cov(returns, rowvar=False, ddof=1)) / MINUTE
    return Estimate(tickers, covariance, int(times.size))


def simulate(
    prices: np.ndarray,
    covariance_per_second: np.ndarray,
    seconds: float,
    rng: np.random.Generator,
    paths: int = DEFAULT_PATHS,
    checkpoints: int = CHECKPOINTS,
) -> np.ndarray:
    """Correlated price paths with no expected return.

    Returns shape (paths, checkpoints, tickers): prices at evenly spaced times
    up to the horizon, the last at the horizon itself.
    """
    k = prices.size
    dt = seconds / checkpoints
    variance = np.diag(covariance_per_second)
    # A small ridge keeps the factorization stable when two tickers move together exactly
    chol = np.linalg.cholesky(covariance_per_second * dt + np.eye(k) * 1e-18)
    shocks = rng.standard_normal((paths, checkpoints, k)) @ chol.T
    log_steps = shocks - 0.5 * variance * dt  # Ito: keeps each price's mean unchanged
    return prices * np.exp(np.cumsum(log_steps, axis=1))


def summarize(values: np.ndarray, current: float, level: float | None = None) -> dict:
    """Percentile bands at each checkpoint, plus loss and level probabilities at the end.

    values has shape (paths, checkpoints).
    """
    bands = np.percentile(values, PERCENTILES, axis=0)  # (len(PERCENTILES), checkpoints)
    final = values[:, -1]
    result = {
        "bands": {
            f"p{p}": [round(float(v), 2) for v in bands[i]] for i, p in enumerate(PERCENTILES)
        },
        "probability_of_loss": round(float((final < current).mean()), 4),
        "expected_shortfall_5": round(
            float(current - final[final <= np.percentile(final, 5)].mean()), 2
        ),
    }
    if level is not None:
        above = level >= current
        reached = values.max(axis=1) >= level if above else values.min(axis=1) <= level
        ends = final >= level if above else final <= level
        result["level"] = {
            "price": level,
            "direction": "above" if above else "below",
            "probability_at_horizon": round(float(ends.mean()), 4),
            "probability_of_touching": round(float(reached.mean()), 4),
        }
    return result


def annualized_volatility(variance_per_second: float, seconds_per_year: float) -> float:
    return math.sqrt(max(variance_per_second, 0.0) * seconds_per_year)
