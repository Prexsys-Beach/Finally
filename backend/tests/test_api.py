"""API tests through the real app, lifespan, database and simulator."""

import asyncio
import json
import signal
import threading
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.db import DEFAULT_TICKERS
from app.main import create_app, stop_on_shutdown_signal
from app.market import PriceCache
from app.market.stream import _generate_events


@pytest.fixture(autouse=True)
def environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FINALLY_DB_PATH", str(tmp_path / "db" / "test.db"))
    monkeypatch.setenv("FINALLY_STATIC_DIR", str(tmp_path / "no-static"))
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)


@pytest.fixture
def client():
    with TestClient(create_app()) as test_client:
        yield test_client


def watched(client: TestClient) -> list[str]:
    return [t["ticker"] for t in client.get("/api/watchlist").json()["tickers"]]


def buy(client: TestClient, ticker: str = "AAPL", quantity: float = 1):
    body = {"ticker": ticker, "quantity": quantity, "side": "buy"}
    return client.post("/api/portfolio/trade", json=body)


class TestFreshStart:
    def test_health(self, client):
        body = client.get("/api/health").json()
        assert body["status"] == "ok"
        assert body["market_data"] == {
            "mode": "simulated",
            "tracked_tickers": 10,
            "priced_tickers": 10,
        }

    def test_seed_data(self, client):
        portfolio = client.get("/api/portfolio").json()
        assert portfolio["cash_balance"] == 10000.0
        assert portfolio["total_value"] == 10000.0
        assert portfolio["positions"] == []
        assert sorted(watched(client)) == sorted(DEFAULT_TICKERS)

    def test_watchlist_has_prices(self, client):
        entry = client.get("/api/watchlist").json()["tickers"][0]
        assert entry["price"] > 0
        assert entry["previous_close"] > 0
        assert entry["direction"] in ("up", "down", "flat")

    def test_initial_snapshot_recorded(self, client):
        snapshots = client.get("/api/portfolio/history").json()["snapshots"]
        assert [s["total_value"] for s in snapshots] == [10000.0]


class TestTrading:
    def test_buy_then_sell(self, client):
        bought = buy(client, quantity=2)
        assert bought.status_code == 200
        body = bought.json()
        price = body["trade"]["price"]
        assert body["portfolio"]["cash_balance"] == pytest.approx(10000 - 2 * price, abs=0.01)
        assert body["portfolio"]["positions"][0]["ticker"] == "AAPL"

        sale = {"ticker": "aapl", "quantity": 2, "side": "sell"}
        sold = client.post("/api/portfolio/trade", json=sale)
        assert sold.status_code == 200
        assert sold.json()["portfolio"]["positions"] == []

    def test_trade_records_snapshot(self, client):
        before = len(client.get("/api/portfolio/history").json()["snapshots"])
        buy(client)
        after = len(client.get("/api/portfolio/history").json()["snapshots"])
        assert after == before + 1

    def test_insufficient_cash_is_400(self, client):
        response = buy(client, quantity=1_000_000)
        assert response.status_code == 400
        assert "Insufficient cash" in response.json()["detail"]

    def test_insufficient_shares_is_400(self, client):
        body = {"ticker": "AAPL", "quantity": 1, "side": "sell"}
        assert client.post("/api/portfolio/trade", json=body).status_code == 400

    @pytest.mark.parametrize(
        "body",
        [
            {"ticker": "AAPL", "quantity": 0, "side": "buy"},
            {"ticker": "AAPL", "quantity": -1, "side": "buy"},
            {"ticker": "AAPL", "quantity": 1, "side": "short"},
            {"ticker": "../etc", "quantity": 1, "side": "buy"},
            {"ticker": "", "quantity": 1, "side": "buy"},
            {"quantity": 1, "side": "buy"},
        ],
    )
    def test_invalid_request_is_422(self, client, body):
        assert client.post("/api/portfolio/trade", json=body).status_code == 422

    def test_trading_unwatched_ticker_tracks_it(self, client):
        assert buy(client, ticker="PYPL").status_code == 200
        assert client.get("/api/health").json()["market_data"]["tracked_tickers"] == 11
        assert client.get("/api/portfolio").json()["positions"][0]["current_price"] > 0


class TestWatchlist:
    def test_add_and_remove(self, client):
        response = client.post("/api/watchlist", json={"ticker": " pypl "})
        assert response.status_code == 201
        assert "PYPL" in watched(client)

        assert client.delete("/api/watchlist/pypl").status_code == 204
        assert "PYPL" not in watched(client)
        assert client.get("/api/health").json()["market_data"]["tracked_tickers"] == 10

    def test_duplicate_is_409(self, client):
        assert client.post("/api/watchlist", json={"ticker": "AAPL"}).status_code == 409

    def test_removing_unknown_is_404(self, client):
        assert client.delete("/api/watchlist/PYPL").status_code == 404

    def test_invalid_ticker_is_422(self, client):
        assert client.post("/api/watchlist", json={"ticker": "not valid"}).status_code == 422
        assert client.delete("/api/watchlist/not%20valid").status_code == 422

    def test_held_ticker_keeps_its_price_after_removal(self, client):
        buy(client)
        assert client.delete("/api/watchlist/AAPL").status_code == 204

        assert "AAPL" not in watched(client)
        assert client.get("/api/portfolio").json()["positions"][0]["current_price"] > 0


class TestPersistence:
    def test_state_survives_restart(self):
        with TestClient(create_app()) as first:
            buy(first, quantity=3)
            first.delete("/api/watchlist/NFLX")
            cash = first.get("/api/portfolio").json()["cash_balance"]

        with TestClient(create_app()) as second:
            portfolio = second.get("/api/portfolio").json()
            assert portfolio["cash_balance"] == cash
            assert portfolio["positions"][0]["quantity"] == 3
            assert "NFLX" not in watched(second)  # Not re-seeded


class TestStaticFiles:
    def test_serves_frontend_without_hiding_api(self, tmp_path, monkeypatch):
        static = tmp_path / "static"
        static.mkdir()
        (static / "index.html").write_text("<h1>FinAlly</h1>")
        monkeypatch.setenv("FINALLY_STATIC_DIR", str(static))

        with TestClient(create_app()) as client:
            assert "FinAlly" in client.get("/").text
            assert client.get("/api/health").json()["status"] == "ok"


class TestShutdownSignal:
    @pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM])
    def test_sets_stop_and_keeps_the_existing_handler(self, signum):
        calls = []
        original = signal.getsignal(signum)
        signal.signal(signum, lambda number, frame: calls.append(number))
        stop = threading.Event()
        try:
            stop_on_shutdown_signal(stop)
            signal.getsignal(signum)(signum, None)
        finally:
            signal.signal(signum, original)

        assert stop.is_set()
        assert calls == [signum]


class TestPriceStream:
    async def test_events_contain_daily_change(self):
        cache = PriceCache()
        cache.update("AAPL", 190.0, previous_close=188.0)
        request = AsyncMock()
        request.is_disconnected.return_value = False
        request.client = None

        events = _generate_events(cache, request, interval=0.01)
        assert await events.__anext__() == "retry: 1000\n\n"
        event = await asyncio.wait_for(events.__anext__(), timeout=1)
        await events.aclose()

        assert event.startswith("data: ")
        assert json.loads(event[6:])["AAPL"]["day_change_percent"] == 1.0638

    async def test_stream_ends_when_stop_is_set(self):
        cache = PriceCache()
        cache.update("AAPL", 190.0)
        request = AsyncMock()
        request.is_disconnected.return_value = False
        request.client = None
        stop = threading.Event()

        events = _generate_events(cache, request, interval=0.01, stop=stop)
        await events.__anext__()
        await events.__anext__()
        stop.set()

        async def drain() -> list[str]:
            return [event async for event in events]

        assert await asyncio.wait_for(drain(), timeout=1) == []

    def test_route_is_registered(self, client):
        paths = [route.path for route in client.app.routes]
        assert paths.count("/api/stream/prices") == 1


class TestMarketBars:
    def test_returns_stored_bars_oldest_first(self, client):
        from contextlib import closing

        from app.db import connect
        from app.market.bars import Bar, insert_bars

        start = 1_700_006_400
        with closing(connect(client.app.state.db_path)) as conn:
            insert_bars(
                conn,
                [
                    Bar("ZZZ", "1m", start + i * 60, 10.0, 11.0, 9.0, 10.5, "synthetic")
                    for i in range(3)
                ],
            )
        body = client.get("/api/market/bars/zzz", params={"limit": 2}).json()
        assert body["ticker"] == "ZZZ"
        assert body["timeframe"] == "1m"
        assert body["bars"] == [
            {
                "time": start + i * 60,
                "open": 10.0,
                "high": 11.0,
                "low": 9.0,
                "close": 10.5,
                "origin": "synthetic",
            }
            for i in (1, 2)
        ]

    def test_unknown_ticker_has_no_bars(self, client):
        assert client.get("/api/market/bars/QQQQ", params={"timeframe": "1d"}).json()["bars"] == []

    @pytest.mark.parametrize(
        "params", [{"timeframe": "5m"}, {"limit": 0}, {"limit": 10001}]
    )
    def test_rejects_bad_parameters(self, client, params):
        assert client.get("/api/market/bars/AAPL", params=params).status_code == 422

    def test_rejects_bad_ticker(self, client):
        assert client.get("/api/market/bars/not a ticker").status_code == 422


class TestSettings:
    def test_defaults(self, client):
        body = client.get("/api/settings").json()
        assert body["settings"] == {"synthetic_history_cutoff": "month"}
        assert body["choices"]["synthetic_history_cutoff"] == [
            "never",
            "day",
            "week",
            "month",
            "quarter",
            "year",
        ]

    def test_update_persists(self, client):
        body = client.put("/api/settings", json={"synthetic_history_cutoff": "never"}).json()
        assert body["settings"]["synthetic_history_cutoff"] == "never"
        assert client.get("/api/settings").json()["settings"]["synthetic_history_cutoff"] == "never"

    @pytest.mark.parametrize(
        "body",
        [{"synthetic_history_cutoff": "decade"}, {"unknown": 1}, {"synthetic_history_cutoff": None}],
    )
    def test_rejects_invalid_changes(self, client, body):
        response = client.put("/api/settings", json=body)
        assert response.status_code == 400
        assert client.get("/api/settings").json()["settings"]["synthetic_history_cutoff"] == "month"

    def test_invalid_change_saves_nothing(self, client):
        body = {"synthetic_history_cutoff": "day", "unknown": 1}
        assert client.put("/api/settings", json=body).status_code == 400
        assert client.get("/api/settings").json()["settings"]["synthetic_history_cutoff"] == "month"
