"""The prediction journal: record directional calls, resolve them, score them.

Every assistant prediction is paired with a coin-flip baseline on the same
ticker and horizon, so the assistant is always judged against chance. The
backend fills in the reference price and data mode; the model never supplies
prices. Stats are kept apart by data mode, so simulated results never mix with
real ones.
"""

from __future__ import annotations

import asyncio
import logging
import math
import random
import sqlite3
from collections.abc import Sequence
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .db import DEFAULT_USER_ID, connect, new_id, transaction
from .market import MarketDataSource, PriceCache
from .market.bars import REAL_ORIGINS, bucket_start

logger = logging.getLogger(__name__)

MIN_CONFIDENCE, MAX_CONFIDENCE = 0.5, 1.0
MIN_HORIZON_MINUTES, MAX_HORIZON_MINUTES = 1, 7 * 24 * 60
RESOLVE_SECONDS = 30.0
LATE_GRACE_SECONDS = 120  # How stale the live price may be when no bar covers the moment
CALIBRATION_BUCKETS = [(0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.0)]
Z_95 = 1.959963984540054


class PredictionError(ValueError):
    """A prediction that can't be recorded, reported back like a failed trade."""


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


def _now() -> datetime:
    return datetime.now(UTC)


def record(
    conn: sqlite3.Connection,
    cache: PriceCache,
    source: MarketDataSource,
    ticker: str,
    direction: str,
    confidence: float,
    horizon_minutes: int,
    chat_message_id: str | None = None,
    now: datetime | None = None,
    rng: random.Random | None = None,
) -> dict:
    """Record an assistant prediction and its coin-flip baseline. Returns the assistant's.

    The ticker must be tracked, so a price will exist to resolve it against.
    """
    if direction not in ("up", "down"):
        raise PredictionError("Direction must be up or down.")
    if not (
        isinstance(confidence, int | float)
        and not isinstance(confidence, bool)
        and MIN_CONFIDENCE <= confidence <= MAX_CONFIDENCE
    ):
        raise PredictionError("Confidence must be between 0.5 (a coin flip) and 1.0 (certain).")
    if not (
        isinstance(horizon_minutes, int)
        and not isinstance(horizon_minutes, bool)
        and MIN_HORIZON_MINUTES <= horizon_minutes <= MAX_HORIZON_MINUTES
    ):
        raise PredictionError(
            f"Horizon must be {MIN_HORIZON_MINUTES} to {MAX_HORIZON_MINUTES} whole minutes."
        )
    if ticker not in source.get_tickers():
        raise PredictionError(f"{ticker} isn't tracked. Add it to the watchlist first.")
    price = cache.get_price(ticker)
    if price is None:
        raise PredictionError(f"No price for {ticker} yet.")

    made = now or _now()
    resolves = made + timedelta(minutes=horizon_minutes)
    assistant_id, baseline_id = new_id(), new_id()
    common = (ticker, horizon_minutes, price, source.mode, _iso(made), _iso(resolves))
    baseline_direction = (rng or random).choice(["up", "down"])
    rows = [
        (assistant_id, "assistant", direction, float(confidence), baseline_id),
        (baseline_id, "baseline", baseline_direction, 0.5, assistant_id),
    ]
    with transaction(conn):
        conn.executemany(
            """
            INSERT INTO predictions (
                id, user_id, predictor, ticker, direction, confidence, horizon_minutes,
                reference_price, data_mode, made_at, resolves_at, pair_id, chat_message_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (id_, DEFAULT_USER_ID, who, ticker, way, conf, *common[1:], pair, chat_message_id)
                for id_, who, way, conf, pair in rows
            ],
        )
    return {
        "id": assistant_id,
        "ticker": ticker,
        "direction": direction,
        "confidence": float(confidence),
        "horizon_minutes": horizon_minutes,
        "reference_price": price,
        "data_mode": source.mode,
        "resolves_at": _iso(resolves),
    }


# --- Resolution ---


def _price_at(
    conn: sqlite3.Connection, cache: PriceCache, ticker: str, moment: datetime, now: datetime
) -> tuple[float | None, str | None]:
    """The price when the prediction came due: the real one-minute bar for that
    minute, or the live price if it is still fresh. Otherwise nothing and why."""
    start = bucket_start(moment.timestamp(), "1m")
    row = conn.execute(
        f"""
        SELECT close FROM price_bars
        WHERE ticker = ? AND timeframe = '1m' AND start_ts = ?
        AND origin IN ({", ".join("?" * len(REAL_ORIGINS))})
        """,
        (ticker, start, *REAL_ORIGINS),
    ).fetchone()
    if row:
        return row["close"], None
    if (now - moment).total_seconds() <= LATE_GRACE_SECONDS:
        price = cache.get_price(ticker)
        if price is not None:
            return price, None
        return None, "No price for the ticker when the prediction came due."
    return None, "No price was recorded when the prediction came due."


def _outcome(direction: str, reference: float, resolved: float) -> tuple[str, str | None]:
    if resolved == reference:
        return "void", "The price didn't move."
    moved_up = resolved > reference
    return ("hit" if moved_up == (direction == "up") else "miss"), None


def resolve_due(conn: sqlite3.Connection, cache: PriceCache, now: datetime | None = None) -> int:
    """Settle every prediction whose horizon has passed. Returns how many."""
    now = now or _now()
    due = conn.execute(
        """
        SELECT id, ticker, direction, reference_price, resolves_at FROM predictions
        WHERE user_id = ? AND outcome IS NULL AND resolves_at <= ?
        """,
        (DEFAULT_USER_ID, _iso(now)),
    ).fetchall()
    updates = []
    for row in due:
        moment = datetime.fromisoformat(row["resolves_at"])
        price, reason = _price_at(conn, cache, row["ticker"], moment, now)
        if price is None:
            updates.append((None, "void", reason, row["id"]))
        else:
            outcome, note = _outcome(row["direction"], row["reference_price"], price)
            updates.append((price, outcome, note, row["id"]))
    if updates:
        with transaction(conn):
            conn.executemany(
                "UPDATE predictions SET resolved_price = ?, outcome = ?, note = ? WHERE id = ?",
                updates,
            )
    return len(updates)


async def resolve_loop(db_path: Path, cache: PriceCache, interval: float = RESOLVE_SECONDS) -> None:
    """Settle due predictions on an interval. Failures don't stop it."""
    while True:
        try:
            with closing(connect(db_path)) as conn:
                resolve_due(conn, cache)
        except Exception:
            logger.exception("Resolving predictions failed")
        await asyncio.sleep(interval)


# --- Scoring ---


def wilson_interval(hits: int, n: int) -> tuple[float, float] | None:
    """95% confidence interval for a hit rate; honest about small samples."""
    if n == 0:
        return None
    p = hits / n
    denominator = 1 + Z_95**2 / n
    center = (p + Z_95**2 / (2 * n)) / denominator
    spread = Z_95 * math.sqrt(p * (1 - p) / n + Z_95**2 / (4 * n * n)) / denominator
    return round(center - spread, 4), round(center + spread, 4)


def score(rows: Sequence[sqlite3.Row]) -> dict:
    """Hit rate, Brier score and calibration for one predictor's predictions.

    Brier scores the stated confidence: 0 is perfect, 0.25 is a coin flip, and
    confident misses push it up. Void predictions count for nothing.
    """
    settled = [r for r in rows if r["outcome"] in ("hit", "miss")]
    hits = sum(r["outcome"] == "hit" for r in settled)
    n = len(settled)
    brier = (
        sum((r["confidence"] - (r["outcome"] == "hit")) ** 2 for r in settled) / n if n else None
    )
    calibration = []
    for low, high in CALIBRATION_BUCKETS:
        bucket = [
            r
            for r in settled
            if low <= r["confidence"] < high or (high == 1.0 and r["confidence"] == 1.0)
        ]
        if bucket:
            calibration.append(
                {
                    "range": [low, high],
                    "count": len(bucket),
                    "stated": round(sum(r["confidence"] for r in bucket) / len(bucket), 4),
                    "observed": round(sum(r["outcome"] == "hit" for r in bucket) / len(bucket), 4),
                }
            )
    return {
        "made": len(rows),
        "settled": n,
        "hits": hits,
        "void": sum(r["outcome"] == "void" for r in rows),
        "pending": sum(r["outcome"] is None for r in rows),
        "hit_rate": round(hits / n, 4) if n else None,
        "hit_rate_interval": wilson_interval(hits, n),
        "brier": round(brier, 4) if brier is not None else None,
        "calibration": calibration,
    }


def stats(conn: sqlite3.Connection) -> dict:
    """Scores per data mode, for the assistant and its coin-flip baseline."""
    rows = conn.execute(
        """
        SELECT predictor, data_mode, confidence, outcome FROM predictions WHERE user_id = ?
        """,
        (DEFAULT_USER_ID,),
    ).fetchall()
    modes = sorted({r["data_mode"] for r in rows})
    return {
        "modes": {
            mode: {
                predictor: score(
                    [r for r in rows if r["data_mode"] == mode and r["predictor"] == predictor]
                )
                for predictor in ("assistant", "baseline")
            }
            for mode in modes
        }
    }


def recent(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    """The latest assistant predictions, newest first, each with its baseline's outcome."""
    rows = conn.execute(
        """
        SELECT p.id, p.ticker, p.direction, p.confidence, p.horizon_minutes,
               p.reference_price, p.data_mode, p.made_at, p.resolves_at,
               p.resolved_price, p.outcome, p.note, p.chat_message_id,
               b.direction AS baseline_direction, b.outcome AS baseline_outcome
        FROM predictions p LEFT JOIN predictions b ON b.id = p.pair_id
        WHERE p.user_id = ? AND p.predictor = 'assistant'
        ORDER BY p.made_at DESC, p.rowid DESC LIMIT ?
        """,
        (DEFAULT_USER_ID, limit),
    ).fetchall()
    return [dict(row) for row in rows]
