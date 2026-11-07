"""LLM chat: portfolio-aware replies that can trade and manage the watchlist."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sqlite3
from typing import Literal

from litellm import completion
from pydantic import BaseModel, Field, ValidationError

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

SYSTEM_PROMPT = """You are FinAlly, an AI trading assistant inside a simulated trading \
workstation. All money is virtual.

- Analyze portfolio composition, risk concentration and P&L.
- Suggest trades with reasoning.
- Execute trades when the user asks or agrees, by listing them in "trades". They run \
immediately at the current price, with no confirmation step.
- Manage the watchlist proactively through "watchlist_changes".
- Only list an action if you intend it to run now. Never list a trade you are merely suggesting.
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


class LLMResponse(BaseModel):
    message: str
    trades: list[TradeAction] = Field(default_factory=list)
    watchlist_changes: list[WatchlistChange] = Field(default_factory=list)


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


def _store(conn: sqlite3.Connection, role: str, content: str, actions: dict | None) -> None:
    conn.execute(
        """
        INSERT INTO chat_messages (id, user_id, role, content, actions, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            new_id(),
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


def _mock_response(message: str) -> LLMResponse:
    """Deterministic replies for LLM_MOCK=true: 'buy 5 AAPL', 'sell 1 MSFT',
    'add PYPL', 'remove NFLX'. Anything else gets a fixed reply and no actions."""
    trades = [
        TradeAction(side=side.lower(), quantity=float(quantity), ticker=ticker)
        for side, quantity, ticker in re.findall(
            r"\b(buy|sell)\s+(\d+(?:\.\d+)?)\s+([A-Za-z.\-]+)", message, re.IGNORECASE
        )
    ]
    changes = [
        WatchlistChange(action=action.lower(), ticker=ticker)
        for action, ticker in re.findall(
            r"\b(add|remove)\s+([A-Za-z.\-]+)", message, re.IGNORECASE
        )
    ]
    return LLMResponse(
        message="Mock response: request received.", trades=trades, watchlist_changes=changes
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


def _with_failures(message: str, trades: list[dict], changes: list[dict]) -> str:
    """Add what didn't run, since the model replied before anything executed."""
    failures = [f"- {item['error']}" for item in [*changes, *trades] if item["error"]]
    if not failures:
        return message
    return "\n\n".join([message, "Some actions could not be completed:", "\n".join(failures)])


async def handle_chat(
    conn: sqlite3.Connection,
    cache: PriceCache,
    source: MarketDataSource,
    user_message: str,
) -> dict:
    """Answer a user message and run any actions the model chose.

    Nothing is stored if the LLM fails, so a retry doesn't duplicate the message.
    """
    if os.environ.get("LLM_MOCK", "").strip().lower() == "true":
        reply = _mock_response(user_message)
    else:
        system = SYSTEM_PROMPT.format(context=_context(conn, cache, source))
        messages = [
            {"role": "system", "content": system},
            *_history(conn),
            {"role": "user", "content": user_message},
        ]
        reply = await asyncio.to_thread(_call_llm, messages)

    # Watchlist first, so "add X and buy it" tracks the ticker before trading
    changes = [await _apply_watchlist_change(conn, source, c) for c in reply.watchlist_changes]
    trades = [await _apply_trade(conn, cache, source, t) for t in reply.trades]
    message = _with_failures(reply.message, trades, changes)

    _store(conn, "user", user_message, None)
    _store(conn, "assistant", message, {"trades": trades, "watchlist_changes": changes})
    return {"message": message, "trades": trades, "watchlist_changes": changes}
