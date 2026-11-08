"""The assistant's read-only tools, against a real database."""

import json
import time
from contextlib import closing
from types import SimpleNamespace

import numpy as np
import pytest

from app import assistant_tools as tools
from app.db import connect, init_db
from app.market import PriceCache
from app.market.bars import Bar, insert_bars

DAY = 86400


@pytest.fixture
def ctx(tmp_path):
    path = tmp_path / "tools.db"
    init_db(path)
    with closing(connect(path)) as conn:
        conn.execute("DELETE FROM watchlist")
        start = int(time.time() // DAY * DAY) - 300 * DAY
        for seed, ticker in enumerate(["AAPL", "MSFT", "JPM"]):
            conn.execute(
                "INSERT INTO watchlist (id, user_id, ticker, added_at) VALUES (?, 'default', ?, '')",
                (ticker, ticker),
            )
            closes = 100 * np.exp(np.cumsum(np.random.default_rng(seed).normal(0, 0.02, 300)))
            insert_bars(
                conn,
                [
                    Bar(ticker, "1d", start + i * DAY, c, c * 1.01, c * 0.99, c, "synthetic")
                    for i, c in enumerate(closes)
                ],
            )
        cache = PriceCache()
        for ticker in ["AAPL", "MSFT", "JPM"]:
            cache.update(ticker, 100.0)
        yield tools.ToolContext(conn, cache, SimpleNamespace(mode="simulated"), 30)


def call(ctx, name, **arguments):
    content, record = tools.run(ctx, name, json.dumps(arguments))
    return json.loads(content), record


class TestTools:
    def test_schemas_name_every_tool(self):
        assert [t["function"]["name"] for t in tools.TOOLS] == [
            "get_indicators",
            "get_bars",
            "get_portfolio_risk",
            "run_forecast",
            "get_prediction_record",
            "get_correlations",
        ]

    def test_indicators(self, ctx):
        result, record = call(ctx, "get_indicators", ticker="aapl")
        assert record == {
            "name": "get_indicators",
            "arguments": {"ticker": "aapl"},
            "status": "ok",
            "error": None,
        }
        assert result["ticker"] == "AAPL" and result["timeframe"] == "1d"
        assert result["bars_used"] == 300 and result["origins"] == {"synthetic": 300}
        assert {"rsi_14", "macd", "volatility"} <= set(result["latest"])
        assert set(result["signals"]) == {"rsi", "bollinger", "trend", "macd"}

    def test_bars_are_compact_and_capped(self, ctx):
        result, _ = call(ctx, "get_bars", ticker="MSFT", limit=500)
        assert len(result["bars"]) == tools.MAX_BARS
        assert result["columns"] == ["time", "open", "high", "low", "close"]
        assert len(result["bars"][0][0]) == 10  # A date for daily bars

    def test_portfolio_risk_without_the_matrix(self, ctx):
        result, _ = call(ctx, "get_portfolio_risk")
        assert "correlation" not in result
        assert result["benchmark"] == "Equal-weighted watchlist (3 tickers)"

    def test_correlations_as_pairs(self, ctx):
        result, _ = call(ctx, "get_correlations", tickers=["msft", "AAPL", "PYPL"])
        assert [pair[:2] for pair in result["pairs"]] == [["MSFT", "AAPL"]]
        assert -1 <= result["pairs"][0][2] <= 1
        assert result["not_available"] == ["PYPL"]
        everything, _ = call(ctx, "get_correlations")
        assert len(everything["pairs"]) == 3

    def test_prediction_record(self, ctx):
        from app import predictions

        source = SimpleNamespace(mode="simulated", get_tickers=lambda: ["AAPL"])
        predictions.record(ctx.conn, ctx.cache, source, "AAPL", "up", 0.8, 60)
        result, _ = call(ctx, "get_prediction_record")
        assert result["current_data_mode"] == "simulated"
        assert result["modes"]["simulated"]["assistant"]["pending"] == 1
        assert result["latest"][0]["ticker"] == "AAPL" and result["latest"][0]["outcome"] is None

    def test_forecast_gives_the_end_of_the_fan(self, ctx):
        result, record = call(ctx, "run_forecast", target="Portfolio", horizon="1w", level=11000)
        assert record["status"] == "ok"
        assert result["target"] == "portfolio" and result["horizon_label"] == "1 week"
        assert set(result["at_horizon"]) == {"p5", "p25", "p50", "p75", "p95"}
        assert "times" not in result and "bands" not in result
        assert result["level"]["price"] == 11000

    @pytest.mark.parametrize(
        ("arguments", "error"),
        [
            ({"target": "AAPL", "horizon": "1y"}, "horizon must be one of"),
            ({"target": "AAPL", "level": -1}, "level must be a positive number"),
            ({"target": "ZZZZ"}, "No price for ZZZZ."),
        ],
    )
    def test_forecast_errors(self, ctx, arguments, error):
        content, record = tools.run(ctx, "run_forecast", json.dumps(arguments))
        assert error in json.loads(content)["error"] and record["status"] == "failed"

    def test_tools_never_write(self, ctx):
        before = ctx.conn.total_changes
        for name, args in [
            ("get_indicators", {"ticker": "AAPL"}),
            ("get_bars", {"ticker": "AAPL"}),
            ("get_portfolio_risk", {}),
            ("get_correlations", {}),
            ("get_prediction_record", {}),
            ("run_forecast", {"target": "AAPL"}),
        ]:
            call(ctx, name, **args)
        assert ctx.conn.total_changes == before


class TestFailuresGoBackToTheModel:
    @pytest.mark.parametrize(
        ("name", "arguments", "error"),
        [
            ("get_indicators", '{"ticker": "ZZZZ"}', "No price history for ZZZZ."),
            ("get_indicators", '{"ticker": "not a ticker"}', "Invalid ticker"),
            ("get_indicators", '{"ticker": "AAPL", "timeframe": "5m"}', "timeframe must be"),
            ("get_bars", '{"ticker": "AAPL", "limit": "ten"}', "whole number"),
            ("get_indicators", '{"symbol": "AAPL"}', "Bad arguments for get_indicators."),
            ("place_trade", "{}", "Unknown tool: place_trade"),
            ("get_bars", "not json", "Arguments were not valid JSON."),
            ("get_bars", "[1, 2]", "Arguments must be a JSON object."),
        ],
    )
    def test_reported_not_raised(self, ctx, name, arguments, error):
        content, record = tools.run(ctx, name, arguments)
        assert error in json.loads(content)["error"]
        assert record["status"] == "failed" and error in record["error"]

    def test_unexpected_errors_are_hidden(self, ctx, monkeypatch):
        def boom(*args, **kwargs):
            raise RuntimeError("secret detail")

        monkeypatch.setattr(tools.analytics, "portfolio_analytics", boom)
        content, record = tools.run(ctx, "get_portfolio_risk", "{}")
        assert json.loads(content) == {"error": "The lookup failed."}
        assert "secret" not in content and record["status"] == "failed"
