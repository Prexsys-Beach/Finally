"""Risk math against hand-worked values."""

import math

import numpy as np
import pytest

from app.analytics import risk


class TestAlignment:
    def test_uses_only_shared_times(self):
        tickers, times, returns = risk.aligned_returns(
            {
                "A": [(0, 100.0), (60, 110.0), (120, 121.0)],
                "B": [(60, 50.0), (120, 25.0), (180, 30.0)],
                "C": [(60, 1.0)],  # Too short
            }
        )
        assert tickers == ["A", "B"]
        assert list(times) == [120]
        np.testing.assert_allclose(returns, [[math.log(1.1), math.log(0.5)]])

    def test_nothing_shared(self):
        tickers, times, returns = risk.aligned_returns(
            {"A": [(0, 1.0), (60, 2.0)], "B": [(120, 1.0), (180, 2.0)]}
        )
        assert tickers == ["A", "B"] and times.size == 0 and returns.shape == (0, 2)


class TestCorrelationAndBeta:
    def test_correlation(self):
        a = np.array([0.01, -0.02, 0.03, 0.0])
        flat = np.zeros(4)
        corr = risk.correlation_matrix(np.column_stack([a, -a, 2 * a, flat]))
        np.testing.assert_allclose(
            corr,
            [[1, -1, 1, 0], [-1, 1, -1, 0], [1, -1, 1, 0], [0, 0, 0, 1]],
            atol=1e-12,
        )

    def test_beta(self):
        bench = np.array([0.01, -0.02, 0.03, 0.0, 0.01])
        assert risk.beta(2 * bench, bench) == pytest.approx(2)
        assert risk.beta(bench, bench) == pytest.approx(1)
        assert math.isnan(risk.beta(bench, np.zeros(5)))


class TestValueAtRisk:
    def test_historical(self):
        returns = np.arange(-50, 50) / 1000  # -5% to +4.9%
        var, es = risk.historical_var_es(returns)
        # 5th percentile by linear interpolation: index 4.95 -> -0.04505
        assert var == pytest.approx(0.04505)
        assert es == pytest.approx(0.048)  # Mean of -5% .. -4.6%
        assert risk.historical_var_es(returns, scale=2)[0] == pytest.approx(0.0901)

    def test_parametric(self):
        var, es = risk.parametric_var_es(0.01)
        assert var == pytest.approx(0.016449, abs=1e-6)
        assert es == pytest.approx(0.020627, abs=1e-6)
        assert risk.parametric_var_es(0.01, scale=3)[0] == pytest.approx(3 * var)

    def test_matches_a_normal_sample(self):
        returns = np.random.default_rng(1).normal(0, 0.01, 200_000)
        hist_var, hist_es = risk.historical_var_es(returns)
        param_var, param_es = risk.parametric_var_es(returns.std())
        assert hist_var == pytest.approx(param_var, rel=0.02)
        assert hist_es == pytest.approx(param_es, rel=0.02)


class TestConcentrationAndPerformance:
    def test_herfindahl(self):
        assert risk.herfindahl([100]) == 1
        assert risk.herfindahl([50, 50]) == 0.5
        assert risk.herfindahl([75, 25]) == pytest.approx(0.625)
        assert math.isnan(risk.herfindahl([]))

    def test_max_drawdown(self):
        assert risk.max_drawdown([100, 120, 90, 130, 100]) == (0.25, 1, 2)
        assert risk.max_drawdown([1, 2, 3]) == (0.0, 0, 0)

    def test_sharpe_uses_elapsed_time(self):
        # Returns ln1.1 over 1s and ln1.1 over 2s: per-second rate 2L/3,
        # variance 2(L/3)^2/3, so the ratio is sqrt(6) per sqrt(second)
        assert risk.sharpe_ratio([100, 110, 121], [0, 1, 3], 1) == pytest.approx(math.sqrt(6))
        assert risk.sharpe_ratio([100, 110, 121], [0, 1, 3], 4) == pytest.approx(2 * math.sqrt(6))

    def test_sharpe_of_a_round_trip_is_zero(self):
        assert risk.sharpe_ratio([100, 110, 100], [0, 1, 2], 1) == pytest.approx(0)

    def test_sharpe_undefined_when_flat_or_short(self):
        assert math.isnan(risk.sharpe_ratio([100, 100, 100], [0, 1, 2], 1))
        assert math.isnan(risk.sharpe_ratio([100, 110], [0, 1], 1))
