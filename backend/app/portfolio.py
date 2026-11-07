"""Portfolio valuation, trade execution and value history.

Routes and the LLM chat flow share place_trade(), so manual and AI trades
pass exactly the same validation.
"""

from __future__ import annotations

import asyncio
import logging
import math
import sqlite3
from contextlib import closing
from pathlib import Path

from .db import DEFAULT_USER_ID, connect, new_id, transaction, utc_now
from .market import MarketDataSource, PriceCache
from .watchlist import release_ticker

logger = logging.getLogger(__name__)

SNAPSHOT_INTERVAL_SECONDS = 30.0
EPSILON = 1e-9  # Tolerance for float dust, e.g. selling a whole fractional position


class TradeError(Exception):
    """A trade the user can't make, such as one with insufficient cash."""


class PriceUnavailableError(TradeError):
    """No price yet. Massive prices new tickers on the next poll, so retrying can work."""


def get_cash(conn: sqlite3.Connection) -> float:
    query = "SELECT cash_balance FROM users_profile WHERE id = ?"
    return conn.execute(query, (DEFAULT_USER_ID,)).fetchone()["cash_balance"]


def _positions(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    query = "SELECT ticker, quantity, avg_cost FROM positions WHERE user_id = ? ORDER BY ticker"
    return conn.execute(query, (DEFAULT_USER_ID,)).fetchall()


def _value_position(row: sqlite3.Row, cache: PriceCache) -> dict:
    update = cache.get(row["ticker"])
    cost_basis = row["quantity"] * row["avg_cost"]
    position = {
        "ticker": row["ticker"],
        "quantity": row["quantity"],
        "avg_cost": round(row["avg_cost"], 4),
        "cost_basis": round(cost_basis, 2),
        "current_price": None,
        "market_value": None,
        "unrealized_pnl": None,
        "unrealized_pnl_percent": None,
        "day_change_percent": None,
    }
    if update:
        market_value = row["quantity"] * update.price
        position |= {
            "current_price": update.price,
            "market_value": round(market_value, 2),
            "unrealized_pnl": round(market_value - cost_basis, 2),
            "unrealized_pnl_percent": round((update.price / row["avg_cost"] - 1) * 100, 4),
            "day_change_percent": update.day_change_percent,
        }
    return position


def get_portfolio(conn: sqlite3.Connection, cache: PriceCache) -> dict:
    """Cash, positions and totals. An unpriced position counts at cost."""
    cash = get_cash(conn)
    positions = [_value_position(row, cache) for row in _positions(conn)]
    positions_value = sum(p["market_value"] or p["cost_basis"] for p in positions)
    return {
        "cash_balance": round(cash, 2),
        "positions": positions,
        "positions_value": round(positions_value, 2),
        "total_value": round(cash + positions_value, 2),
        "unrealized_pnl": round(sum(p["unrealized_pnl"] or 0 for p in positions), 2),
    }


def execute_trade(
    conn: sqlite3.Connection, ticker: str, side: str, quantity: float, price: float
) -> dict:
    """Validate and apply a market order at price, atomically."""
    if not math.isfinite(quantity) or quantity <= 0:
        raise TradeError(f"Invalid quantity for {ticker}: {quantity:g}")

    now = utc_now()
    trade = {
        "id": new_id(),
        "ticker": ticker,
        "side": side,
        "quantity": quantity,
        "price": price,
        "executed_at": now,
    }
    with transaction(conn):
        cash = get_cash(conn)
        held = conn.execute(
            "SELECT quantity, avg_cost FROM positions WHERE user_id = ? AND ticker = ?",
            (DEFAULT_USER_ID, ticker),
        ).fetchone()
        owned = held["quantity"] if held else 0.0
        notional = quantity * price

        if side == "buy":
            if notional > cash + EPSILON:
                raise TradeError(
                    f"Insufficient cash: {quantity:g} {ticker} costs ${notional:,.2f}, "
                    f"available ${cash:,.2f}"
                )
            new_cash = max(cash - notional, 0.0)
            new_quantity = owned + quantity
            old_cost = owned * held["avg_cost"] if held else 0.0
            new_avg_cost = (old_cost + notional) / new_quantity
            conn.execute(
                """
                INSERT INTO positions (id, user_id, ticker, quantity, avg_cost, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (user_id, ticker) DO UPDATE SET
                    quantity = excluded.quantity,
                    avg_cost = excluded.avg_cost,
                    updated_at = excluded.updated_at
                """,
                (new_id(), DEFAULT_USER_ID, ticker, new_quantity, new_avg_cost, now),
            )
        else:
            if quantity > owned + EPSILON:
                raise TradeError(
                    f"Insufficient shares: selling {quantity:g} {ticker}, you own {owned:g}"
                )
            new_cash = cash + notional
            remaining = owned - quantity
            if remaining <= EPSILON:
                conn.execute(
                    "DELETE FROM positions WHERE user_id = ? AND ticker = ?",
                    (DEFAULT_USER_ID, ticker),
                )
            else:
                conn.execute(
                    """
                    UPDATE positions SET quantity = ?, updated_at = ?
                    WHERE user_id = ? AND ticker = ?
                    """,
                    (remaining, now, DEFAULT_USER_ID, ticker),
                )

        conn.execute(
            "UPDATE users_profile SET cash_balance = ? WHERE id = ?",
            (new_cash, DEFAULT_USER_ID),
        )
        conn.execute(
            """
            INSERT INTO trades (id, user_id, ticker, side, quantity, price, executed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (trade["id"], DEFAULT_USER_ID, ticker, side, quantity, price, now),
        )
    return trade


async def place_trade(
    conn: sqlite3.Connection,
    cache: PriceCache,
    source: MarketDataSource,
    ticker: str,
    side: str,
    quantity: float,
) -> dict:
    """Trade at the current price, keeping market data tracking in step."""
    newly_tracked = ticker not in source.get_tickers()
    if newly_tracked:
        await source.add_ticker(ticker)

    price = cache.get_price(ticker)
    if price is None:
        # Stay tracked: a live Massive source prices the ticker on its next poll.
        raise PriceUnavailableError(f"No price available for {ticker} yet. Try again shortly.")

    try:
        trade = execute_trade(conn, ticker, side, quantity, price)
    except TradeError:
        if newly_tracked:
            await release_ticker(conn, source, ticker)
        raise

    if side == "sell":
        await release_ticker(conn, source, ticker)  # The position may have closed
    record_snapshot(conn, cache)
    return trade


def record_snapshot(conn: sqlite3.Connection, cache: PriceCache) -> float | None:
    """Store the total value, or skip if a held ticker has no price.

    Counting an unpriced position at cost would put a false jump in the chart.
    """
    portfolio = get_portfolio(conn, cache)
    if any(p["current_price"] is None for p in portfolio["positions"]):
        return None
    conn.execute(
        """
        INSERT INTO portfolio_snapshots (id, user_id, total_value, recorded_at)
        VALUES (?, ?, ?, ?)
        """,
        (new_id(), DEFAULT_USER_ID, portfolio["total_value"], utc_now()),
    )
    return portfolio["total_value"]


def get_history(conn: sqlite3.Connection, limit: int = 1000) -> list[dict]:
    """The most recent snapshots, oldest first."""
    rows = conn.execute(
        """
        SELECT total_value, recorded_at FROM portfolio_snapshots
        WHERE user_id = ? ORDER BY recorded_at DESC LIMIT ?
        """,
        (DEFAULT_USER_ID, limit),
    ).fetchall()
    return [dict(row) for row in reversed(rows)]


async def snapshot_loop(
    db_path: Path, cache: PriceCache, interval: float = SNAPSHOT_INTERVAL_SECONDS
) -> None:
    """Record portfolio value now and then on an interval. Failures don't stop it."""
    while True:
        try:
            with closing(connect(db_path)) as conn:
                record_snapshot(conn, cache)
        except Exception:
            logger.exception("Portfolio snapshot failed")
        await asyncio.sleep(interval)
