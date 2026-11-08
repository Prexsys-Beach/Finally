"""LLM chat: portfolio-aware replies that can trade and manage the watchlist."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sqlite3
import time
from typing import Literal

from litellm import completion
from pydantic import BaseModel, Field, ValidationError

from . import assistant_tools, predictions
from .db import DEFAULT_USER_ID, new_id, utc_now
from .market import MarketDataSource, PriceCache
from .portfolio import TradeError, get_portfolio, place_trade
from .watchlist import (
    WatchlistError,
    add_to_watchlist,
    get_watchlist,
    remove_from_watchlist,
    validate_ticker,
)

logger = logging.getLogger(__name__)

MODEL = "openrouter/openai/gpt-oss-120b"
EXTRA_BODY = {"provider": {"order": ["cerebras"]}}
HISTORY_LIMIT = 20
LLM_TIMEOUT_SECONDS = 30
RESEARCH_BUDGET_SECONDS = 45  # Lookups stop here; the final answer still gets its own call
DEFAULT_TOOL_ROUNDS = 4

SYSTEM_PROMPT = """You are FinAlly, an AI trading assistant inside a simulated trading \
workstation. All money is virtual.

- Analyze portfolio composition, risk concentration and P&L.
- Suggest trades with reasoning.
- Execute trades when the user asks or agrees, by listing them in "trades". They run \
immediately at the current price, with no confirmation step.
- Manage the watchlist proactively through "watchlist_changes".
- Only list an action if you intend it to run now. Never list a trade you are merely suggesting.
- Before making claims about trends, momentum, volatility, correlation or risk, look them \
up with your tools, and cite the numbers you used. Tools only read data; they never trade.
- Whenever you state your own view on which way a price will go, record it in \
"predictions" (describing a forecast's range or odds is not a view of your own, so \
don't record those): ticker, direction (up or down), your honest confidence from \
0.5 (a coin flip) to 1.0 (certain), and a horizon in minutes (1 to 10080). If the user asks for a prediction, \
give one and record it: never decline. Every prediction is scored against a coin flip, \
so overconfidence costs you. When market_data_mode is "simulated" or "seeded", say in \
your message that the prices are simulated and the call is close to a coin flip, and \
keep confidence near 0.5. Use get_prediction_record to see how your past calls have done.
- Your reply is final: everything is looked up before you write it. Never say you will \
fetch or check something next. If a lookup failed or data is missing, say what is missing.
- Tool results report which bars they used: "synthetic" bars are made-up history, \
"recorded" and "vendor" bars are real prices. When market_data_mode is "simulated" or \
"seeded", even recorded prices come from a random simulation, so past patterns don't \
predict future moves; say so if you discuss direction.
- Be concise and data-driven. Use the numbers in the context below.
- Always respond with valid JSON matching the requested schema.

Current state:
{context}"""


class TradeAction(BaseModel):
    ticker: str
    side: Literal["buy", "sell"]
    quantity: float


class WatchlistChange(BaseModel):
    ticker: str
    action: Literal["add", "remove"]


class Prediction(BaseModel):
    ticker: str
    direction: Literal["up", "down"]
    confidence: float  # 0.5 is a coin flip, 1.0 is certain
    horizon_minutes: int


class LLMResponse(BaseModel):
    message: str
    trades: list[TradeAction] = Field(default_factory=list)
    watchlist_changes: list[WatchlistChange] = Field(default_factory=list)
    predictions: list[Prediction] = Field(default_factory=list)


class ChatError(Exception):
    """The LLM call failed or returned something unusable."""


def _context(conn: sqlite3.Connection, cache: PriceCache, source: MarketDataSource) -> str:
    watchlist = [
        {k: entry[k] for k in ("ticker", "price", "day_change_percent")}
        for entry in get_watchlist(conn, cache)
    ]
    state = {
        "portfolio": get_portfolio(conn, cache),
        "watchlist": watchlist,
        "market_data_mode": source.mode,
    }
    return json.dumps(state)


def _history(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT role, content FROM chat_messages WHERE user_id = ?
        ORDER BY rowid DESC LIMIT ?
        """,
        (DEFAULT_USER_ID, HISTORY_LIMIT),
    ).fetchall()
    return [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]


def get_messages(conn: sqlite3.Connection, limit: int = 100) -> list[dict]:
    """Recent conversation for display, oldest first."""
    rows = conn.execute(
        """
        SELECT role, content, actions, created_at FROM chat_messages WHERE user_id = ?
        ORDER BY rowid DESC LIMIT ?
        """,
        (DEFAULT_USER_ID, limit),
    ).fetchall()
    return [
        {**dict(row), "actions": json.loads(row["actions"]) if row["actions"] else None}
        for row in reversed(rows)
    ]


def _store(
    conn: sqlite3.Connection,
    role: str,
    content: str,
    actions: dict | None,
    message_id: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO chat_messages (id, user_id, role, content, actions, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            message_id or new_id(),
            DEFAULT_USER_ID,
            role,
            content,
            json.dumps(actions) if actions is not None else None,
            utc_now(),
        ),
    )


def _call_llm(messages: list[dict]) -> LLMResponse:
    """Blocking call to the model. Raises ChatError on any failure."""
    try:
        response = completion(
            model=MODEL,
            messages=messages,
            response_format=LLMResponse,
            reasoning_effort="low",
            extra_body=EXTRA_BODY,
            timeout=LLM_TIMEOUT_SECONDS,
        )
        return LLMResponse.model_validate_json(response.choices[0].message.content or "")
    except ValidationError as e:
        logger.warning("Malformed LLM response: %s", e)
        raise ChatError("The assistant returned an unreadable response.") from e
    except Exception as e:
        logger.error("LLM call failed: %s", e)
        raise ChatError("The assistant is unavailable right now.") from e


def _tool_rounds() -> int:
    raw = os.environ.get("CHAT_MAX_TOOL_ROUNDS", "").strip()
    try:
        return max(0, int(raw)) if raw else DEFAULT_TOOL_ROUNDS
    except ValueError:
        logger.warning("Ignoring invalid CHAT_MAX_TOOL_ROUNDS: %r", raw)
        return DEFAULT_TOOL_ROUNDS


def _call_with_tools(messages: list[dict]):
    """One lookup round: the model may call tools. Raises ChatError on failure."""
    try:
        response = completion(
            model=MODEL,
            messages=messages,
            tools=assistant_tools.TOOLS,
            reasoning_effort="low",
            extra_body=EXTRA_BODY,
            timeout=LLM_TIMEOUT_SECONDS,
        )
        return response.choices[0].message
    except Exception as e:
        logger.error("LLM tool round failed: %s", e)
        raise ChatError("The assistant is unavailable right now.") from e


def _assistant_turn(message, calls) -> dict:
    """The model's tool-calling turn, in the shape the next request needs."""
    return {
        "role": "assistant",
        "content": message.content or "",
        "tool_calls": [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.function.name, "arguments": call.function.arguments},
            }
            for call in calls
        ],
    }


async def _research(messages: list[dict], tools: assistant_tools.ToolContext) -> list[dict]:
    """Let the model look things up before it answers. Appends the lookups to messages.

    Tool rounds carry no response schema: asked for both at once, the model
    tended to fill in trades nobody asked for. The answer comes from a separate
    structured call afterwards. Tools run here, on the request's own thread,
    because the SQLite connection belongs to it.
    """
    records: list[dict] = []
    deadline = time.monotonic() + RESEARCH_BUDGET_SECONDS
    for _ in range(_tool_rounds()):
        if time.monotonic() > deadline:
            logger.warning("Chat research budget spent; answering with what was found")
            break
        message = await asyncio.to_thread(_call_with_tools, messages)
        calls = getattr(message, "tool_calls", None) or []
        if not calls:
            break
        messages.append(_assistant_turn(message, calls))
        for call in calls:
            content, record = assistant_tools.run(
                tools, call.function.name, call.function.arguments
            )
            messages.append({"role": "tool", "tool_call_id": call.id, "content": content})
            records.append(record)
    return records


def _mock_tools(message: str, tools: assistant_tools.ToolContext) -> list[dict]:
    """Deterministic lookups for LLM_MOCK=true: 'analyze NVDA' reads its indicators,
    any mention of risk reads portfolio risk, and 'forecast' runs a one-day
    portfolio forecast. The tools really run."""
    requests = [
        ("get_indicators", {"ticker": ticker})
        for ticker in re.findall(r"\banaly[sz]e\s+([A-Za-z.\-]+)", message, re.IGNORECASE)
    ]
    if re.search(r"\brisk", message, re.IGNORECASE):
        requests.append(("get_portfolio_risk", {}))
    if re.search(r"\bforecast", message, re.IGNORECASE):
        requests.append(("run_forecast", {"target": "portfolio", "horizon": "1d"}))
    return [assistant_tools.run(tools, name, json.dumps(args))[1] for name, args in requests]


def _mock_response(message: str) -> LLMResponse:
    """Deterministic replies for LLM_MOCK=true: 'buy 5 AAPL', 'sell 1 MSFT',
    'add PYPL', 'remove NFLX', and 'predict NVDA up' (optionally '70%' and '30m';
    60% over 60 minutes otherwise). Anything else gets a fixed reply and no actions."""
    calls = [
        Prediction(
            ticker=ticker,
            direction=direction.lower(),
            confidence=int(percent or 60) / 100,
            horizon_minutes=int(minutes or 60),
        )
        for ticker, direction, percent, minutes in re.findall(
            r"\bpredict\s+([A-Za-z.\-]+)\s+(up|down)(?:\s+(\d+)%)?(?:\s+(\d+)\s*m(?:in)?\b)?",
            message,
            re.IGNORECASE,
        )
    ]
    trades = [
        TradeAction(side=side.lower(), quantity=float(quantity), ticker=ticker)
        for side, quantity, ticker in re.findall(
            r"\b(buy|sell)\s+(\d+(?:\.\d+)?)\s+([A-Za-z.\-]+)", message, re.IGNORECASE
        )
    ]
    changes = [
        WatchlistChange(action=action.lower(), ticker=ticker)
        for action, ticker in re.findall(r"\b(add|remove)\s+([A-Za-z.\-]+)", message, re.IGNORECASE)
    ]
    return LLMResponse(
        message="Mock response: request received.",
        trades=trades,
        watchlist_changes=changes,
        predictions=calls,
    )


async def _apply_watchlist_change(
    conn: sqlite3.Connection, source: MarketDataSource, change: WatchlistChange
) -> dict:
    result = {"ticker": change.ticker, "action": change.action, "status": "ok", "error": None}
    try:
        ticker = validate_ticker(change.ticker)
        result["ticker"] = ticker
        if change.action == "add":
            await add_to_watchlist(conn, source, ticker)
        else:
            await remove_from_watchlist(conn, source, ticker)
    except (ValueError, WatchlistError) as e:
        result |= {"status": "failed", "error": str(e)}
    return result


async def _apply_trade(
    conn: sqlite3.Connection,
    cache: PriceCache,
    source: MarketDataSource,
    action: TradeAction,
) -> dict:
    result = {**action.model_dump(), "price": None, "status": "ok", "error": None}
    try:
        ticker = validate_ticker(action.ticker)
        result["ticker"] = ticker
        trade = await place_trade(conn, cache, source, ticker, action.side, action.quantity)
        result["price"] = trade["price"]
    except (ValueError, TradeError) as e:
        result |= {"status": "failed", "error": str(e)}
    return result


def _record_prediction(
    conn: sqlite3.Connection,
    cache: PriceCache,
    source: MarketDataSource,
    call: Prediction,
    message_id: str,
) -> dict:
    result = {**call.model_dump(), "id": None, "reference_price": None, "resolves_at": None}
    result |= {"status": "ok", "error": None}
    try:
        ticker = validate_ticker(call.ticker)
        result["ticker"] = ticker
        recorded = predictions.record(
            conn,
            cache,
            source,
            ticker,
            call.direction,
            call.confidence,
            call.horizon_minutes,
            chat_message_id=message_id,
        )
        result |= {k: recorded[k] for k in ("id", "reference_price", "resolves_at")}
    except (ValueError, predictions.PredictionError) as e:
        result |= {"status": "failed", "error": str(e)}
    return result


def _with_failures(message: str, *groups: list[dict]) -> str:
    """Add what didn't run, since the model replied before anything executed."""
    failures = [f"- {item['error']}" for group in groups for item in group if item["error"]]
    if not failures:
        return message
    return "\n\n".join([message, "Some actions could not be completed:", "\n".join(failures)])


async def handle_chat(
    conn: sqlite3.Connection,
    cache: PriceCache,
    source: MarketDataSource,
    user_message: str,
    retention_days: float = 30,
) -> dict:
    """Answer a user message: look things up, then run any actions the model chose.

    Nothing is stored if the LLM fails, so a retry doesn't duplicate the message.
    """
    tools = assistant_tools.ToolContext(conn, cache, source, retention_days)
    if os.environ.get("LLM_MOCK", "").strip().lower() == "true":
        tool_calls = _mock_tools(user_message, tools)
        reply = _mock_response(user_message)
    else:
        system = SYSTEM_PROMPT.format(context=_context(conn, cache, source))
        messages = [
            {"role": "system", "content": system},
            *_history(conn),
            {"role": "user", "content": user_message},
        ]
        tool_calls = await _research(messages, tools)
        reply = await asyncio.to_thread(_call_llm, messages)

    # Watchlist first, so "add X and buy it" tracks the ticker before trading
    changes = [await _apply_watchlist_change(conn, source, c) for c in reply.watchlist_changes]
    trades = [await _apply_trade(conn, cache, source, t) for t in reply.trades]
    message_id = new_id()
    calls = [_record_prediction(conn, cache, source, p, message_id) for p in reply.predictions]
    message = _with_failures(reply.message, changes, trades, calls)

    actions = {
        "trades": trades,
        "watchlist_changes": changes,
        "predictions": calls,
        "tool_calls": tool_calls,
    }
    _store(conn, "user", user_message, None)
    _store(conn, "assistant", message, actions, message_id)
    return {"message": message, **actions}
