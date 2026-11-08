"""Records live prices as bars and backfills history for each ticker it sees.

Prices are read from the PriceCache, never from a data source, so recording works
the same whatever produces them.
"""

from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

from ..db import connect
from .bars import (
    BarBuilder,
    bucket_start,
    earliest_bar,
    insert_bars,
    prune,
    rollup_days,
    write_recorded,
)
from .cache import PriceCache
from .history import BackfillRequest, HistoryProvider

logger = logging.getLogger(__name__)

DEFAULT_BACKFILL_DAYS = 5.0  # One-minute bars
DEFAULT_DAILY_BACKFILL_DAYS = 365.0
DEFAULT_RETENTION_DAYS = 30.0  # One-minute bars; daily bars are kept
SAMPLE_SECONDS = 1.0
FLUSH_SECONDS = 5.0
PRUNE_SECONDS = 3600.0


class HistoryService:
    """Background recording and backfill.

    All database work runs on one worker thread, so it stays off the event loop
    and in order, and stop() can wait for it to finish.

    backfill_days 0 turns backfill off; recording still runs.
    """

    def __init__(
        self,
        db_path: Path,
        cache: PriceCache,
        provider: HistoryProvider,
        backfill_days: float = DEFAULT_BACKFILL_DAYS,
        daily_backfill_days: float = DEFAULT_DAILY_BACKFILL_DAYS,
        retention_days: float = DEFAULT_RETENTION_DAYS,
        sample_seconds: float = SAMPLE_SECONDS,
        flush_seconds: float = FLUSH_SECONDS,
    ) -> None:
        self._db_path = db_path
        self._cache = cache
        self._provider = provider
        self._backfill_days = backfill_days
        self._daily_backfill_days = daily_backfill_days if backfill_days > 0 else 0
        self._retention_days = retention_days
        self._sample_seconds = sample_seconds
        self._flush_seconds = flush_seconds
        self._builder = BarBuilder()
        self._seen: set[str] = set()
        self._pending: set[str] = set()
        self._wake = asyncio.Event()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="history")
        self._tasks: list[asyncio.Task] = []

    @property
    def retention_days(self) -> float:
        return self._retention_days

    async def start(self) -> None:
        self._tasks = [
            asyncio.create_task(self._record_loop(), name="history-recorder"),
            asyncio.create_task(self._backfill_loop(), name="history-backfill"),
        ]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        try:
            await self._in_worker(self.flush)
        except Exception:
            logger.exception("Final bar flush failed")
        await asyncio.to_thread(self._executor.shutdown, wait=True)

    async def _in_worker(self, fn, *args):
        return await asyncio.get_running_loop().run_in_executor(self._executor, fn, *args)

    # --- Recording ---

    def sample(self) -> None:
        """Add the cache's latest prices to the bars, and queue unseen tickers."""
        for ticker, update in self._cache.get_all().items():
            self._builder.add(ticker, update.price, update.timestamp)
            if ticker not in self._seen:
                self._seen.add(ticker)
                self._pending.add(ticker)
                self._wake.set()

    def flush(self) -> None:
        bars = self._builder.drain()
        if bars:
            with closing(connect(self._db_path)) as conn:
                write_recorded(conn, bars)

    def prune_old(self, now: float | None = None) -> int:
        now = time.time() if now is None else now
        cutoff = bucket_start(now - self._retention_days * 86400, "1m")
        with closing(connect(self._db_path)) as conn:
            return prune(conn, "1m", cutoff)

    async def _record_loop(self) -> None:
        last_flush = last_prune = time.monotonic()
        await self._run_guarded(self.prune_old, "Pruning old bars failed")
        while True:
            self.sample()
            now = time.monotonic()
            if now - last_flush >= self._flush_seconds:
                last_flush = now
                await self._run_guarded(self.flush, "Writing bars failed")
            if now - last_prune >= PRUNE_SECONDS:
                last_prune = now
                await self._run_guarded(self.prune_old, "Pruning old bars failed")
            await asyncio.sleep(self._sample_seconds)

    async def _run_guarded(self, fn, message: str) -> None:
        try:
            await self._in_worker(fn)
        except Exception:
            logger.exception(message)

    # --- Backfill ---

    def _requests(self, tickers: list[str], timeframe: str, days: float, now: float):
        """Requests for the stretch before each ticker's earliest stored bar."""
        start = bucket_start(now - days * 86400, timeframe)
        requests = []
        with closing(connect(self._db_path)) as conn:
            for ticker in tickers:
                first = earliest_bar(conn, ticker, timeframe)
                end = first.start_ts if first else bucket_start(now, timeframe)
                anchor = first.open if first else self._cache.get_price(ticker)
                requests.append(BackfillRequest(ticker, timeframe, start, end, anchor))
        return requests

    def _store(self, bars, rollup: bool) -> None:
        with closing(connect(self._db_path)) as conn:
            insert_bars(conn, bars)
            if rollup:
                days: dict[str, set[int]] = {}
                for bar in bars:
                    days.setdefault(bar.ticker, set()).add(bucket_start(bar.start_ts, "1d"))
                for ticker, starts in days.items():
                    rollup_days(conn, ticker, starts)

    async def backfill(self, tickers: list[str], now: float | None = None) -> list[str]:
        """Fill history for the tickers. Returns those that couldn't be done yet.

        Synthetic history needs a price to end at, so an unpriced ticker waits.
        One-minute bars come first; they are rolled into days, and daily history
        is then filled before the earliest day.
        """
        now = time.time() if now is None else now
        needs_anchor = self._provider.origin == "synthetic"
        waiting = [t for t in tickers if needs_anchor and self._cache.get_price(t) is None]
        ready = [t for t in tickers if t not in waiting]
        if not ready or self._backfill_days <= 0:
            return waiting

        for timeframe, days in (("1m", self._backfill_days), ("1d", self._daily_backfill_days)):
            requests = await self._in_worker(self._requests, ready, timeframe, days, now)
            bars = await self._provider.fetch(requests)
            await self._in_worker(self._store, bars, timeframe == "1m")
            logger.info("Backfilled %d %s bars for %d tickers", len(bars), timeframe, len(ready))
        return waiting

    async def _backfill_loop(self) -> None:
        while True:
            await self._wake.wait()
            self._wake.clear()
            # Let a burst of new tickers arrive, so they are generated together
            await asyncio.sleep(self._flush_seconds)
            tickers = sorted(self._pending)
            self._pending.clear()
            try:
                waiting = await self.backfill(tickers)
            except Exception:
                logger.exception("Backfill failed for %s", tickers)
                continue
            for ticker in waiting:
                self._seen.discard(ticker)  # Queued again once it has a price
