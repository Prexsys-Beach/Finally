"""Bar building, storage, rollup and selection for analysis."""

from contextlib import closing

import pytest

from app.db import connect, init_db
from app.market.bars import (
    Bar,
    BarBuilder,
    bars_for_analysis,
    bucket_start,
    earliest_bar,
    effective_cutoff_days,
    insert_bars,
    prune,
    real_coverage_seconds,
    recent_bars,
    rollup_days,
    write_recorded,
)

DAY = 86400
T0 = 1_700_006_400  # A UTC midnight


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / "bars.db"
    init_db(path)
    with closing(connect(path)) as connection:
        yield connection


def bar(start, close=100.0, origin="recorded", ticker="AAPL", timeframe="1m", high=None, low=None):
    return Bar(ticker, timeframe, start, close, high or close, low or close, close, origin)


class TestBucketStart:
    def test_minutes_and_days(self):
        assert bucket_start(T0 + 125.7, "1m") == T0 + 120
        assert bucket_start(T0 + DAY - 1, "1d") == T0


class TestBarBuilder:
    def test_builds_ohlc_within_a_minute(self):
        builder = BarBuilder()
        for offset, price in [(1, 100), (10, 105), (20, 95), (59, 101)]:
            builder.add("AAPL", price, T0 + offset)
        assert builder.drain() == [Bar("AAPL", "1m", T0, 100, 105, 95, 101, "recorded")]

    def test_new_minute_keeps_the_finished_bar(self):
        builder = BarBuilder()
        builder.add("AAPL", 100, T0 + 1)
        builder.add("AAPL", 102, T0 + 59)
        builder.add("AAPL", 103, T0 + 61)
        assert [(b.start_ts, b.close) for b in builder.drain()] == [(T0, 102), (T0 + 60, 103)]

    def test_repeated_timestamp_is_not_new_data(self):
        builder = BarBuilder()
        builder.add("AAPL", 100, T0 + 1)
        builder.drain()
        builder.add("AAPL", 100, T0 + 1)
        assert builder.drain() == []

    def test_out_of_order_sample_is_ignored(self):
        builder = BarBuilder()
        builder.add("AAPL", 100, T0 + 61)
        builder.add("AAPL", 50, T0 + 1)
        assert [(b.start_ts, b.low) for b in builder.drain()] == [(T0 + 60, 100)]

    def test_drain_only_returns_changes(self):
        builder = BarBuilder()
        builder.add("AAPL", 100, T0 + 1)
        builder.add("MSFT", 200, T0 + 1)
        builder.drain()
        builder.add("MSFT", 201, T0 + 2)
        assert [b.ticker for b in builder.drain()] == ["MSFT"]


class TestStorage:
    def test_recorded_bar_merges_and_feeds_its_day(self, conn):
        write_recorded(conn, [bar(T0, 100, high=101, low=99)])
        write_recorded(conn, [bar(T0, 102, high=103, low=100)])  # Same minute, later
        write_recorded(conn, [bar(T0 + 60, 98, high=98, low=97)])

        minute = recent_bars(conn, "AAPL", "1m", 10)
        assert [(b.high, b.low, b.close) for b in minute] == [(103, 99, 102), (98, 97, 98)]
        (day,) = recent_bars(conn, "AAPL", "1d", 10)
        assert (day.start_ts, day.open, day.high, day.low, day.close) == (T0, 100, 103, 97, 98)
        assert day.origin == "recorded"

    def test_recording_into_a_synthetic_day_keeps_it_synthetic(self, conn):
        insert_bars(conn, [bar(T0, 100, origin="synthetic", timeframe="1d")])
        write_recorded(conn, [bar(T0 + 60, 101)])
        assert earliest_bar(conn, "AAPL", "1d").origin == "synthetic"

    def test_vendor_bars_are_never_overwritten(self, conn):
        insert_bars(conn, [bar(T0, 100, origin="vendor")])
        write_recorded(conn, [bar(T0, 150)])
        assert earliest_bar(conn, "AAPL", "1m") == bar(T0, 100, origin="vendor")

    def test_backfill_never_overwrites(self, conn):
        write_recorded(conn, [bar(T0, 100)])
        insert_bars(conn, [bar(T0, 50, origin="synthetic"), bar(T0 - 60, 51, origin="synthetic")])
        assert [(b.close, b.origin) for b in recent_bars(conn, "AAPL", "1m", 10)] == [
            (51, "synthetic"),
            (100, "recorded"),
        ]

    def test_recent_bars_are_the_latest_oldest_first(self, conn):
        insert_bars(conn, [bar(T0 + i * 60, 100 + i) for i in range(5)])
        assert [b.close for b in recent_bars(conn, "AAPL", "1m", 3)] == [102, 103, 104]
        assert recent_bars(conn, "MSFT", "1m", 3) == []

    def test_recent_bars_by_origin(self, conn):
        insert_bars(conn, [bar(T0, origin="synthetic"), bar(T0 + 60, origin="recorded")])
        bars = recent_bars(conn, "AAPL", "1m", 10, origins=["recorded"])
        assert [b.origin for b in bars] == ["recorded"]

    def test_prune(self, conn):
        insert_bars(conn, [bar(T0), bar(T0 + 60), bar(T0, timeframe="1d")])
        assert prune(conn, "1m", T0 + 60) == 1
        assert [b.start_ts for b in recent_bars(conn, "AAPL", "1m", 10)] == [T0 + 60]
        assert len(recent_bars(conn, "AAPL", "1d", 10)) == 1


class TestRollup:
    def test_builds_days_from_minutes(self, conn):
        insert_bars(
            conn,
            [
                bar(T0, 100, high=104, low=99, origin="synthetic"),
                bar(T0 + 60, 103, high=103, low=96, origin="synthetic"),
                bar(T0 + DAY, 110, origin="vendor"),
            ],
        )
        rollup_days(conn, "AAPL", [T0, T0 + DAY, T0 + 2 * DAY])
        days = recent_bars(conn, "AAPL", "1d", 10)
        assert [(d.open, d.high, d.low, d.close, d.origin) for d in days] == [
            (100, 104, 96, 103, "synthetic"),
            (110, 110, 110, 110, "vendor"),
        ]

    @pytest.mark.parametrize(
        ("origins", "expected"),
        [
            (["recorded", "recorded"], "recorded"),
            (["vendor", "recorded"], "recorded"),
            (["synthetic", "recorded"], "synthetic"),
            (["vendor", "vendor"], "vendor"),
        ],
    )
    def test_day_origin(self, conn, origins, expected):
        insert_bars(conn, [bar(T0 + i * 60, origin=o) for i, o in enumerate(origins)])
        rollup_days(conn, "AAPL", [T0])
        assert earliest_bar(conn, "AAPL", "1d").origin == expected

    def test_leaves_vendor_days_alone(self, conn):
        insert_bars(conn, [bar(T0, 200, origin="vendor", timeframe="1d"), bar(T0, 100)])
        rollup_days(conn, "AAPL", [T0])
        assert earliest_bar(conn, "AAPL", "1d").close == 200


class TestAnalysisSelection:
    def test_coverage_counts_only_real_bars(self, conn):
        insert_bars(conn, [bar(T0 + i * 60, origin="synthetic") for i in range(10)])
        assert real_coverage_seconds(conn, "AAPL", "1m") == 0
        insert_bars(conn, [bar(T0 + 600, origin="recorded"), bar(T0 + 720, origin="vendor")])
        assert real_coverage_seconds(conn, "AAPL", "1m") == 180

    def test_cutoff_is_capped_by_minute_retention(self):
        assert effective_cutoff_days(365, "1m", retention_days=30) == 29
        assert effective_cutoff_days(7, "1m", retention_days=30) == 7
        assert effective_cutoff_days(365, "1d", retention_days=30) == 365
        assert effective_cutoff_days(None, "1m", retention_days=30) is None
        assert effective_cutoff_days(1, "1m", retention_days=2) == 1

    def test_synthetic_used_until_real_history_covers_the_cutoff(self, conn):
        insert_bars(conn, [bar(T0 - DAY, timeframe="1d", origin="synthetic")])
        insert_bars(conn, [bar(T0 + i * DAY, timeframe="1d") for i in range(6)])

        def origins(cutoff):
            selected = bars_for_analysis(conn, "AAPL", "1d", 100, cutoff, retention_days=30)
            return {b.origin for b in selected}

        assert origins(7) == {"synthetic", "recorded"}  # 6 days of real history
        assert origins(6) == {"recorded"}
        assert origins(None) == {"synthetic", "recorded"}  # 'never'
