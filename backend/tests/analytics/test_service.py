"""Analytics service over a real database: bars, positions, cash and settings."""

from contextlib import closing

import numpy as np
import pytest

from app.analytics.service import portfolio_analytics, ticker_analytics
from app.db import connect, init_db
from app.market import PriceCache
from app.market.bars import Bar, insert_bars
from app.settings import update_settings

DAY = 86400
T0 = 1_700_006_400


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / "analytics.db"
    init_db(path)
    with closing(connect(path)) as connection:
        connection.execute("DELETE FROM watchlist")
        yield connection


def add_daily(conn, ticker, closes, origin="synthetic", start=T0):
    insert_bars(
        conn,
        [
            Bar(ticker, "1d", start + i * DAY, c, c * 1.01, c * 0.99, c, origin)
            for i, c in enumerate(closes)
        ],
    )


def watch(conn, *tickers):
    for t in tickers:
        conn.execute(
            "INSERT INTO watchlist (id, user_id, ticker, added_at) VALUES (?, 'default', ?, '')",
            (t, t),
        )


def hold(conn, ticker, quantity, avg_cost, cash):
    conn.execute(
        """
        INSERT INTO positions (id, user_id, ticker, quantity, avg_cost, updated_at)
        VALUES (?, 'default', ?, ?, ?, '')
        """,
        (ticker, ticker, quantity, avg_cost),
    )
    conn.execute("UPDATE users_profile SET cash_balance = ?", (cash,))


def walk(seed, n=120, sigma=0.02):
    return list(100 * np.exp(np.cumsum(np.random.default_rng(seed).normal(0, sigma, n))))


class TestTickerAnalytics:
    def test_series_and_latest_values(self, conn):
        add_daily(conn, "AAPL", walk(1, n=200))
        result = ticker_analytics(conn, "AAPL", "1d", limit=100, retention_days=30)
        assert result["bars"] == 150  # 100 plus the warm-up
        assert result["origins"] == {"synthetic": 150}
        series = result["series"]
        assert len(series["time"]) == 100 and series["time"][-1] == T0 + 199 * DAY
        assert all(v is not None for v in series["ema_50"])  # Warmed up before the window
        latest = result["latest"]
        assert latest["close"] == pytest.approx(walk(1, n=200)[-1], abs=1e-4)  # Rounded
        assert latest["sma_20"] == pytest.approx(np.mean(walk(1, n=200)[-20:]), rel=1e-6)
        assert 0 <= latest["rsi_14"] <= 100
        assert set(result["signals"]) == {"rsi", "bollinger", "trend", "macd"}

    def test_short_history_has_gaps_not_errors(self, conn):
        add_daily(conn, "AAPL", [100, 101, 102])
        result = ticker_analytics(conn, "AAPL", "1d", limit=100, retention_days=30)
        assert result["latest"]["sma_20"] is None
        assert result["signals"]["rsi"] is None
        assert result["series"]["sma_20"] == [None, None, None]

    def test_no_history(self, conn):
        result = ticker_analytics(conn, "ZZZ", "1d", limit=100, retention_days=30)
        assert result["bars"] == 0 and result["latest"] is None

    def test_signals(self, conn):
        add_daily(conn, "UP", [100 * 1.02**i for i in range(100)])  # Accelerating
        signals = ticker_analytics(conn, "UP", "1d", 50, 30)["signals"]
        assert signals == {
            "rsi": "overbought",
            "bollinger": "inside",
            "trend": "above_sma",
            "macd": "bullish",
        }


class TestPortfolioAnalytics:
    def setup_market(self, conn):
        watch(conn, "AAPL", "MSFT", "JPM")
        for seed, ticker in enumerate(["AAPL", "MSFT", "JPM"]):
            add_daily(conn, ticker, walk(seed))
        cache = PriceCache()
        for ticker in ["AAPL", "MSFT", "JPM"]:
            cache.update(ticker, 100.0)
        return cache

    def test_without_positions(self, conn):
        cache = self.setup_market(conn)
        result = portfolio_analytics(conn, cache, "1d", 30)
        assert result["correlation"]["tickers"] == ["AAPL", "JPM", "MSFT"]
        matrix = np.array(result["correlation"]["matrix"])
        np.testing.assert_allclose(np.diag(matrix), 1)
        np.testing.assert_allclose(matrix, matrix.T)
        assert result["volatility"] is None and result["value_at_risk"] is None
        assert any("No positions" in note for note in result["notes"])
        assert result["cash_weight"] == 1

    def test_with_positions(self, conn):
        cache = self.setup_market(conn)
        hold(conn, "AAPL", 50, 100, cash=5000)  # Half invested
        result = portfolio_analytics(conn, cache, "1d", 30)

        assert result["total_value"] == 10000 and result["cash_weight"] == 0.5
        assert result["returns"] == 119
        aapl = np.diff(np.log(walk(0)))
        assert result["volatility"] == pytest.approx(
            0.5 * aapl.std(ddof=1) * np.sqrt(252), rel=1e-5
        )
        (position,) = result["positions"]
        assert position["weight"] == 0.5
        assert result["beta"] == pytest.approx(0.5 * position["beta"], rel=1e-3)
        var = result["value_at_risk"]
        assert var["horizon"] == "1 trading day"
        assert var["parametric"]["amount"] == pytest.approx(
            var["parametric"]["percent"] * 100, abs=0.01
        )
        assert 0 < var["historical"]["percent"] < 10
        assert result["expected_shortfall"]["parametric"]["percent"] > var["parametric"]["percent"]
        assert result["concentration"] == {
            "top": {"ticker": "AAPL", "weight": 0.5},
            "herfindahl": 1.0,
            "effective_positions": 1.0,
        }

    def test_holding_the_whole_benchmark_has_beta_one(self, conn):
        cache = self.setup_market(conn)
        for ticker in ["AAPL", "MSFT", "JPM"]:
            hold(conn, ticker, 10, 100, cash=0)
        assert portfolio_analytics(conn, cache, "1d", 30)["beta"] == pytest.approx(1)

    def test_position_without_history_is_left_out(self, conn):
        cache = self.setup_market(conn)
        cache.update("PYPL", 50.0)
        hold(conn, "PYPL", 10, 50, cash=9500)
        result = portfolio_analytics(conn, cache, "1d", 30)
        assert result["volatility"] is None
        assert any("PYPL" in note for note in result["notes"])

    def test_synthetic_history_drops_out_after_the_cutoff(self, conn):
        cache = self.setup_market(conn)
        recent = T0 + 120 * DAY
        for seed, ticker in enumerate(["AAPL", "MSFT", "JPM"]):
            add_daily(conn, ticker, walk(seed + 10, n=40), origin="recorded", start=recent)
        assert set(portfolio_analytics(conn, cache, "1d", 30)["origins"]) == {"recorded"}

        update_settings(conn, {"synthetic_history_cutoff": "quarter"})  # 40 days isn't enough
        assert set(portfolio_analytics(conn, cache, "1d", 30)["origins"]) == {
            "recorded",
            "synthetic",
        }

    def test_performance_needs_a_day_of_snapshots(self, conn):
        cache = self.setup_market(conn)
        rows = [
            (f"s{i}", 10000 + (i % 7) * 50, f"2026-01-0{1 + i // 24}T{i % 24:02d}:00:00+00:00")
            for i in range(48)
        ]
        conn.executemany(
            "INSERT INTO portfolio_snapshots (id, user_id, total_value, recorded_at) VALUES (?, 'default', ?, ?)",
            rows,
        )
        performance = portfolio_analytics(conn, cache, "1d", 30)["performance"]
        assert performance["max_drawdown"]["percent"] == pytest.approx(300 / 10300 * 100, rel=1e-4)
        assert performance["sharpe"] is not None

        conn.execute("DELETE FROM portfolio_snapshots WHERE recorded_at > '2026-01-01T05'")
        performance = portfolio_analytics(conn, cache, "1d", 30)["performance"]
        assert performance["sharpe"] is None and "a day" in performance["note"]
