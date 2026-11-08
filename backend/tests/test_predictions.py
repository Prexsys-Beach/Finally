"""The prediction journal: recording, resolution against real prices, and scoring."""

import random
from contextlib import closing
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from app import predictions as pred
from app.db import connect, init_db
from app.market import PriceCache
from app.market.bars import Bar, bucket_start, insert_bars

T0 = datetime(2026, 3, 2, 15, 0, 30, tzinfo=UTC)


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / "predictions.db"
    init_db(path)
    with closing(connect(path)) as connection:
        yield connection


@pytest.fixture
def cache():
    cache = PriceCache()
    cache.update("NVDA", 800.0)
    return cache


def source(mode="simulated", tickers=("NVDA",)):
    return SimpleNamespace(mode=mode, get_tickers=lambda: list(tickers))


def make(conn, cache, direction="up", confidence=0.7, horizon=60, mode="simulated", now=T0, seed=1):
    return pred.record(
        conn,
        cache,
        source(mode),
        "NVDA",
        direction,
        confidence,
        horizon,
        chat_message_id="msg-1",
        now=now,
        rng=random.Random(seed),
    )


def bar_at(conn, moment, close, origin="recorded", ticker="NVDA"):
    start = bucket_start(moment.timestamp(), "1m")
    insert_bars(conn, [Bar(ticker, "1m", start, close, close, close, close, origin)])


def rows(conn):
    return conn.execute("SELECT * FROM predictions ORDER BY predictor").fetchall()


class TestRecording:
    def test_records_the_call_and_a_coin_flip_baseline(self, conn, cache):
        made = make(conn, cache)
        assert made["reference_price"] == 800.0
        assert made["resolves_at"] == (T0 + timedelta(minutes=60)).isoformat()
        assistant, baseline = rows(conn)
        assert (assistant["predictor"], assistant["confidence"], assistant["data_mode"]) == (
            "assistant",
            0.7,
            "simulated",
        )
        assert baseline["predictor"] == "baseline" and baseline["confidence"] == 0.5
        assert baseline["direction"] in ("up", "down")
        assert assistant["pair_id"] == baseline["id"] and baseline["pair_id"] == assistant["id"]
        assert assistant["chat_message_id"] == "msg-1"
        assert baseline["horizon_minutes"] == 60 and baseline["reference_price"] == 800.0

    def test_baseline_is_a_fair_coin(self, conn, cache):
        rng = random.Random(7)
        for _ in range(400):
            pred.record(conn, cache, source(), "NVDA", "up", 0.6, 60, now=T0, rng=rng)
        ups = conn.execute(
            "SELECT COUNT(*) FROM predictions WHERE predictor = 'baseline' AND direction = 'up'"
        ).fetchone()[0]
        assert 160 < ups < 240

    @pytest.mark.parametrize(
        ("kwargs", "error"),
        [
            ({"direction": "sideways"}, "Direction must be up or down."),
            ({"confidence": 0.4}, "Confidence must be between 0.5"),
            ({"confidence": 65}, "Confidence must be between 0.5"),
            ({"confidence": True}, "Confidence must be between 0.5"),
            ({"horizon": 0}, "Horizon must be 1 to 10080"),
            ({"horizon": 20000}, "Horizon must be 1 to 10080"),
        ],
    )
    def test_rejects_bad_calls(self, conn, cache, kwargs, error):
        with pytest.raises(pred.PredictionError, match=error):
            make(conn, cache, **kwargs)
        assert rows(conn) == []

    def test_needs_a_tracked_priced_ticker(self, conn, cache):
        with pytest.raises(pred.PredictionError, match="isn't tracked"):
            pred.record(conn, cache, source(), "AAPL", "up", 0.6, 60)
        with pytest.raises(pred.PredictionError, match="No price for MSFT"):
            pred.record(conn, cache, source(tickers=["MSFT"]), "MSFT", "up", 0.6, 60)


class TestResolution:
    def due(self, minutes=60, seconds=10):
        return T0 + timedelta(minutes=minutes, seconds=seconds)

    @pytest.mark.parametrize(
        ("direction", "close", "outcome"),
        [("up", 810, "hit"), ("up", 790, "miss"), ("down", 790, "hit"), ("down", 810, "miss")],
    )
    def test_against_the_recorded_bar(self, conn, cache, direction, close, outcome):
        make(conn, cache, direction=direction)
        bar_at(conn, T0 + timedelta(minutes=60), close)
        cache.update("NVDA", 9999.0)  # The bar wins over the live price
        assert pred.resolve_due(conn, cache, now=self.due()) == 2
        assistant = rows(conn)[0]
        assert (assistant["outcome"], assistant["resolved_price"]) == (outcome, close)

    def test_not_before_it_is_due(self, conn, cache):
        make(conn, cache)
        assert pred.resolve_due(conn, cache, now=T0 + timedelta(minutes=59)) == 0
        assert rows(conn)[0]["outcome"] is None

    def test_unchanged_price_is_void(self, conn, cache):
        make(conn, cache)
        bar_at(conn, T0 + timedelta(minutes=60), 800.0)
        pred.resolve_due(conn, cache, now=self.due())
        assert {(r["outcome"], r["note"]) for r in rows(conn)} == {
            ("void", "The price didn't move.")
        }

    def test_synthetic_bars_never_settle_a_prediction(self, conn, cache):
        make(conn, cache)
        bar_at(conn, T0 + timedelta(minutes=60), 900.0, origin="synthetic")
        cache.update("NVDA", 790.0)
        pred.resolve_due(conn, cache, now=self.due(seconds=30))
        assert rows(conn)[0]["resolved_price"] == 790.0  # The fresh live price instead

    def test_late_without_a_recorded_price_is_void(self, conn, cache):
        make(conn, cache)
        pred.resolve_due(conn, cache, now=self.due(minutes=70))  # The app was down
        assert {r["outcome"] for r in rows(conn)} == {"void"}
        assert "No price was recorded" in rows(conn)[0]["note"]

    def test_settled_once(self, conn, cache):
        make(conn, cache)
        bar_at(conn, T0 + timedelta(minutes=60), 810.0)
        pred.resolve_due(conn, cache, now=self.due())
        assert pred.resolve_due(conn, cache, now=self.due(minutes=90)) == 0


def scored(outcomes):
    """Rows for score(): (confidence, outcome) pairs."""
    return [{"confidence": c, "outcome": o} for c, o in outcomes]


class TestScoring:
    def test_wilson_interval(self):
        assert pred.wilson_interval(5, 10) == pytest.approx((0.2366, 0.7634), abs=1e-4)
        assert pred.wilson_interval(0, 0) is None
        low, high = pred.wilson_interval(10, 10)
        assert high == pytest.approx(1.0) and 0.7 < low < 0.75

    def test_hit_rate_brier_and_calibration(self):
        result = pred.score(
            scored(
                [
                    (0.9, "hit"),
                    (0.9, "miss"),
                    (0.6, "hit"),
                    (1.0, "hit"),
                    (0.7, "void"),
                    (0.8, None),
                ]
            )
        )
        assert (result["made"], result["settled"], result["hits"]) == (6, 4, 3)
        assert (result["void"], result["pending"], result["hit_rate"]) == (1, 1, 0.75)
        # (0.1^2 + 0.9^2 + 0.4^2 + 0^2) / 4
        assert result["brier"] == pytest.approx((0.01 + 0.81 + 0.16 + 0) / 4)
        assert result["calibration"] == [
            {"range": [0.6, 0.7], "count": 1, "stated": 0.6, "observed": 1.0},
            {
                "range": [0.9, 1.0],
                "count": 3,
                "stated": pytest.approx(0.9333, abs=1e-4),
                "observed": pytest.approx(0.6667, abs=1e-4),
            },
        ]

    def test_coin_flip_brier_is_a_quarter(self):
        assert pred.score(scored([(0.5, "hit"), (0.5, "miss")]))["brier"] == 0.25

    def test_nothing_settled(self):
        result = pred.score(scored([(0.6, None)]))
        assert result["hit_rate"] is None and result["brier"] is None
        assert result["calibration"] == []

    def test_stats_keep_data_modes_apart(self, conn, cache):
        make(conn, cache, mode="simulated")
        make(conn, cache, mode="live")
        bar_at(conn, T0 + timedelta(minutes=60), 810.0)
        pred.resolve_due(conn, cache, now=T0 + timedelta(minutes=61))
        stats = pred.stats(conn)
        assert set(stats["modes"]) == {"live", "simulated"}
        for mode in ("live", "simulated"):
            assert stats["modes"][mode]["assistant"]["made"] == 1
            assert stats["modes"][mode]["baseline"]["made"] == 1

    def test_recent_pairs_each_call_with_its_baseline(self, conn, cache):
        make(conn, cache, direction="down", now=T0)
        make(conn, cache, direction="up", now=T0 + timedelta(minutes=5))
        latest = pred.recent(conn)
        assert [p["direction"] for p in latest] == ["up", "down"]
        assert all(p["baseline_direction"] in ("up", "down") for p in latest)


class TestControlGroup:
    """On a random walk, always calling "up" scores about 50%: the baseline the
    journal measures against. A clearly better score here would mean a bug."""

    def test_random_walk_is_a_coin_flip(self, conn):
        cache = PriceCache()
        rng = np.random.default_rng(11)
        prices = 100 * np.exp(np.cumsum(rng.normal(0, 0.002, 2000)))
        cache.update("NVDA", float(prices[0]))
        for i in range(0, 1990, 5):
            now = T0 + timedelta(minutes=i)
            cache.update("NVDA", round(float(prices[i]), 2))
            pred.record(conn, cache, source(), "NVDA", "up", 0.6, 1, now=now, rng=random.Random(i))
            bar_at(conn, now + timedelta(minutes=1), round(float(prices[i + 1]), 2))
        pred.resolve_due(conn, cache, now=T0 + timedelta(minutes=2000))
        assistant = pred.stats(conn)["modes"]["simulated"]["assistant"]
        low, high = assistant["hit_rate_interval"]
        assert assistant["settled"] > 350
        assert low < 0.5 < high
