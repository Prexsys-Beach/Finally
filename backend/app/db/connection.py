"""SQLite connections, transactions and lazy initialization."""

from __future__ import annotations

import os
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_USER_ID = "default"
STARTING_CASH = 10000.0
DEFAULT_TICKERS = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"]

_SCHEMA = Path(__file__).with_name("schema.sql")
_DEFAULT_PATH = Path(__file__).resolve().parents[3] / "db" / "finally.db"


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


def database_path() -> Path:
    """FINALLY_DB_PATH, or db/finally.db in the project root."""
    configured = os.environ.get("FINALLY_DB_PATH", "").strip()
    return Path(configured) if configured else _DEFAULT_PATH


def connect(path: Path) -> sqlite3.Connection:
    """Open a connection in autocommit mode; use transaction() to group writes."""
    conn = sqlite3.connect(path, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[None]:
    """All-or-nothing write. Takes the write lock up front."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def init_db(path: Path) -> None:
    """Create the database if needed and seed it once, on first run only.

    Seeding is tied to the user profile, so tickers the user later removes
    from the watchlist don't come back on restart.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA.read_text())
        with transaction(conn):
            exists = conn.execute(
                "SELECT 1 FROM users_profile WHERE id = ?", (DEFAULT_USER_ID,)
            ).fetchone()
            if not exists:
                now = utc_now()
                conn.execute(
                    "INSERT INTO users_profile (id, cash_balance, created_at) VALUES (?, ?, ?)",
                    (DEFAULT_USER_ID, STARTING_CASH, now),
                )
                conn.executemany(
                    "INSERT INTO watchlist (id, user_id, ticker, added_at) VALUES (?, ?, ?, ?)",
                    [(new_id(), DEFAULT_USER_ID, t, now) for t in DEFAULT_TICKERS],
                )
    finally:
        conn.close()
