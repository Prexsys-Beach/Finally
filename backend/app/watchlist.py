"""Watchlist rules, and which tickers the market data source must track."""

from __future__ import annotations

import re
import sqlite3

from .db import DEFAULT_USER_ID, new_id, utc_now
from .market import MarketDataSource, PriceCache, normalize_ticker

_TICKER_PATTERN = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


def validate_ticker(value: str) -> str:
    """Normalize a ticker, or raise ValueError if it can't be one."""
    ticker = normalize_ticker(value)
    if not _TICKER_PATTERN.match(ticker):
        raise ValueError(f"Invalid ticker: {value!r}")
    return ticker


class WatchlistError(Exception):
    """Base class for watchlist failures."""


class DuplicateTickerError(WatchlistError):
    pass


class TickerNotFoundError(WatchlistError):
    pass


def _in_watchlist(conn: sqlite3.Connection, ticker: str) -> bool:
    query = "SELECT 1 FROM watchlist WHERE user_id = ? AND ticker = ?"
    return conn.execute(query, (DEFAULT_USER_ID, ticker)).fetchone() is not None


def _has_position(conn: sqlite3.Connection, ticker: str) -> bool:
    query = "SELECT 1 FROM positions WHERE user_id = ? AND ticker = ?"
    return conn.execute(query, (DEFAULT_USER_ID, ticker)).fetchone() is not None


def tracked_tickers(conn: sqlite3.Connection) -> list[str]:
    """Watchlist plus open positions: everything that needs a live price."""
    rows = conn.execute(
        """
        SELECT ticker FROM watchlist WHERE user_id = :user
        UNION
        SELECT ticker FROM positions WHERE user_id = :user
        ORDER BY ticker
        """,
        {"user": DEFAULT_USER_ID},
    ).fetchall()
    return [row["ticker"] for row in rows]


async def release_ticker(
    conn: sqlite3.Connection, source: MarketDataSource, ticker: str
) -> None:
    """Stop tracking a ticker, unless the watchlist or a position still needs it."""
    if not _in_watchlist(conn, ticker) and not _has_position(conn, ticker):
        await source.remove_ticker(ticker)


def get_watchlist(conn: sqlite3.Connection, cache: PriceCache) -> list[dict]:
    """Watched tickers with latest prices. Price fields are None until known."""
    rows = conn.execute(
        "SELECT ticker, added_at FROM watchlist WHERE user_id = ? ORDER BY added_at, ticker",
        (DEFAULT_USER_ID,),
    ).fetchall()
    entries = []
    for row in rows:
        update = cache.get(row["ticker"])
        entries.append(
            {
                "ticker": row["ticker"],
                "added_at": row["added_at"],
                "price": update.price if update else None,
                "previous_price": update.previous_price if update else None,
                "previous_close": update.previous_close if update else None,
                "day_change_percent": update.day_change_percent if update else None,
                "direction": update.direction if update else None,
                "timestamp": update.timestamp if update else None,
            }
        )
    return entries


async def add_to_watchlist(
    conn: sqlite3.Connection, source: MarketDataSource, ticker: str
) -> None:
    if _in_watchlist(conn, ticker):
        raise DuplicateTickerError(f"{ticker} is already on the watchlist")
    conn.execute(
        "INSERT INTO watchlist (id, user_id, ticker, added_at) VALUES (?, ?, ?, ?)",
        (new_id(), DEFAULT_USER_ID, ticker, utc_now()),
    )
    await source.add_ticker(ticker)


async def remove_from_watchlist(
    conn: sqlite3.Connection, source: MarketDataSource, ticker: str
) -> None:
    deleted = conn.execute(
        "DELETE FROM watchlist WHERE user_id = ? AND ticker = ?",
        (DEFAULT_USER_ID, ticker),
    )
    if deleted.rowcount == 0:
        raise TickerNotFoundError(f"{ticker} is not on the watchlist")
    await release_ticker(conn, source, ticker)
