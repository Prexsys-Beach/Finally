"""Trade rules, valuation and snapshots, with prices set directly."""

import sqlite3
from pathlib import Path

import pytest

from app import portfolio, watchlist
from app.db import connect, init_db
from app.market import PriceCache
from app.market.simulator import SimulatorDataSource


class NoPriceSource(SimulatorDataSource):
    """Like a live Massive source: tracks a new ticker without pricing it yet."""

    def __init__(self, cache: PriceCache) -> None:
        super().__init__(cache)
        self.tickers: list[str] = []

    async def add_ticker(self, ticker: str) -> None:
        self.tickers.append(ticker)

    async def remove_ticker(self, ticker: str) -> None:
        self.tickers.remove(ticker)

    def get_tickers(self) -> list[str]:
        return list(self.tickers)


@pytest.fixture
def conn(tmp_path: Path):
    path = tmp_path / "test.db"
    init_db(path)
    connection = connect(path)
    yield connection
    connection.close()


@pytest.fixture
def cache() -> PriceCache:
    return PriceCache()


def trade_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) AS n FROM trades").fetchone()["n"]


class TestBuy:
    def test_reduces_cash_and_opens_position(self, conn, cache):
        cache.update("AAPL", 100.0)
        portfolio.execute_trade(conn, "AAPL", "buy", 10, 100.0)

        result = portfolio.get_portfolio(conn, cache)
        assert result["cash_balance"] == 9000.0
        assert result["total_value"] == 10000.0
        assert result["positions"][0]["quantity"] == 10
        assert trade_count(conn) == 1

    def test_averages_cost_across_buys(self, conn, cache):
        cache.update("AAPL", 200.0)
        portfolio.execute_trade(conn, "AAPL", "buy", 10, 100.0)
        portfolio.execute_trade(conn, "AAPL", "buy", 10, 200.0)

        position = portfolio.get_portfolio(conn, cache)["positions"][0]
        assert position["quantity"] == 20
        assert position["avg_cost"] == 150.0
        assert position["unrealized_pnl"] == 1000.0
        assert position["unrealized_pnl_percent"] == pytest.approx(33.3333)

    def test_fractional_shares(self, conn, cache):
        cache.update("AAPL", 100.0)
        portfolio.execute_trade(conn, "AAPL", "buy", 0.5, 100.0)
        assert portfolio.get_cash(conn) == 9950.0

    def test_can_spend_all_cash(self, conn):
        portfolio.execute_trade(conn, "AAPL", "buy", 100, 100.0)
        assert portfolio.get_cash(conn) == 0.0

    def test_insufficient_cash_changes_nothing(self, conn, cache):
        with pytest.raises(portfolio.TradeError, match="Insufficient cash"):
            portfolio.execute_trade(conn, "AAPL", "buy", 101, 100.0)

        assert portfolio.get_cash(conn) == 10000.0
        assert portfolio.get_portfolio(conn, cache)["positions"] == []
        assert trade_count(conn) == 0


class TestSell:
    def test_partial_sale_keeps_avg_cost(self, conn, cache):
        cache.update("AAPL", 120.0)
        portfolio.execute_trade(conn, "AAPL", "buy", 10, 100.0)
        portfolio.execute_trade(conn, "AAPL", "sell", 4, 120.0)

        position = portfolio.get_portfolio(conn, cache)["positions"][0]
        assert position["quantity"] == 6
        assert position["avg_cost"] == 100.0
        assert portfolio.get_cash(conn) == 9480.0

    def test_selling_everything_closes_position(self, conn, cache):
        portfolio.execute_trade(conn, "AAPL", "buy", 10, 100.0)
        portfolio.execute_trade(conn, "AAPL", "sell", 10, 100.0)
        assert portfolio.get_portfolio(conn, cache)["positions"] == []

    def test_float_dust_closes_position(self, conn, cache):
        portfolio.execute_trade(conn, "AAPL", "buy", 0.1, 100.0)
        portfolio.execute_trade(conn, "AAPL", "buy", 0.2, 100.0)
        portfolio.execute_trade(conn, "AAPL", "sell", 0.3, 100.0)
        assert portfolio.get_portfolio(conn, cache)["positions"] == []

    def test_selling_at_a_loss(self, conn, cache):
        portfolio.execute_trade(conn, "AAPL", "buy", 10, 100.0)
        portfolio.execute_trade(conn, "AAPL", "sell", 10, 80.0)
        assert portfolio.get_cash(conn) == 9800.0

    def test_cannot_sell_more_than_owned(self, conn):
        portfolio.execute_trade(conn, "AAPL", "buy", 1, 100.0)
        with pytest.raises(portfolio.TradeError, match="Insufficient shares"):
            portfolio.execute_trade(conn, "AAPL", "sell", 2, 100.0)
        assert trade_count(conn) == 1

    def test_cannot_sell_unowned(self, conn):
        with pytest.raises(portfolio.TradeError, match="you own 0"):
            portfolio.execute_trade(conn, "AAPL", "sell", 1, 100.0)


class TestValuation:
    def test_unpriced_position_counts_at_cost(self, conn, cache):
        portfolio.execute_trade(conn, "AAPL", "buy", 10, 100.0)

        result = portfolio.get_portfolio(conn, cache)
        assert result["positions"][0]["current_price"] is None
        assert result["total_value"] == 10000.0

    def test_snapshot_skipped_while_a_position_is_unpriced(self, conn, cache):
        portfolio.execute_trade(conn, "AAPL", "buy", 10, 100.0)
        assert portfolio.record_snapshot(conn, cache) is None
        assert portfolio.get_history(conn) == []

    def test_history_is_oldest_first_and_limited(self, conn, cache):
        cache.update("AAPL", 100.0)
        portfolio.execute_trade(conn, "AAPL", "buy", 10, 100.0)
        for price in (110.0, 120.0, 130.0):
            cache.update("AAPL", price)
            portfolio.record_snapshot(conn, cache)

        values = [s["total_value"] for s in portfolio.get_history(conn, limit=2)]
        assert values == [10200.0, 10300.0]


class TestTracking:
    async def test_unpriced_ticker_stays_tracked_for_retry(self, conn, cache):
        source = NoPriceSource(cache)
        with pytest.raises(portfolio.PriceUnavailableError):
            await portfolio.place_trade(conn, cache, source, "PYPL", "buy", 1)
        assert source.get_tickers() == ["PYPL"]

    async def test_rejected_trade_releases_new_ticker(self, conn, cache):
        source = NoPriceSource(cache)
        cache.update("PYPL", 50.0)
        with pytest.raises(portfolio.TradeError):
            await portfolio.place_trade(conn, cache, source, "PYPL", "sell", 1)
        assert source.get_tickers() == []

    async def test_closing_unwatched_position_releases_ticker(self, conn, cache):
        source = NoPriceSource(cache)
        cache.update("PYPL", 50.0)
        await portfolio.place_trade(conn, cache, source, "PYPL", "buy", 1)
        assert source.get_tickers() == ["PYPL"]

        await portfolio.place_trade(conn, cache, source, "PYPL", "sell", 1)
        assert source.get_tickers() == []

    async def test_held_ticker_survives_watchlist_removal(self, conn, cache):
        source = NoPriceSource(cache)
        source.tickers = ["AAPL"]
        cache.update("AAPL", 100.0)
        await portfolio.place_trade(conn, cache, source, "AAPL", "buy", 1)

        await watchlist.remove_from_watchlist(conn, source, "AAPL")

        assert source.get_tickers() == ["AAPL"]
        assert "AAPL" in watchlist.tracked_tickers(conn)
