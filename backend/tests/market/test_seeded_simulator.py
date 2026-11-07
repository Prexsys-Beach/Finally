"""The simulator starting from real Massive closes.

Runs the real massive client and models. Only the HTTP transport is faked.
"""

import os
from unittest.mock import patch

import pytest

from app.market.cache import PriceCache
from app.market.factory import create_market_data_source
from app.market.massive_client import DailyCloses, MassiveDataSource
from app.market.seed_prices import SEED_PRICES
from app.market.simulator import GBMSimulator, SimulatorDataSource

from .test_massive_real_models import (
    FORBIDDEN,
    GROUPED_PATH,
    FakeTransport,
    bar,
    real_client,
    recent_weekdays,
)

RATE_LIMITED = (429, {"status": "ERROR", "error": "Too many requests"})


def market(days: dict[str, tuple]) -> FakeTransport:
    """Answer grouped calls by date. Unlisted days have no data."""

    def grouped(url: str) -> tuple:
        return days.get(url.rsplit("/", 1)[1], (200, {"status": "OK", "results": []}))

    return FakeTransport([(GROUPED_PATH, grouped)])


def session(*bars: dict) -> tuple:
    return 200, {"status": "OK", "results": list(bars)}


def two_sessions() -> FakeTransport:
    """Today is too recent for the plan, as on the free tier."""
    newest, latest, previous = recent_weekdays(3)
    return market(
        {
            newest.isoformat(): FORBIDDEN,
            latest.isoformat(): session(bar("AAPL", 270.0), bar("JMKE", 19.0)),
            previous.isoformat(): session(bar("AAPL", 265.0), bar("JMKE", 20.0)),
        }
    )


def make_closes(transport: FakeTransport, **kwargs) -> DailyCloses:
    closes = DailyCloses("test-key", **kwargs)
    closes._client = real_client(transport)
    return closes


async def started(transport: FakeTransport, tickers: list[str]):
    cache = PriceCache()
    source = SimulatorDataSource(cache, update_interval=60, closes=make_closes(transport))
    await source.start(tickers)
    return source, cache


class TestSeededSimulator:
    async def test_tickers_start_at_their_real_close(self):
        source, cache = await started(two_sessions(), ["AAPL", "jmke"])
        assert source.mode == "seeded"
        assert cache.get_price("AAPL") == 270.0
        assert cache.get_price("JMKE") == 19.0
        await source.stop()

    async def test_daily_change_is_measured_from_the_close_before(self):
        source, cache = await started(two_sessions(), ["JMKE"])
        update = cache.get("JMKE")
        assert update.previous_close == 20.0
        assert update.day_change_percent == pytest.approx(-5.0)
        await source.stop()

    async def test_added_ticker_uses_its_close_with_no_extra_request(self):
        transport = two_sessions()
        source, cache = await started(transport, ["AAPL"])
        calls = len(transport.urls)
        await source.add_ticker("JMKE")
        assert cache.get_price("JMKE") == 19.0
        assert len(transport.urls) == calls
        await source.stop()

    async def test_ticker_with_no_close_stays_unpriced(self):
        source, cache = await started(two_sessions(), ["AAPL", "NOPE"])
        await source.add_ticker("ALSONO")
        assert cache.get_price("NOPE") is None
        assert cache.get_price("ALSONO") is None
        assert source.get_tickers() == ["AAPL"]
        await source.stop()

    async def test_adding_a_tracked_ticker_keeps_its_price_and_reference(self):
        source, cache = await started(two_sessions(), ["JMKE"])
        cache.update("JMKE", 21.0)
        await source.add_ticker("JMKE")
        assert cache.get_price("JMKE") == 21.0
        assert cache.get("JMKE").previous_close == 20.0
        await source.stop()

    async def test_steps_move_from_the_real_close(self):
        sim = GBMSimulator(["JMKE"], event_probability=0, start_prices={"JMKE": 19.0})
        assert sim.step()["JMKE"] == pytest.approx(19.0, abs=0.05)


class TestWhenClosesAreUnavailable:
    async def test_defaults_use_sample_prices_and_say_so(self):
        failing = market({d.isoformat(): RATE_LIMITED for d in recent_weekdays(10)})
        source, cache = await started(failing, ["AAPL", "JMKE"])
        assert source.mode == "simulated"
        assert cache.get_price("AAPL") == SEED_PRICES["AAPL"]
        assert cache.get_price("JMKE") is None
        await source.stop()

    async def test_later_add_retries_after_the_wait(self):
        newest, latest = recent_weekdays(2)
        days = {newest.isoformat(): RATE_LIMITED}
        transport = market(days)
        closes = make_closes(transport)
        cache = PriceCache()
        source = SimulatorDataSource(cache, update_interval=60, closes=closes)
        await source.start(["AAPL"])

        days[newest.isoformat()] = session(bar("JMKE", 19.0))
        await source.add_ticker("JMKE")  # Still inside the retry wait
        assert cache.get_price("JMKE") is None

        closes._next_load = 0.0
        await source.add_ticker("JMKE")
        assert cache.get_price("JMKE") == 19.0
        await source.stop()


class TestDailyCloses:
    async def test_keeps_the_latest_session_if_the_older_one_fails(self):
        latest, previous = recent_weekdays(2)
        transport = market(
            {latest.isoformat(): session(bar("JMKE", 19.0)), previous.isoformat(): RATE_LIMITED}
        )
        closes = await make_closes(transport).load()
        assert closes["JMKE"][:2] == (19.0, None)

    async def test_failed_refresh_keeps_the_last_good_closes(self):
        latest = recent_weekdays(1)[0]
        days = {latest.isoformat(): session(bar("JMKE", 19.0))}
        loader = make_closes(market(days), refresh_seconds=0)
        await loader.load()

        days[latest.isoformat()] = RATE_LIMITED
        loader._next_load = 0.0
        closes = await loader.load()
        assert closes["JMKE"][0] == 19.0

    async def test_fresh_closes_need_no_request(self):
        transport = two_sessions()
        loader = make_closes(transport)
        await loader.load()
        calls = len(transport.urls)
        await loader.load()
        assert len(transport.urls) == calls


class TestFactory:
    @pytest.mark.parametrize("value", ["true", "TRUE", " true "])
    def test_flag_with_key_seeds_the_simulator(self, value):
        env = {"MASSIVE_API_KEY": "k", "MASSIVE_SEED_SIMULATOR": value}
        with patch.dict(os.environ, env, clear=True):
            source = create_market_data_source(PriceCache())
        assert isinstance(source, SimulatorDataSource)
        assert source._closes is not None

    @pytest.mark.parametrize("value", ["false", "", "yes"])
    def test_key_alone_stays_on_massive(self, value):
        env = {"MASSIVE_API_KEY": "k", "MASSIVE_SEED_SIMULATOR": value}
        with patch.dict(os.environ, env, clear=True):
            assert isinstance(create_market_data_source(PriceCache()), MassiveDataSource)

    def test_flag_without_key_is_the_plain_simulator(self):
        with patch.dict(os.environ, {"MASSIVE_SEED_SIMULATOR": "true"}, clear=True):
            source = create_market_data_source(PriceCache())
        assert isinstance(source, SimulatorDataSource)
        assert source._closes is None
