"""Backtesting simple long-only strategies on stored bars. Pure numpy, no I/O.

A strategy turns closing prices into a decision per bar: 1 to be invested, 0
to hold cash. The decision made at bar t's close is carried out at bar t+1's
close, so no trade uses a price it couldn't have known: there is no look-ahead
by construction. Fees are zero, as in the app; slippage is optional.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from . import indicators as ind
from .risk import max_drawdown

MAX_CURVE_POINTS = 200


class BacktestError(ValueError):
    """Unknown strategy or parameters it can't use."""


def _whole(params: dict, name: str, default: int, low: int, high: int) -> int:
    value = params.get(name, default)
    if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
        raise BacktestError(f"{name} must be a whole number from {low} to {high}")
    return value


def _number(params: dict, name: str, default: float, low: float, high: float) -> float:
    value = params.get(name, default)
    if not isinstance(value, int | float) or isinstance(value, bool) or not low <= value <= high:
        raise BacktestError(f"{name} must be a number from {low} to {high}")
    return float(value)


def buy_and_hold(closes: np.ndarray, params: dict) -> tuple[np.ndarray, dict]:
    return np.ones(closes.size), {}


def sma_crossover(closes: np.ndarray, params: dict) -> tuple[np.ndarray, dict]:
    """Invested while the fast moving average is above the slow one."""
    fast = _whole(params, "fast", 10, 2, 200)
    slow = _whole(params, "slow", 30, 3, 400)
    if fast >= slow:
        raise BacktestError("fast must be shorter than slow")
    quick, steady = ind.sma(closes, fast), ind.sma(closes, slow)
    with np.errstate(invalid="ignore"):
        decisions = np.where(quick > steady, 1.0, 0.0)  # NaN warm-up compares as False
    return decisions, {"fast": fast, "slow": slow}


def rsi_reversion(closes: np.ndarray, params: dict) -> tuple[np.ndarray, dict]:
    """Buy when RSI falls below buy_below; sell when it rises above sell_above."""
    period = _whole(params, "period", 14, 2, 100)
    buy_below = _number(params, "buy_below", 30, 1, 99)
    sell_above = _number(params, "sell_above", 70, 1, 99)
    if buy_below >= sell_above:
        raise BacktestError("buy_below must be lower than sell_above")
    rsi = ind.rsi(closes, period)
    decisions = np.zeros(closes.size)
    holding = 0.0
    for i, value in enumerate(rsi):
        if not np.isnan(value):
            if holding == 0 and value < buy_below:
                holding = 1.0
            elif holding == 1 and value > sell_above:
                holding = 0.0
        decisions[i] = holding
    return decisions, {"period": period, "buy_below": buy_below, "sell_above": sell_above}


STRATEGIES: dict[str, tuple[str, Callable[[np.ndarray, dict], tuple[np.ndarray, dict]]]] = {
    "buy_and_hold": ("Buy and hold", buy_and_hold),
    "sma_crossover": ("SMA crossover", sma_crossover),
    "rsi_reversion": ("RSI mean reversion", rsi_reversion),
}


@dataclass(frozen=True)
class Result:
    strategy: str
    params: dict
    total_return: float
    buy_and_hold_return: float
    max_drawdown: float
    trades: int
    winning_trades: int
    open_position: bool
    exposure: float
    equity: np.ndarray  # Value of 1.0 invested at the first execution, at each bar


def held_positions(decisions: np.ndarray) -> np.ndarray:
    """Position held over each interval (bar i-1 to bar i): the decision from bar i-2,
    carried out at bar i-1's close. Cash until the first decision is carried out."""
    held = np.zeros(decisions.size)
    held[2:] = decisions[:-2]
    return held


def run(closes, strategy: str, params: dict | None = None, slippage_bps: float = 0.0) -> Result:
    """Backtest a strategy on closing prices, oldest first."""
    closes = np.asarray(closes, dtype=float)
    if strategy not in STRATEGIES:
        raise BacktestError(f"Unknown strategy: {strategy}. Choose from {', '.join(STRATEGIES)}.")
    if closes.size < 3:
        raise BacktestError("Not enough price history to backtest.")
    if not 0 <= slippage_bps <= 100:
        raise BacktestError("slippage_bps must be from 0 to 100")
    decisions, used = STRATEGIES[strategy][1](closes, params or {})

    held = held_positions(decisions)
    after = np.r_[held[1:], held[-1]]  # Position after each bar's close
    cost = slippage_bps / 10_000 * np.abs(after - held)  # Paid on what changes hands
    # The run starts at bar 1's close, when the first decision can be carried out
    equity = np.empty(closes.size - 1)
    value = 1.0
    for j in range(1, closes.size):
        if held[j] > 0:
            value *= closes[j] / closes[j - 1]
        value *= 1 - cost[j]
        equity[j - 1] = value

    entries = np.flatnonzero(np.diff(held) > 0)  # Bought at the close of bar index
    exits = np.flatnonzero(np.diff(held) < 0)
    wins = sum(1 for buy, sell in zip(entries, exits, strict=False) if closes[sell] > closes[buy])
    drawdown, _, _ = max_drawdown(equity)
    return Result(
        strategy=strategy,
        params=used,
        total_return=float(equity[-1] - 1),
        buy_and_hold_return=float(closes[-1] / closes[1] - 1),
        max_drawdown=drawdown,
        trades=int(entries.size),
        winning_trades=wins,
        open_position=bool(held[-1] > 0),
        exposure=float(held[2:].mean()) if closes.size > 2 else 0.0,
        equity=equity,
    )


def curve(equity: np.ndarray, times: list[int]) -> list[list]:
    """The equity curve as [time, value] pairs, thinned to at most MAX_CURVE_POINTS."""
    step = max(1, int(np.ceil(equity.size / MAX_CURVE_POINTS)))
    picks = list(range(0, equity.size, step))
    if picks[-1] != equity.size - 1:
        picks.append(equity.size - 1)
    return [[times[i], round(float(equity[i]), 6)] for i in picks]
