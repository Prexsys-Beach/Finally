"""Backtests on hand-built prices: timing, no look-ahead, costs and the figures."""

import numpy as np
import pytest

from app.analytics import backtest as bt


class TestTiming:
    def test_decisions_are_carried_out_one_bar_later(self):
        # Decided at bar 0's close, traded at bar 1's close, held from bar 1 to bar 2
        held = bt.held_positions(np.array([1.0, 0, 1, 1]))
        np.testing.assert_array_equal(held, [0, 0, 1, 0])

    def test_a_jump_on_the_decision_bar_is_not_captured(self):
        """A strategy that sees the jump at bar 3 can only buy at bar 4's close."""
        closes = np.array([100.0, 100, 100, 150, 150, 150])

        def after_jump(c, params):
            return (c > 120).astype(float), {}

        bt.STRATEGIES["after_jump"] = ("test", after_jump)
        try:
            result = bt.run(closes, "after_jump")
        finally:
            del bt.STRATEGIES["after_jump"]
        assert result.total_return == 0  # Bought at 150, still 150
        assert result.trades == 1 and result.open_position

    def test_buy_and_hold_is_the_price_change(self):
        closes = np.array([50.0, 40, 60, 55, 80])
        result = bt.run(closes, "buy_and_hold")
        assert result.total_return == pytest.approx(80 / 40 - 1)
        assert result.buy_and_hold_return == pytest.approx(80 / 40 - 1)
        assert result.exposure == 1 and result.trades == 1


class TestNoLookAhead:
    @pytest.mark.parametrize(
        ("strategy", "params"),
        [("sma_crossover", {"fast": 3, "slow": 8}), ("rsi_reversion", {"period": 5})],
    )
    def test_changing_the_future_changes_nothing_before_it(self, strategy, params):
        closes = 100 * np.exp(np.cumsum(np.random.default_rng(1).normal(0, 0.02, 120)))
        changed = closes.copy()
        changed[80:] *= np.random.default_rng(2).uniform(0.5, 1.5, 40)
        full = bt.STRATEGIES[strategy][1](closes, params)[0]
        other = bt.STRATEGIES[strategy][1](changed, params)[0]
        np.testing.assert_array_equal(full[:80], other[:80])
        a = bt.run(closes, strategy, params).equity
        b = bt.run(changed, strategy, params).equity
        # equity[j - 1] is the value at bar j, so a[:79] covers bars 1-79: all before the change
        np.testing.assert_allclose(a[:79], b[:79])


class TestStrategies:
    def test_sma_crossover_on_a_v_shape(self):
        # Falls 10 -> 4, then rises 4 -> 12. With fast 2 and slow 4, the fast average
        # first exceeds the slow one at bar 8 (5.5 vs 5.0), so the buy is at bar 9's
        # close (7) and is held to the end (12). Buy and hold starts at bar 1 (9).
        closes = np.array([10.0, 9, 8, 7, 6, 5, 4, 5, 6, 7, 8, 9, 10, 11, 12])
        decisions, used = bt.sma_crossover(closes, {"fast": 2, "slow": 4})
        assert used == {"fast": 2, "slow": 4}
        assert list(decisions[:8]) == [0] * 8 and list(decisions[8:]) == [1] * 7
        result = bt.run(closes, "sma_crossover", {"fast": 2, "slow": 4})
        assert result.total_return == pytest.approx(12 / 7 - 1)
        assert result.buy_and_hold_return == pytest.approx(12 / 9 - 1)
        assert result.trades == 1 and result.open_position
        assert result.max_drawdown == 0

    def test_rsi_reversion_buys_low_and_sells_high(self):
        closes = np.array([100.0, 98, 96, 94, 92, 90, 93, 96, 99, 102, 105, 108, 104])
        decisions, _ = bt.rsi_reversion(closes, {"period": 3, "buy_below": 30, "sell_above": 70})
        assert decisions[3] == 1  # RSI hits 0 on the way down
        result = bt.run(closes, "rsi_reversion", {"period": 3})
        assert result.trades == 1 and result.winning_trades == 1 and not result.open_position
        assert result.total_return > 0

    @pytest.mark.parametrize(
        ("strategy", "params", "error"),
        [
            ("sma_crossover", {"fast": 30, "slow": 10}, "fast must be shorter than slow"),
            ("sma_crossover", {"fast": 1}, "fast must be a whole number"),
            ("sma_crossover", {"slow": "30"}, "slow must be a whole number"),
            ("rsi_reversion", {"buy_below": 80, "sell_above": 20}, "buy_below must be lower"),
            ("rsi_reversion", {"period": True}, "period must be a whole number"),
            ("momentum", {}, "Unknown strategy: momentum"),
        ],
    )
    def test_rejects_bad_requests(self, strategy, params, error):
        with pytest.raises(bt.BacktestError, match=error):
            bt.run(np.arange(1.0, 60), strategy, params)

    def test_needs_three_bars_and_sane_slippage(self):
        with pytest.raises(bt.BacktestError, match="Not enough"):
            bt.run([1.0, 2.0], "buy_and_hold")
        with pytest.raises(bt.BacktestError, match="slippage_bps"):
            bt.run([1.0, 2.0, 3.0], "buy_and_hold", slippage_bps=500)


class TestCostsAndFigures:
    def test_slippage_is_paid_on_each_trade(self):
        closes = np.array([10.0, 9, 8, 7, 6, 5, 4, 5, 6, 7, 8, 9, 10, 11, 12])
        free = bt.run(closes, "sma_crossover", {"fast": 2, "slow": 4})
        costly = bt.run(closes, "sma_crossover", {"fast": 2, "slow": 4}, slippage_bps=50)
        assert (1 + costly.total_return) == pytest.approx((1 + free.total_return) * 0.995)

    def test_drawdown_and_wins(self):
        # In for a fall then out: a losing trade with a drawdown
        closes = np.array([100.0, 100, 100, 80, 80, 80])

        def first_bars(c, params):
            return np.array([1.0, 1, 0, 0, 0, 0]), {}

        bt.STRATEGIES["first_bars"] = ("test", first_bars)
        try:
            result = bt.run(closes, "first_bars")
        finally:
            del bt.STRATEGIES["first_bars"]
        assert result.total_return == pytest.approx(-0.2)
        assert result.max_drawdown == pytest.approx(0.2)
        assert (result.trades, result.winning_trades, result.open_position) == (1, 0, False)

    def test_curve_is_thinned_but_keeps_the_end(self):
        equity = np.linspace(1, 2, 1000)
        points = bt.curve(equity, list(range(1000)))
        assert len(points) <= bt.MAX_CURVE_POINTS + 1
        assert points[0] == [0, 1.0] and points[-1] == [999, 2.0]
