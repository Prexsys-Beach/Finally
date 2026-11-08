"""Tests for GBMSimulator."""

import pytest

from app.market.seed_prices import SEED_PRICES
from app.market.simulator import GBMSimulator, pairwise_correlation


class TestGBMSimulator:
    """Unit tests for the GBM price simulator."""

    def test_step_returns_all_tickers(self):
        """Test that step() returns prices for all tickers."""
        sim = GBMSimulator(tickers=["AAPL", "GOOGL"])
        result = sim.step()
        assert set(result.keys()) == {"AAPL", "GOOGL"}

    def test_prices_are_positive(self):
        """GBM prices can never go negative (exp() is always positive)."""
        sim = GBMSimulator(tickers=["AAPL"])
        for _ in range(10_000):
            prices = sim.step()
            assert prices["AAPL"] > 0

    def test_initial_prices_match_seeds(self):
        """Test that initial prices match seed prices."""
        sim = GBMSimulator(tickers=["AAPL"])
        # Before any step, price should be the seed price
        assert sim.get_price("AAPL") == SEED_PRICES["AAPL"]

    def test_add_ticker(self):
        """Test adding a ticker dynamically."""
        sim = GBMSimulator(tickers=["AAPL"])
        sim.add_ticker("TSLA")
        result = sim.step()
        assert "TSLA" in result

    def test_remove_ticker(self):
        """Test removing a ticker."""
        sim = GBMSimulator(tickers=["AAPL", "GOOGL"])
        sim.remove_ticker("GOOGL")
        result = sim.step()
        assert "GOOGL" not in result
        assert "AAPL" in result

    def test_add_duplicate_is_noop(self):
        """Test that adding a duplicate ticker is a no-op."""
        sim = GBMSimulator(tickers=["AAPL"])
        sim.add_ticker("AAPL")
        assert len(sim._tickers) == 1

    def test_remove_nonexistent_is_noop(self):
        """Test that removing a non-existent ticker is a no-op."""
        sim = GBMSimulator(tickers=["AAPL"])
        sim.remove_ticker("NOPE")  # Should not raise

    def test_unknown_ticker_gets_random_seed_price(self):
        """Test that unknown tickers get random seed prices."""
        sim = GBMSimulator(tickers=["ZZZZ"])
        price = sim.get_price("ZZZZ")
        assert price is not None
        assert 50.0 <= price <= 300.0

    def test_empty_step(self):
        """Test stepping with no tickers."""
        sim = GBMSimulator(tickers=[])
        result = sim.step()
        assert result == {}

    def test_prices_change_over_time(self):
        """After many steps, prices should have drifted from their seeds."""
        sim = GBMSimulator(tickers=["AAPL"])
        initial_price = sim.get_price("AAPL")

        for _ in range(1000):
            sim.step()

        final_price = sim.get_price("AAPL")
        # Price should have changed (extremely unlikely to be exactly the seed)
        assert final_price != initial_price

    def test_cholesky_rebuilds_on_add(self):
        """Test that Cholesky matrix is rebuilt when tickers are added."""
        sim = GBMSimulator(tickers=["AAPL"])
        assert sim._cholesky is None  # Only 1 ticker, no correlation matrix
        sim.add_ticker("GOOGL")
        assert sim._cholesky is not None  # Now 2 tickers, matrix exists

    def test_cholesky_none_with_one_ticker(self):
        """Test that Cholesky is None with only one ticker."""
        sim = GBMSimulator(tickers=["AAPL"])
        assert sim._cholesky is None

    def test_get_price_returns_none_for_unknown(self):
        """Test that get_price returns None for unknown ticker."""
        sim = GBMSimulator(tickers=["AAPL"])
        assert sim.get_price("UNKNOWN") is None

    def test_pairwise_correlation_tech_stocks(self):
        """Test that tech stocks have high correlation."""
        corr = pairwise_correlation("AAPL", "GOOGL")
        assert corr == 0.6

    def test_pairwise_correlation_finance_stocks(self):
        """Test that finance stocks have moderate correlation."""
        corr = pairwise_correlation("JPM", "V")
        assert corr == 0.5

    def test_pairwise_correlation_tsla(self):
        """Test that TSLA has lower correlation with everything."""
        corr = pairwise_correlation("TSLA", "AAPL")
        assert corr == 0.3
        corr = pairwise_correlation("TSLA", "JPM")
        assert corr == 0.3

    def test_pairwise_correlation_cross_sector(self):
        """Test cross-sector correlation."""
        corr = pairwise_correlation("AAPL", "JPM")
        assert corr == 0.3

    def test_default_dt_is_reasonable(self):
        """Test that default dt is a reasonable small value."""
        assert 0 < GBMSimulator.DEFAULT_DT < 0.0001

    def test_prices_rounded_to_two_decimals(self):
        """Test that prices are rounded to 2 decimal places."""
        sim = GBMSimulator(tickers=["AAPL"])
        result = sim.step()
        price_str = str(result["AAPL"])
        # Check that we have at most 2 decimal places
        if '.' in price_str:
            decimal_part = price_str.split('.')[1]
            assert len(decimal_part) <= 2


class TestRandomEvents:
    """Jumps move prices 2-5% either way without pulling them down over time."""

    def jumps(self, monkeypatch, moves):
        """Prices after forced jumps of the given (size, sign) moves, with no GBM drift."""
        sequence = iter(moves)
        current = {}

        def uniform(low, high):
            current["move"] = next(sequence)
            return current["move"][0]

        monkeypatch.setattr("app.market.simulator.random.random", lambda: 0.0)
        monkeypatch.setattr("app.market.simulator.random.uniform", uniform)
        monkeypatch.setattr("app.market.simulator.random.choice", lambda _: current["move"][1])
        sim = GBMSimulator(tickers=["AAPL"], dt=0.0, start_prices={"AAPL": 100.0})
        return [sim.step()["AAPL"] for _ in moves], sim

    def test_rise_and_drop_of_the_same_size_cancel(self, monkeypatch):
        prices, sim = self.jumps(monkeypatch, [(0.03, 1), (0.03, -1)])
        assert prices == [103.0, 100.0]
        assert sim.get_price("AAPL") == 100.0

    def test_drop_size(self, monkeypatch):
        prices, _ = self.jumps(monkeypatch, [(0.05, -1)])
        assert prices == [round(100 / 1.05, 2)]  # 95.24, a 4.8% drop

    def test_no_drift_over_many_jumps(self, monkeypatch):
        moves = [(0.02 + 0.03 * i / 999, sign) for i in range(1000) for sign in (1, -1)]
        _, sim = self.jumps(monkeypatch, moves)
        assert sim.get_price("AAPL") == pytest.approx(100.0)
