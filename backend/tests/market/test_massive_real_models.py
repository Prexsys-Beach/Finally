"""MassiveDataSource tests that run the real massive client and models.

Only the HTTP transport is faked, so URL building and response parsing are both
exercised. MagicMock snapshots are deliberately avoided: they invent attributes,
which once hid a read of a field that does not exist.
"""

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

import pytest
import urllib3
from massive import RESTClient
from massive.rest.models import TickerSnapshot

from app.market import massive_client
from app.market.cache import PriceCache
from app.market.factory import create_market_data_source
from app.market.massive_client import MassiveDataSource, snapshot_price, snapshot_timestamp
from app.market.simulator import SimulatorDataSource

SNAPSHOT_PATH = "/v2/snapshot/locale/us/markets/stocks/tickers"
GROUPED_PATH = "/v2/aggs/grouped/"
NANOSECONDS = 1762440000123456789
SECONDS = 1762440000.1234567
FORBIDDEN = (403, {"status": "NOT_AUTHORIZED", "message": "Upgrade your plan"})


def snapshot_payload(**overrides) -> dict:
    """A documented snapshot. Pass field=None to omit that field."""
    payload = {
        "ticker": "AAPL",
        "day": {"c": 190.2, "o": 189.0, "h": 191.0, "l": 188.0, "v": 10, "vw": 190.0},
        "min": {"c": 190.1, "t": 1762439940000},
        "prevDay": {"c": 188.0},
        "lastTrade": {"p": 190.25, "t": NANOSECONDS, "s": 100},
        "updated": NANOSECONDS,
        "todaysChangePerc": 1.2,
    }
    payload.update(overrides)
    return {key: value for key, value in payload.items() if value is not None}


def parsed(**overrides) -> TickerSnapshot:
    return TickerSnapshot.from_dict(snapshot_payload(**overrides))


def bar(ticker: str, close: float) -> dict:
    return {"T": ticker, "c": close, "o": 1, "h": 1, "l": 1, "v": 1, "t": 1762376400000}


class FakeTransport:
    """Stands in for urllib3's request(), answering by URL fragment."""

    def __init__(self, routes: list[tuple[str, tuple | Callable]]) -> None:
        self.routes = routes
        self.urls: list[str] = []

    def __call__(self, method: str, url: str, **kwargs) -> urllib3.HTTPResponse:
        self.urls.append(url)
        status, body = 200, {"status": "OK", "results": []}
        for fragment, route in self.routes:
            if fragment in url:
                status, body = route(url) if callable(route) else route
                break
        return urllib3.HTTPResponse(body=json.dumps(body).encode(), status=status)


def real_client(transport: FakeTransport) -> RESTClient:
    client = RESTClient(api_key="test-key", retries=0)
    client.client.request = transport
    return client


def make_source(cache: PriceCache, transport: FakeTransport) -> MassiveDataSource:
    source = MassiveDataSource("test-key", cache, eod_call_spacing=0)
    source._client = real_client(transport)
    source._tickers = ["AAPL"]
    return source


def recent_weekdays(count: int) -> list[date]:
    days: list[date] = []
    day = datetime.now(UTC).date()
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day)
        day -= timedelta(days=1)
    return days


class TestSnapshotParsing:
    def test_price_prefers_last_trade(self):
        assert snapshot_price(parsed()) == 190.25

    def test_price_falls_back_to_minute_bar(self):
        assert snapshot_price(parsed(lastTrade=None)) == 190.1

    def test_price_falls_back_to_day(self):
        assert snapshot_price(parsed(lastTrade=None, min=None)) == 190.2

    def test_zero_is_treated_as_missing(self):
        assert snapshot_price(parsed(lastTrade=None, min=None, day={"c": 0})) == 188.0

    def test_no_usable_price(self):
        assert snapshot_price(TickerSnapshot.from_dict({"ticker": "AAPL"})) is None

    def test_trade_timestamp_is_nanoseconds(self):
        assert snapshot_timestamp(parsed()) == pytest.approx(SECONDS)

    def test_minute_timestamp_is_milliseconds(self):
        assert snapshot_timestamp(parsed(lastTrade=None, updated=None)) == 1762439940.0


class TestLiveMode:
    async def test_poll_uses_correct_url_and_updates_cache(self):
        cache = PriceCache()
        tickers = {"status": "OK", "tickers": [snapshot_payload()]}
        transport = FakeTransport([(SNAPSHOT_PATH, (200, tickers))])
        source = make_source(cache, transport)

        await source._poll_once()

        assert transport.urls == [f"https://api.massive.com{SNAPSHOT_PATH}"]
        update = cache.get("AAPL")
        assert update.price == 190.25
        assert update.previous_close == 188.0
        assert update.day_change_percent == 1.1968
        assert update.timestamp == pytest.approx(SECONDS)
        assert source.mode == "live"

    async def test_ticker_removed_during_poll_stays_removed(self):
        cache = PriceCache()
        tickers = {"status": "OK", "tickers": [snapshot_payload()]}
        source = make_source(cache, FakeTransport([(SNAPSHOT_PATH, (200, tickers))]))
        fetch = source._fetch_snapshots

        def fetch_then_remove(requested: list[str]) -> list[TickerSnapshot]:
            snapshots = fetch(requested)
            source._tickers = []
            return snapshots

        source._fetch_snapshots = fetch_then_remove
        await source._poll_once()

        assert cache.get("AAPL") is None

    @pytest.mark.parametrize("status", [401, 404])
    async def test_other_errors_stay_in_live_mode(self, status: int):
        transport = FakeTransport([(SNAPSHOT_PATH, (status, {"status": "ERROR"}))])
        source = make_source(PriceCache(), transport)

        await source._poll_once()

        assert source.mode == "live"


class TestEndOfDayMode:
    async def test_403_switches_mode_then_loads_two_latest_sessions(self):
        cache = PriceCache()
        newest, latest, previous = recent_weekdays(3)
        closes = {latest.isoformat(): 200.0, previous.isoformat(): 190.0}

        def grouped(url: str) -> tuple:
            day = url.rsplit("/", 1)[1]
            if day == newest.isoformat():
                return FORBIDDEN  # Too recent for the plan
            results = [bar("AAPL", closes[day]), bar("MSFT", 400.0)]
            return 200, {"status": "OK", "results": results}

        transport = FakeTransport([(SNAPSHOT_PATH, FORBIDDEN), (GROUPED_PATH, grouped)])
        source = make_source(cache, transport)

        await source._poll_once()
        assert source.mode == "eod"
        assert len(cache) == 0
        assert source._next_delay() == 0.0

        await source._poll_once()
        update = cache.get("AAPL")
        assert (update.price, update.previous_close) == (200.0, 190.0)
        assert update.timestamp == 1762376400.0
        assert source._next_delay() == massive_client.EOD_REFRESH_SECONDS

        requested = [url.rsplit("/", 1)[1] for url in transport.urls if GROUPED_PATH in url]
        assert all(date.fromisoformat(day).weekday() < 5 for day in requested)

        calls_before = len(transport.urls)
        await source.add_ticker("msft")
        assert cache.get_price("MSFT") == 400.0
        assert len(transport.urls) == calls_before

    async def test_start_returns_and_loop_fetches_closes(self):
        cache = PriceCache()
        results = {"status": "OK", "results": [bar("AAPL", 5.0)]}
        transport = FakeTransport([(SNAPSHOT_PATH, FORBIDDEN), (GROUPED_PATH, (200, results))])
        source = MassiveDataSource("test-key", cache, eod_call_spacing=0)

        with patch.object(massive_client, "RESTClient", return_value=real_client(transport)):
            await source.start(["aapl"])
            await asyncio.sleep(0.2)

        assert source.get_tickers() == ["AAPL"]
        assert cache.get_price("AAPL") == 5.0
        await source.stop()

    async def test_no_data_waits_for_next_refresh(self):
        source = make_source(PriceCache(), FakeTransport([]))
        source._mode = "eod"

        await source._poll_once()

        assert source._next_delay() == massive_client.EOD_REFRESH_SECONDS


class TestSimulatorContract:
    async def test_tickers_are_normalized_and_previous_close_is_kept(self):
        cache = PriceCache()
        source = SimulatorDataSource(cache, update_interval=0.01)

        await source.start(["aapl"])
        await source.add_ticker("Aapl")
        await asyncio.sleep(0.05)

        assert source.get_tickers() == ["AAPL"]
        assert source.mode == "simulated"
        assert cache.get("AAPL").previous_close == 190.0
        await source.stop()


class TestPollInterval:
    @pytest.mark.parametrize(
        ("value", "expected"), [("5", 5.0), ("abc", 15.0), ("0", 15.0), ("", 15.0)]
    )
    def test_env_var(self, monkeypatch: pytest.MonkeyPatch, value: str, expected: float):
        monkeypatch.setenv("MASSIVE_API_KEY", "test-key")
        monkeypatch.setenv("MASSIVE_POLL_INTERVAL", value)

        assert create_market_data_source(PriceCache())._interval == expected
