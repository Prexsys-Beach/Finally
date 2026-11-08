"""HistoryService: recording from the cache and gap-only backfill."""

import asyncio
from contextlib import closing

import pytest

from app.db import connect, init_db
from app.market.bars import Bar, insert_bars, recent_bars, write_recorded
from app.market.cache import PriceCache
from app.market.history import SyntheticHistory
from app.market.recorder import HistoryService

DAY = 86400
NOW = 1_700_006_400 + 12 * 3600 + 30  # Midday, 30s into a minute


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "history.db"
    init_db(path)
    return path


@pytest.fixture
def cache():
    cache = PriceCache()
    cache.update("AAPL", 190.0, timestamp=NOW)
    cache.update("MSFT", 420.0, timestamp=NOW)
    return cache


def service(db_path, cache, **kwargs):
    options = {"backfill_days": 1, "daily_backfill_days": 10} | kwargs
    return HistoryService(db_path, cache, SyntheticHistory(seed=1), **options)


def bars(db_path, ticker="AAPL", timeframe="1m"):
    with closing(connect(db_path)) as conn:
        return recent_bars(conn, ticker, timeframe, 100000)


class TestRecording:
    def test_samples_become_stored_bars(self, db_path, cache):
        history = service(db_path, cache)
        history.sample()
        cache.update("AAPL", 191.0, timestamp=NOW + 5)
        history.sample()
        history.flush()
        (minute,) = bars(db_path)
        assert (minute.open, minute.high, minute.close, minute.origin) == (
            190.0,
            191.0,
            191.0,
            "recorded",
        )
        assert bars(db_path, timeframe="1d")[0].close == 191.0

    def test_prunes_old_minutes(self, db_path, cache):
        history = service(db_path, cache, retention_days=2)
        with closing(connect(db_path)) as conn:
            write_recorded(conn, [Bar("AAPL", "1m", NOW - 3 * DAY, 1, 1, 1, 1, "recorded")])
        assert history.prune_old(now=NOW) == 1
        assert bars(db_path) == []
        assert len(bars(db_path, timeframe="1d")) == 1


class TestBackfill:
    async def test_fills_minutes_then_days_ending_at_the_live_price(self, db_path, cache):
        history = service(db_path, cache)
        assert await history.backfill(["AAPL", "MSFT"], now=NOW) == []

        minutes = bars(db_path)
        assert len(minutes) == 1440
        assert minutes[0].start_ts == NOW - 30 - DAY
        assert minutes[-1].start_ts == NOW - 30 - 60  # Stops before the live minute
        assert minutes[-1].close == 190.0
        assert {b.origin for b in minutes} == {"synthetic"}

        days = bars(db_path, timeframe="1d")
        assert [d.start_ts for d in days] == [
            NOW - 12 * 3600 - 30 - i * DAY for i in range(10, -1, -1)
        ]
        # Days covered by minutes are rolled up from them, and history before leads into them
        assert days[-1].close == 190.0
        assert days[-3].close == days[-2].open
        assert len(bars(db_path, "MSFT")) == 1440

    async def test_only_fills_before_existing_history(self, db_path, cache):
        with closing(connect(db_path)) as conn:
            write_recorded(conn, [Bar("AAPL", "1m", NOW - 30, 189.5, 190, 189, 190, "recorded")])
        history = service(db_path, cache)
        await history.backfill(["AAPL"], now=NOW)

        minutes = bars(db_path)
        assert minutes[-1].origin == "recorded"
        assert minutes[-2].close == 189.5  # Leads into the recorded bar's open

        before = len(minutes)
        await service(db_path, cache).backfill(["AAPL"], now=NOW + 60)  # A restart
        assert len(bars(db_path)) == before

    async def test_unpriced_ticker_waits(self, db_path, cache):
        assert await service(db_path, cache).backfill(["AAPL", "PYPL"], now=NOW) == ["PYPL"]
        assert bars(db_path, "PYPL") == []

    async def test_can_be_turned_off(self, db_path, cache):
        assert await service(db_path, cache, backfill_days=0).backfill(["AAPL"], now=NOW) == []
        assert bars(db_path) == []

    async def test_existing_daily_history_is_kept(self, db_path, cache):
        old_day = Bar("AAPL", "1d", NOW - 12 * 3600 - 30 - 5 * DAY, 1, 1, 1, 1, "vendor")
        with closing(connect(db_path)) as conn:
            insert_bars(conn, [old_day])
        await service(db_path, cache).backfill(["AAPL"], now=NOW)
        days = bars(db_path, timeframe="1d")
        assert old_day in days
        assert days[0].start_ts == old_day.start_ts - 5 * DAY


class TestLifecycle:
    async def test_runs_in_the_background(self, db_path):
        cache = PriceCache()
        cache.update("AAPL", 190.0)  # Now, as the service's own clock sees it
        cache.update("MSFT", 420.0)
        history = service(db_path, cache, sample_seconds=0.01, flush_seconds=0.05)
        await history.start()
        for _ in range(200):
            if len(bars(db_path, "MSFT")) > 1:
                break
            await asyncio.sleep(0.05)
        await history.stop()
        assert len(bars(db_path, "MSFT")) > 1
        assert bars(db_path, "AAPL")[-1].origin == "recorded"
