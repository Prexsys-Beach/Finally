"""Read-only tools the assistant can call before it answers.

Each tool is a thin wrapper over the analytics service and returns compact JSON.
None of them trade or change anything: trades and watchlist changes only come
from the assistant's final structured answer, where they are validated as usual.
A failure is returned to the model as {"error": ...}, never raised, so it can
correct itself or explain.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from .analytics import service as analytics
from .market import MarketDataSource, PriceCache
from .market.bars import TIMEFRAME_SECONDS, recent_bars
from .watchlist import validate_ticker

logger = logging.getLogger(__name__)

MAX_BARS = 120
INDICATOR_BARS = {"1m": 390, "1d": 252}  # A trading day of minutes; a trading year
TIMEFRAMES = ("1m", "1d")

# Signals that make the analysis panel worth showing: these read portfolio risk
RISK_TOOLS = ("get_portfolio_risk", "get_correlations")


@dataclass(frozen=True)
class ToolContext:
    conn: sqlite3.Connection
    cache: PriceCache
    source: MarketDataSource
    retention_days: float


class ToolError(ValueError):
    """Bad arguments or missing data, reported back to the model."""


def _function(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


_TICKER = {"type": "string", "description": "Ticker symbol, e.g. AAPL"}
_TIMEFRAME = {
    "type": "string",
    "enum": list(TIMEFRAMES),
    "description": "1d for daily bars (the default), 1m for one-minute bars",
}

TOOLS = [
    _function(
        "get_indicators",
        "Latest technical indicators for a ticker: close, SMA 20, EMA 50, Bollinger "
        "Bands, RSI 14, MACD, ATR 14, annualized volatility, and simple signals "
        "(RSI overbought/oversold, price vs bands and SMA, MACD vs signal).",
        {"ticker": _TICKER, "timeframe": _TIMEFRAME},
        ["ticker"],
    ),
    _function(
        "get_bars",
        f"Recent OHLC price bars for a ticker, oldest first (at most {MAX_BARS}).",
        {
            "ticker": _TICKER,
            "timeframe": _TIMEFRAME,
            "limit": {"type": "integer", "minimum": 1, "maximum": MAX_BARS},
        },
        ["ticker"],
    ),
    _function(
        "get_portfolio_risk",
        "Risk of the current portfolio: annualized volatility, beta vs the "
        "equal-weighted watchlist, 1-day 95% Value at Risk and expected shortfall, "
        "concentration, max drawdown, Sharpe ratio, and per-position weight, "
        "volatility and beta. Weights include cash.",
        {},
        [],
    ),
    _function(
        "get_correlations",
        "Correlation of daily returns between held and watched tickers.",
        {
            "tickers": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Tickers to include; all held and watched tickers if omitted",
            }
        },
        [],
    ),
]


def _ticker(value) -> str:
    try:
        return validate_ticker(str(value))
    except ValueError as e:
        raise ToolError(str(e)) from e


def _timeframe(value) -> str:
    if value not in TIMEFRAMES:
        raise ToolError(f"timeframe must be one of: {', '.join(TIMEFRAMES)}")
    return value


def _stamp(timestamp: int, timeframe: str) -> str:
    moment = datetime.fromtimestamp(timestamp, UTC)
    return moment.strftime("%Y-%m-%d" if timeframe == "1d" else "%Y-%m-%dT%H:%MZ")


def get_indicators(ctx: ToolContext, ticker: str, timeframe: str = "1d") -> dict:
    ticker, timeframe = _ticker(ticker), _timeframe(timeframe)
    result = analytics.ticker_analytics(
        ctx.conn, ticker, timeframe, INDICATOR_BARS[timeframe], ctx.retention_days
    )
    if not result["bars"]:
        raise ToolError(f"No price history for {ticker}.")
    return {
        "ticker": ticker,
        "timeframe": timeframe,
        "bars_used": result["bars"],
        "origins": result["origins"],
        "latest": result["latest"],
        "signals": result["signals"],
    }


def get_bars(ctx: ToolContext, ticker: str, timeframe: str = "1d", limit: int = 30) -> dict:
    ticker, timeframe = _ticker(ticker), _timeframe(timeframe)
    if not isinstance(limit, int) or isinstance(limit, bool):
        raise ToolError("limit must be a whole number")
    bars = recent_bars(ctx.conn, ticker, timeframe, max(1, min(limit, MAX_BARS)))
    if not bars:
        raise ToolError(f"No price history for {ticker}.")
    origins: dict[str, int] = {}
    for bar in bars:
        origins[bar.origin] = origins.get(bar.origin, 0) + 1
    return {
        "ticker": ticker,
        "timeframe": timeframe,
        "bar_seconds": TIMEFRAME_SECONDS[timeframe],
        "columns": ["time", "open", "high", "low", "close"],
        "bars": [[_stamp(b.start_ts, timeframe), b.open, b.high, b.low, b.close] for b in bars],
        "origins": origins,
    }


def _portfolio(ctx: ToolContext) -> dict:
    return analytics.portfolio_analytics(
        ctx.conn, ctx.cache, "1d", ctx.retention_days, mode=ctx.source.mode
    )


def get_portfolio_risk(ctx: ToolContext) -> dict:
    result = _portfolio(ctx)
    del result["correlation"]  # get_correlations has it, and it is the bulkiest part
    return result


def get_correlations(ctx: ToolContext, tickers: list[str] | None = None) -> dict:
    result = _portfolio(ctx)
    available = result["correlation"]["tickers"]
    matrix = result["correlation"]["matrix"]
    if matrix is None:
        raise ToolError("Not enough shared price history to measure correlation yet.")
    wanted = available if not tickers else [_ticker(t) for t in tickers]
    index = {t: i for i, t in enumerate(available)}
    found = [t for t in wanted if t in index]
    pairs = [
        [a, b, matrix[index[a]][index[b]]] for i, a in enumerate(found) for b in found[i + 1 :]
    ]
    return {
        "measured_on": f"{result['returns']} daily returns",
        "origins": result["origins"],
        "pairs": pairs,
        "not_available": [t for t in wanted if t not in index],
    }


_FUNCTIONS: dict[str, Callable[..., dict]] = {
    "get_indicators": get_indicators,
    "get_bars": get_bars,
    "get_portfolio_risk": get_portfolio_risk,
    "get_correlations": get_correlations,
}


def run(ctx: ToolContext, name: str, arguments: str | None) -> tuple[str, dict]:
    """Run a tool call. Returns the JSON content for the model and a record for the chat."""
    record: dict = {"name": name, "arguments": {}, "status": "ok", "error": None}
    try:
        args = json.loads(arguments or "{}")
        if not isinstance(args, dict):
            raise ToolError("Arguments must be a JSON object.")
        record["arguments"] = args
        function = _FUNCTIONS.get(name)
        if function is None:
            raise ToolError(f"Unknown tool: {name}")
        try:
            result = function(ctx, **args)
        except TypeError as e:
            raise ToolError(f"Bad arguments for {name}.") from e
    except (ToolError, json.JSONDecodeError) as e:
        message = str(e) if isinstance(e, ToolError) else "Arguments were not valid JSON."
        record |= {"status": "failed", "error": message}
        return json.dumps({"error": message}), record
    except Exception:
        logger.exception("Tool %s failed", name)
        record |= {"status": "failed", "error": "The lookup failed."}
        return json.dumps({"error": "The lookup failed."}), record
    return json.dumps(result, separators=(",", ":")), record
