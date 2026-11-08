"""Forecasts: the fan's spread matches theory, there is no drift, and the
service handles cash, missing history and data modes."""

import math
import time
from contextlib import closing

import numpy as np
import pytest

from app.analytics import forecast as fc
from app.analytics.service import forecast
from app.db import connect, init_db
from app.market import PriceCache
from app.market.bars import Bar, insert_bars
from app.market.simulator import GBMSimulator

YEAR = GBMSimulator.TRADING_SECONDS_PER_YEAR


class TestMath:
    def test_estimate_scales_minute_returns_to_seconds(self):
        rng = np.random.default_rng(1)
        returns = rng.normal(0, 0.001, 5000)
        closes = {
            "A": list(zip(range(0, 5001 * 60, 60), 100 * np.exp(np.cumsum(np.r_[0, returns]))))
        }
        est = fc.estimate(closes)
        assert est.tickers == ["A"] and est.returns == 5000
        assert est.covariance_per_second[0, 0] == pytest.approx(0.001**2 / 60, rel=0.05)

    def test_spread_matches_theory_and_mean_stays_put(self):
        sigma, seconds = 0.4, 86400  # 40% a year over a simulator day
        variance = sigma**2 / YEAR
        paths = fc.simulate(
            np.array([100.0]),
            np.array([[variance]]),
            seconds,
            np.random.default_rng(2),
            paths=40000,
        )
        final = paths[:, -1, 0]
        spread = sigma * math.sqrt(seconds / YEAR)
        assert final.mean() == pytest.approx(100, rel=0.005)  # No drift
        assert np.log(final).std() == pytest.approx(spread, rel=0.02)
        p95 = np.percentile(final, 95)
        assert p95 == pytest.approx(100 * math.exp(-(spread**2) / 2 + 1.6449 * spread), rel=0.01)

    def test_keeps_correlation_and_shape(self):
        cov = np.array([[1.0, 0.6], [0.6, 1.0]]) * 1e-7
        paths = fc.simulate(
            np.array([50.0, 80.0]), cov, 3600, np.random.default_rng(3), paths=20000
        )
        assert paths.shape == (20000, fc.CHECKPOINTS, 2)
        logs = np.log(paths[:, -1, :])
        assert np.corrcoef(logs.T)[0, 1] == pytest.approx(0.6, abs=0.02)

    def test_same_seed_same_fan(self):
        args = (np.array([100.0]), np.array([[1e-8]]), 3600)
        a = fc.simulate(*args, np.random.default_rng(9))
        b = fc.simulate(*args, np.random.default_rng(9))
        np.testing.assert_array_equal(a, b)

    def test_summary(self):
        values = fc.simulate(
            np.array([100.0]), np.array([[1e-7]]), 86400, np.random.default_rng(4)
        )[:, :, 0]
        result = fc.summarize(values, 100.0, level=110.0)
        finals = [result["bands"][f"p{p}"][-1] for p in fc.PERCENTILES]
        assert finals == sorted(finals) and len(result["bands"]["p50"]) == fc.CHECKPOINTS
        assert 0.5 <= result["probability_of_loss"] < 0.6  # Median sits a touch below today
        level = result["level"]
        assert level["direction"] == "above"
        assert level["probability_of_touching"] >= level["probability_at_horizon"] > 0
        assert fc.summarize(values, 100.0, level=90.0)["level"]["direction"] == "below"

    def test_trading_time_by_mode(self):
        assert fc.trading_seconds("1d", "simulated") == 86400
        assert fc.trading_seconds("1d", "seeded") == 86400
        assert fc.trading_seconds("1d", "live") == 23400
        assert fc.trading_seconds("1w", "eod") == 5 * 23400


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / "forecast.db"
    init_db(path)
    with closing(connect(path)) as connection:
        connection.execute("DELETE FROM watchlist")
        yield connection


def minute_bars(conn, ticker, sigma_per_minute, seed, n=600, origin="recorded"):
    start = int(time.time() // 60 * 60) - (n + 5) * 60
    closes = 100 * np.exp(np.cumsum(np.random.default_rng(seed).normal(0, sigma_per_minute, n)))
    insert_bars(
        conn, [Bar(ticker, "1m", start + i * 60, c, c, c, c, origin) for i, c in enumerate(closes)]
    )


def hold(conn, ticker, quantity, cash):
    conn.execute(
        "INSERT INTO positions (id, user_id, ticker, quantity, avg_cost, updated_at) VALUES (?, 'default', ?, ?, 100, '')",
        (ticker, ticker, quantity),
    )
    conn.execute("UPDATE users_profile SET cash_balance = ?", (cash,))


class TestService:
    def test_ticker_forecast(self, conn):
        minute_bars(conn, "AAPL", 0.001, seed=1)
        cache = PriceCache()
        cache.update("AAPL", 190.0)
        result = forecast(
            conn,
            cache,
            "AAPL",
            "1d",
            30,
            mode="simulated",
            now=1000.0,
            rng=np.random.default_rng(5),
        )
        assert result["current_value"] == 190.0 and result["returns_used"] == 599
        assert result["times"][0] == 1000 + 3600 and result["times"][-1] == 1000 + 86400
        assert result["volatility"] == pytest.approx(0.001 * math.sqrt(YEAR / 60), rel=0.1)
        assert result["bands"]["p5"][-1] < 190 < result["bands"]["p95"][-1]
        assert result["origins"] == {"recorded": 600} and result["notes"] == []

    def test_real_data_spans_fewer_trading_hours(self, conn):
        minute_bars(conn, "AAPL", 0.001, seed=1)
        cache = PriceCache()
        cache.update("AAPL", 190.0)

        def width(mode):
            r = forecast(conn, cache, "AAPL", "1d", 30, mode=mode, rng=np.random.default_rng(6))
            return math.log(r["bands"]["p95"][-1] / r["bands"]["p5"][-1])

        assert width("simulated") / width("live") == pytest.approx(
            math.sqrt(86400 / 23400), rel=0.05
        )

    def test_portfolio_includes_cash(self, conn):
        minute_bars(conn, "AAPL", 0.001, seed=1)
        cache = PriceCache()
        cache.update("AAPL", 100.0)
        hold(conn, "AAPL", 50, cash=5000)
        result = forecast(conn, cache, "portfolio", "1d", 30, rng=np.random.default_rng(7))
        assert result["current_value"] == 10000
        stock_only = forecast(conn, cache, "AAPL", "1d", 30, rng=np.random.default_rng(7))
        # Half in cash: about half the volatility of the stock alone
        assert result["volatility"] == pytest.approx(stock_only["volatility"] / 2, rel=0.01)

    def test_cash_only_is_flat(self, conn):
        result = forecast(conn, PriceCache(), "portfolio", "1w", 30)
        assert set(result["bands"]["p5"]) == set(result["bands"]["p95"]) == {10000.0}
        assert result["probability_of_loss"] == 0
        assert result["notes"] == ["Only cash: the value won't change."]

    def test_position_without_history_is_held_flat(self, conn):
        minute_bars(conn, "AAPL", 0.001, seed=1)
        cache = PriceCache()
        cache.update("AAPL", 100.0)
        cache.update("PYPL", 50.0)
        hold(conn, "AAPL", 10, cash=1000)
        hold(conn, "PYPL", 20, cash=1000)
        result = forecast(conn, cache, "portfolio", "1d", 30, rng=np.random.default_rng(8))
        assert result["notes"] == ["Held at today's price for lack of history: PYPL."]
        assert result["current_value"] == 3000

    def test_not_enough_history(self, conn):
        minute_bars(conn, "AAPL", 0.001, seed=1, n=10)
        cache = PriceCache()
        cache.update("AAPL", 100.0)
        result = forecast(conn, cache, "AAPL", "1d", 30)
        assert result["notes"] == ["Not enough price history to forecast yet."]
        assert result["bands"]["p5"][-1] == result["bands"]["p95"][-1] == 100.0

    def test_unpriced_ticker(self, conn):
        with pytest.raises(ValueError, match="No price for ZZZZ"):
            forecast(conn, PriceCache(), "ZZZZ", "1d", 30)

    def test_stable_within_a_minute(self, conn):
        minute_bars(conn, "AAPL", 0.001, seed=1)
        cache = PriceCache()
        cache.update("AAPL", 100.0)
        a = forecast(conn, cache, "AAPL", "1h", 30, now=6000.0)
        b = forecast(conn, cache, "AAPL", "1h", 30, now=6030.0)
        assert a["bands"] == b["bands"]
