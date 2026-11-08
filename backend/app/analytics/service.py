"""Analytics over stored bars and the live portfolio, shaped for the API and the assistant.

Bars come from bars_for_analysis(), so synthetic history drops out once a ticker
has enough real history for the user's cutoff setting. Every result says how many
bars of each origin it used.
"""

from __future__ import annotations

import math
import sqlite3
from collections import Counter
from datetime import datetime

import numpy as np

from ..db import DEFAULT_USER_ID
from ..market import PriceCache
from ..market.bars import Bar, bars_for_analysis
from ..market.simulator import GBMSimulator
from ..portfolio import get_portfolio
from ..settings import synthetic_cutoff_days
from ..watchlist import get_watchlist
from . import indicators as ind
from . import risk

INDICATOR_WARMUP = 50  # Bars before the first EMA(50) value
RISK_LOOKBACK = {"1m": 1440, "1d": 252}  # A calendar day of minutes; a trading year
MIN_RISK_RETURNS = 20
MIN_PERFORMANCE_SECONDS = 86400
MIN_PERFORMANCE_SNAPSHOTS = 30
RSI_OVERBOUGHT, RSI_OVERSOLD = 70, 30


def _number(value, digits: int = 6):
    """JSON-safe float: None for NaN or infinity."""
    if value is None:
        return None
    value = float(value)
    return round(value, digits) if math.isfinite(value) else None


def _series(values: np.ndarray, digits: int = 4) -> list:
    return [_number(v, digits) for v in values]


def _origins(bars: list[Bar]) -> dict[str, int]:
    return dict(Counter(bar.origin for bar in bars))


def _bars(conn, ticker, timeframe, limit, retention_days) -> list[Bar]:
    cutoff = synthetic_cutoff_days(conn)
    return bars_for_analysis(conn, ticker, timeframe, limit, cutoff, retention_days)


def _signals(close, sma, upper, lower, rsi, histogram) -> dict:
    def known(*values):
        return all(v is not None and math.isfinite(v) for v in values)

    return {
        "rsi": None
        if not known(rsi)
        else "overbought"
        if rsi > RSI_OVERBOUGHT
        else "oversold"
        if rsi < RSI_OVERSOLD
        else "neutral",
        "bollinger": None
        if not known(upper, lower)
        else "above"
        if close > upper
        else "below"
        if close < lower
        else "inside",
        "trend": None if not known(sma) else "above_sma" if close > sma else "below_sma",
        "macd": None if not known(histogram) else "bullish" if histogram > 0 else "bearish",
    }


def ticker_analytics(
    conn: sqlite3.Connection, ticker: str, timeframe: str, limit: int, retention_days: float
) -> dict:
    """Indicator series for the last `limit` bars, plus the latest values and signals.

    Extra bars before the window warm the indicators up, so the first returned
    point is already a real value when enough history exists.
    """
    bars = _bars(conn, ticker, timeframe, limit + INDICATOR_WARMUP, retention_days)
    result = {
        "ticker": ticker,
        "timeframe": timeframe,
        "bars": len(bars),
        "origins": _origins(bars),
    }
    if not bars:
        return result | {"latest": None, "signals": None, "series": None}

    close = np.array([b.close for b in bars])
    high = np.array([b.high for b in bars])
    low = np.array([b.low for b in bars])
    sma = ind.sma(close, 20)
    ema = ind.ema(close, 50)
    middle, upper, lower = ind.bollinger(close, 20, 2)
    rsi = ind.rsi(close, 14)
    macd, signal, histogram = ind.macd(close)
    atr = ind.atr(high, low, close, 14)
    window = slice(-limit, None)

    latest = {
        "time": bars[-1].start_ts,
        "close": _number(close[-1], 4),
        "sma_20": _number(sma[-1], 4),
        "ema_50": _number(ema[-1], 4),
        "bollinger_upper": _number(upper[-1], 4),
        "bollinger_middle": _number(middle[-1], 4),
        "bollinger_lower": _number(lower[-1], 4),
        "rsi_14": _number(rsi[-1], 2),
        "macd": _number(macd[-1], 4),
        "macd_signal": _number(signal[-1], 4),
        "macd_histogram": _number(histogram[-1], 4),
        "atr_14": _number(atr[-1], 4),
        "volatility": _number(ind.realized_volatility(close[window], timeframe), 4),
    }
    return result | {
        "latest": latest,
        "signals": _signals(close[-1], sma[-1], upper[-1], lower[-1], rsi[-1], histogram[-1]),
        "series": {
            "time": [b.start_ts for b in bars[window]],
            "sma_20": _series(sma[window]),
            "ema_50": _series(ema[window]),
            "bollinger_upper": _series(upper[window]),
            "bollinger_lower": _series(lower[window]),
            "rsi_14": _series(rsi[window], 2),
            "macd": _series(macd[window]),
            "macd_signal": _series(signal[window]),
            "macd_histogram": _series(histogram[window]),
        },
    }


def _figure(fraction: float, total_value: float) -> dict | None:
    if not math.isfinite(fraction):
        return None
    return {"percent": round(fraction * 100, 4), "amount": round(fraction * total_value, 2)}


def _performance(conn: sqlite3.Connection) -> dict:
    """Max drawdown and Sharpe ratio from portfolio snapshots.

    The Sharpe ratio counts elapsed time as trading time, which is how the
    simulator runs; with real data it understates returns and volatility alike.
    """
    rows = conn.execute(
        """
        SELECT total_value, recorded_at FROM portfolio_snapshots
        WHERE user_id = ? ORDER BY recorded_at
        """,
        (DEFAULT_USER_ID,),
    ).fetchall()
    values = [row["total_value"] for row in rows if row["total_value"] > 0]
    seconds = [
        datetime.fromisoformat(row["recorded_at"]).timestamp()
        for row in rows
        if row["total_value"] > 0
    ]
    if not values:
        return {"max_drawdown": None, "sharpe": None, "note": "No portfolio history yet."}
    drawdown, peak, trough = risk.max_drawdown(values)
    result = {
        "max_drawdown": {
            "percent": round(drawdown * 100, 4),
            "peak_at": rows[peak]["recorded_at"],
            "trough_at": rows[trough]["recorded_at"],
        },
        "sharpe": None,
        "note": None,
    }
    span = seconds[-1] - seconds[0]
    if span < MIN_PERFORMANCE_SECONDS or len(values) < MIN_PERFORMANCE_SNAPSHOTS:
        result["note"] = "The Sharpe ratio needs at least a day of portfolio history."
        return result
    sharpe = risk.sharpe_ratio(values, seconds, GBMSimulator.TRADING_SECONDS_PER_YEAR)
    result["sharpe"] = _number(sharpe, 3)
    return result


def portfolio_analytics(
    conn: sqlite3.Connection, cache: PriceCache, timeframe: str, retention_days: float
) -> dict:
    """Risk of the current positions, measured on the history of held and watched tickers.

    Weights are shares of total value including cash, so cash dampens portfolio
    volatility, beta and VaR. VaR and expected shortfall are for one trading day
    at 95%; one-minute figures are scaled up by the square root of time.
    """
    portfolio = get_portfolio(conn, cache)
    total = portfolio["total_value"]
    held = {p["ticker"]: p for p in portfolio["positions"]}
    watched = [entry["ticker"] for entry in get_watchlist(conn, cache)]
    universe = sorted(set(held) | set(watched))

    used: Counter = Counter()
    closes = {}
    for ticker in universe:
        bars = _bars(conn, ticker, timeframe, RISK_LOOKBACK[timeframe] + 1, retention_days)
        used.update(bar.origin for bar in bars)
        closes[ticker] = [(bar.start_ts, bar.close) for bar in bars]
    tickers, times, returns = risk.aligned_returns(closes)

    notes: list[str] = []
    missing = sorted(set(universe) - set(tickers))
    if missing:
        notes.append(f"No history yet for {', '.join(missing)}.")
    enough = times.size >= MIN_RISK_RETURNS
    if not enough:
        notes.append("Not enough shared history to measure risk yet.")

    result: dict = {
        "timeframe": timeframe,
        "returns": int(times.size),
        "as_of": int(times[-1]) if times.size else None,
        "origins": dict(used),
        "total_value": total,
        "cash_weight": _number(portfolio["cash_balance"] / total, 6) if total else None,
        "benchmark": f"Equal-weighted watchlist ({len(watched)} tickers)",
        "correlation": {
            "tickers": tickers,
            "matrix": [[_number(v, 4) for v in row] for row in risk.correlation_matrix(returns)]
            if enough
            else None,
        },
        "volatility": None,
        "beta": None,
        "value_at_risk": None,
        "expected_shortfall": None,
        "positions": [],
        "concentration": None,
        "performance": _performance(conn),
        "notes": notes,
    }

    if not held:
        notes.append("No positions: portfolio risk appears once you hold shares.")
        return result

    market_values = {t: p["market_value"] or p["cost_basis"] for t, p in held.items()}
    top = max(market_values, key=market_values.get)
    invested = list(market_values.values())
    result["concentration"] = {
        "top": {"ticker": top, "weight": _number(market_values[top] / total, 6)},
        "herfindahl": _number(risk.herfindahl(invested), 6),
        "effective_positions": _number(1 / risk.herfindahl(invested), 3),
    }
    if not enough:
        return result

    column = {ticker: i for i, ticker in enumerate(tickers)}
    measured = [t for t in held if t in column]
    unmeasured = sorted(set(held) - set(measured))
    if unmeasured:
        notes.append(f"Left out of portfolio risk for lack of history: {', '.join(unmeasured)}.")
    if not measured:
        return result
    weights = np.array([market_values[t] / total for t in measured])
    portfolio_returns = returns[:, [column[t] for t in measured]] @ weights
    bench_columns = [column[t] for t in watched if t in column]
    benchmark = returns[:, bench_columns].mean(axis=1) if bench_columns else None

    per_year = np.sqrt(ind.PERIODS_PER_YEAR[timeframe])
    to_day = np.sqrt(ind.BARS_PER_TRADING_DAY[timeframe])
    std = float(portfolio_returns.std(ddof=1))
    hist_var, hist_es = risk.historical_var_es(portfolio_returns, scale=to_day)
    param_var, param_es = risk.parametric_var_es(std, scale=to_day)

    def position_beta(series):
        return _number(risk.beta(series, benchmark), 4) if benchmark is not None else None

    result |= {
        "volatility": _number(std * per_year, 6),
        "beta": position_beta(portfolio_returns),
        "value_at_risk": {
            "level": 0.95,
            "horizon": "1 trading day",
            "historical": _figure(hist_var, total),
            "parametric": _figure(param_var, total),
        },
        "expected_shortfall": {
            "level": 0.95,
            "horizon": "1 trading day",
            "historical": _figure(hist_es, total),
            "parametric": _figure(param_es, total),
        },
        "positions": [
            {
                "ticker": t,
                "weight": _number(market_values[t] / total, 6),
                "volatility": _number(returns[:, column[t]].std(ddof=1) * per_year, 6),
                "beta": position_beta(returns[:, column[t]]),
            }
            for t in measured
        ],
    }
    return result
