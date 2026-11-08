"""History providers: synthetic history matches the simulator; Massive bars parse."""

import numpy as np
import pytest
from massive.exceptions import BadResponse
from massive.rest.models import Agg

from app.market.bars import TIMEFRAME_SECONDS
from app.market.history import (
    BAR_MODELS,
    EVENT_SIZE,
    BackfillRequest,
    MassiveHistory,
    SyntheticHistory,
    simulate_ohlc,
)
from app.market.simulator import GBMSimulator

T0 = 1_700_006_400  # A UTC midnight


def bar_variance(sigma: float, timeframe: str, events: float) -> float:
    """Expected variance of one bar's log return: diffusion plus jumps."""
    seconds = BAR_MODELS[timeframe].trading_seconds
    diffusion = sigma**2 * seconds / GBMSimulator.TRADING_SECONDS_PER_YEAR
    low, high = EVENT_SIZE
    jump_size_sq = (high**3 - low**3) / (3 * (high - low))  # E[size^2], uniform
    return diffusion + events * jump_size_sq


class TestSimulateOhlc:
    def test_bars_are_valid_and_continuous(self):
        ohlc = simulate_ohlc(["AAPL", "TSLA"], 500, "1m", np.random.default_rng(1))
        assert ohlc.shape == (500, 2, 4)
        opens, highs, lows, closes = np.moveaxis(ohlc, -1, 0)
        assert np.all(highs >= np.maximum(opens, closes))
        assert np.all(lows <= np.minimum(opens, closes))
        assert np.all(lows > 0)
        assert np.allclose(opens[1:], closes[:-1])  # Each bar opens at the last close
        assert np.allclose(opens[0], 1.0)

    @pytest.mark.parametrize("timeframe", ["1m", "1d"])
    def test_volatility_matches_the_simulator_without_events(self, timeframe):
        ohlc = simulate_ohlc(["AAPL"], 4000, timeframe, np.random.default_rng(2), events_per_bar=0)
        measured = np.diff(np.log(ohlc[:, 0, 3])).std()
        assert measured == pytest.approx(np.sqrt(bar_variance(0.22, timeframe, 0)), rel=0.05)

    @pytest.mark.parametrize("timeframe", ["1m", "1d"])
    def test_volatility_includes_jumps(self, timeframe):
        ohlc = simulate_ohlc(
            ["AAPL"], 20000, timeframe, np.random.default_rng(3), events_per_bar=0.5
        )
        measured = np.diff(np.log(ohlc[:, 0, 3])).std()
        expected = bar_variance(0.22, timeframe, 0.5)
        assert measured == pytest.approx(np.sqrt(expected), rel=0.08)

    @pytest.mark.parametrize(("timeframe", "bars"), [("1m", 7200), ("1d", 365)])
    def test_default_history_stays_realistic(self, timeframe, bars):
        """TSLA, the most volatile ticker, stays within about 3 sigma over the default depth.

        Its 50% volatility over 365 daily bars is a 60% standard deviation in log price.
        """
        for seed in range(20):
            ohlc = simulate_ohlc(["TSLA"], bars, timeframe, np.random.default_rng(seed))
            assert 0.15 < ohlc[:, 0, 2].min() and ohlc[:, 0, 1].max() < 6.5

    def test_keeps_sector_correlations(self):
        tickers = ["AAPL", "MSFT", "JPM"]
        ohlc = simulate_ohlc(tickers, 5000, "1m", np.random.default_rng(4), events_per_bar=0)
        corr = np.corrcoef(np.diff(np.log(ohlc[:, :, 3]), axis=0).T)
        assert corr[0, 1] == pytest.approx(0.6, abs=0.05)  # Tech with tech
        assert corr[0, 2] == pytest.approx(0.3, abs=0.05)  # Across sectors


class TestSyntheticHistory:
    def request(self, ticker="AAPL", anchor=190.0, bars=60, timeframe="1m", start=T0):
        end = start + bars * TIMEFRAME_SECONDS[timeframe]
        return BackfillRequest(ticker, timeframe, start, end, anchor)

    def test_fills_the_range_and_ends_at_the_anchor(self):
        bars = SyntheticHistory(seed=1).generate([self.request()])
        assert [b.start_ts for b in bars] == [T0 + i * 60 for i in range(60)]
        assert bars[-1].close == 190.0
        assert {b.origin for b in bars} == {"synthetic"}
        assert all(b.low <= b.open <= b.high and b.low <= b.close <= b.high for b in bars)

    def test_same_range_is_generated_together(self):
        bars = SyntheticHistory(seed=1).generate(
            [self.request("AAPL", 190.0), self.request("MSFT", 420.0)]
        )
        closes = {b.ticker: b.close for b in bars}
        assert closes == {"AAPL": 190.0, "MSFT": 420.0}
        assert len(bars) == 120

    def test_skips_requests_without_an_anchor_or_range(self):
        provider = SyntheticHistory(seed=1)
        assert provider.generate([self.request(anchor=None), self.request(bars=0)]) == []

    def test_seeded_runs_repeat(self):
        assert SyntheticHistory(seed=7).generate([self.request()]) == SyntheticHistory(
            seed=7
        ).generate([self.request()])

    async def test_fetch(self):
        bars = await SyntheticHistory(seed=1).fetch([self.request(timeframe="1d", bars=3)])
        assert [b.start_ts for b in bars] == [T0, T0 + 86400, T0 + 2 * 86400]


def agg(timestamp_ms, close=100.0, **fields):
    values = {"open": close, "high": close, "low": close, "close": close} | fields
    return Agg(timestamp=timestamp_ms, volume=1000, **values)


class TestMassiveHistory:
    def test_daily_bars_move_to_utc_midnight(self):
        request = BackfillRequest("AAPL", "1d", T0, T0 + 2 * 86400, None)
        us_midnight = (T0 + 5 * 3600) * 1000  # 00:00 New York is 05:00 UTC
        (bar,) = MassiveHistory.to_bars(request, [agg(us_midnight, 101.0)])
        assert (bar.start_ts, bar.close, bar.origin) == (T0, 101.0, "vendor")

    def test_drops_bars_outside_the_range_and_unusable_ones(self):
        request = BackfillRequest("AAPL", "1m", T0, T0 + 180, None)
        aggs = [
            agg((T0 - 60) * 1000),
            agg(T0 * 1000, 100.0),
            agg((T0 + 60) * 1000, 0.0),
            agg(None),
            agg((T0 + 120) * 1000, 102.0, high=103.0),
            agg((T0 + 180) * 1000),
        ]
        bars = MassiveHistory.to_bars(request, aggs)
        assert [(b.start_ts, b.high) for b in bars] == [(T0, 100.0), (T0 + 120, 103.0)]

    async def test_fetch_skips_failed_requests(self):
        provider = MassiveHistory("test-key", call_spacing=0)
        calls = []

        def list_aggs(ticker, multiplier, timespan, start, end, **kwargs):
            calls.append((ticker, timespan, start, end))
            if ticker == "MSFT":
                raise BadResponse('{"status":"NOT_AUTHORIZED"}')
            return iter([agg(start, 100.0)])

        provider._client.list_aggs = list_aggs
        bars = await provider.fetch(
            [
                BackfillRequest("AAPL", "1m", T0, T0 + 60, None),
                BackfillRequest("MSFT", "1m", T0, T0 + 60, None),
                BackfillRequest("NVDA", "1d", T0, T0, None),  # Empty range: no call
            ]
        )
        assert [(b.ticker, b.close) for b in bars] == [("AAPL", 100.0)]
        assert calls[0] == ("AAPL", "minute", T0 * 1000, (T0 + 60) * 1000 - 1)
        assert len(calls) == 2
