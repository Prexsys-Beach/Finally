"""Indicators against hand-worked values, and proof that none looks ahead."""

import math

import numpy as np
import pytest

from app.analytics import indicators as ind

nan = math.nan


def same(actual, expected):
    np.testing.assert_allclose(np.asarray(actual, float), np.asarray(expected, float), rtol=1e-9)


class TestAverages:
    def test_sma(self):
        same(ind.sma([1, 2, 3, 4, 5], 3), [nan, nan, 2, 3, 4])

    def test_sma_too_short(self):
        same(ind.sma([1, 2], 3), [nan, nan])

    def test_ema_seeds_with_the_sma(self):
        # alpha = 0.5: seed (2+4+6)/3 = 4, then 0.5*8 + 0.5*4 = 6, then 0.5*12 + 0.5*6 = 9
        same(ind.ema([2, 4, 6, 8, 12], 3), [nan, nan, 4, 6, 9])

    def test_ema_skips_a_leading_warm_up(self):
        same(ind.ema([nan, 2, 4, 6, 8], 3), [nan, nan, nan, 4, 6])
        same(ind.ema([nan, nan], 3), [nan, nan])


class TestRsi:
    def test_wilder_smoothing(self):
        # Changes +1, -1, +2. Seed (n=2): gains 0.5, losses 0.5 -> 50.
        # Then gains (0.5 + 2)/2 = 1.25, losses (0.5 + 0)/2 = 0.25, RS 5 -> 83.33
        same(ind.rsi([10, 11, 10, 12], 2), [nan, nan, 50, 100 - 100 / 6])

    def test_only_gains_is_100_and_flat_is_50(self):
        assert ind.rsi(range(1, 20), 14)[-1] == 100
        assert ind.rsi([5] * 20, 14)[-1] == 50

    def test_stays_in_range(self):
        values = ind.rsi(100 * np.exp(np.cumsum(np.random.default_rng(1).normal(0, 0.01, 500))))
        valid = values[~np.isnan(values)]
        assert valid.size == 500 - 14 and valid.min() >= 0 and valid.max() <= 100


class TestBandsAndRanges:
    def test_bollinger(self):
        middle, upper, lower = ind.bollinger([1, 2, 3], 3, 2)
        spread = 2 * math.sqrt(2 / 3)  # Population standard deviation
        same(middle, [nan, nan, 2])
        same(upper, [nan, nan, 2 + spread])
        same(lower, [nan, nan, 2 - spread])

    def test_atr_uses_gaps_from_the_previous_close(self):
        # True ranges: 1, then max(1, |11 - 9.5|, |10 - 9.5|) = 1.5, then 1.5
        result = ind.atr([10, 11, 12], [9, 10, 11], [9.5, 10.5, 11.5], 2)
        same(result, [nan, 1.25, (1.25 + 1.5) / 2])

    def test_macd_is_flat_on_a_flat_series(self):
        line, signal, histogram = ind.macd([50.0] * 60)
        assert np.isnan(line[24]) and line[25] == 0
        assert np.isnan(signal[32]) and signal[33] == 0
        same(histogram[33:], np.zeros(27))

    def test_macd_histogram_is_line_minus_signal(self):
        closes = 100 + np.cumsum(np.random.default_rng(2).normal(0, 1, 100))
        line, signal, histogram = ind.macd(closes)
        same(histogram[40:], (line - signal)[40:])


class TestVolatility:
    def test_annualizes_by_timeframe(self):
        closes = 100 * np.exp(np.cumsum([0.01, -0.01] * 50))
        returns = np.diff(np.log(closes))
        expected = returns.std(ddof=1)
        assert ind.realized_volatility(closes, "1d") == pytest.approx(expected * math.sqrt(252))
        assert ind.realized_volatility(closes, "1m") == pytest.approx(
            expected * math.sqrt(252 * 390)
        )

    def test_needs_two_returns(self):
        assert math.isnan(ind.realized_volatility([1, 2], "1d"))


class TestNoLookAhead:
    """Computed on the series up to bar k, every indicator equals its full-series value at k."""

    closes = 100 * np.exp(np.cumsum(np.random.default_rng(3).normal(0, 0.01, 200)))
    highs = closes * 1.01
    lows = closes * 0.99

    @pytest.mark.parametrize(
        "compute",
        [
            lambda c, h, lo: ind.sma(c, 20),
            lambda c, h, lo: ind.ema(c, 50),
            lambda c, h, lo: ind.rsi(c, 14),
            lambda c, h, lo: ind.macd(c)[0],
            lambda c, h, lo: ind.macd(c)[1],
            lambda c, h, lo: ind.bollinger(c)[1],
            lambda c, h, lo: ind.bollinger(c)[2],
            lambda c, h, lo: ind.atr(h, lo, c, 14),
        ],
    )
    def test_truncation_changes_nothing(self, compute):
        full = compute(self.closes, self.highs, self.lows)
        for k in (10, 35, 60, 120, 199):
            part = compute(self.closes[:k], self.highs[:k], self.lows[:k])
            same(part, full[:k])
