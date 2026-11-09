"""Chat flow: parsing, auto-execution and failure handling, with no real LLM."""

import json
import time
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import chat
from app.db import connect
from app.main import create_app


@pytest.fixture(autouse=True)
def environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FINALLY_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("FINALLY_STATIC_DIR", str(tmp_path / "no-static"))
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MOCK", raising=False)


@pytest.fixture
def client():
    with TestClient(create_app()) as test_client:
        yield test_client


def llm_reply(content: str | None) -> SimpleNamespace:
    message = SimpleNamespace(content=content)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def send(client: TestClient, content: str | None, text: str = "hello"):
    with patch.object(chat, "completion", return_value=llm_reply(content)) as completion:
        response = client.post("/api/chat", json={"message": text})
    return response, completion


class TestParsing:
    def test_message_only_is_valid(self, client):
        response, _ = send(client, json.dumps({"message": "Hi"}))
        assert response.status_code == 200
        assert response.json() == {
            "message": "Hi",
            "trades": [],
            "watchlist_changes": [],
            "predictions": [],
            "tool_calls": [],
        }

    @pytest.mark.parametrize(
        "content", ["not json", "{}", '{"message": "x", "trades": [{"side": "hold"}]}', "", None]
    )
    def test_malformed_response_is_502_and_stores_nothing(self, client, content):
        response, _ = send(client, content)
        assert response.status_code == 502

        reply, completion = send(client, json.dumps({"message": "ok"}))
        roles = [m["role"] for m in completion.call_args.kwargs["messages"]]
        assert reply.status_code == 200
        assert roles == ["system", "user"]

    def test_llm_failure_is_502_without_leaking_detail(self, client):
        with patch.object(chat, "completion", side_effect=RuntimeError("secret detail")):
            response = client.post("/api/chat", json={"message": "hello"})
        assert response.status_code == 502
        assert "secret" not in response.text

    @pytest.mark.parametrize("body", [{"message": ""}, {}, {"message": "x" * 4001}])
    def test_invalid_request_is_422(self, client, body):
        assert client.post("/api/chat", json=body).status_code == 422


class TestPrompt:
    def test_call_follows_project_settings(self, client):
        _, completion = send(client, json.dumps({"message": "Hi"}))
        kwargs = completion.call_args.kwargs
        assert kwargs["model"] == "openrouter/openai/gpt-oss-120b"
        assert kwargs["extra_body"] == {"provider": {"order": ["cerebras"]}}
        assert kwargs["response_format"] is chat.LLMResponse
        assert kwargs["reasoning_effort"] == "low"

    def test_context_has_portfolio_and_watchlist(self, client):
        client.post("/api/portfolio/trade", json={"ticker": "AAPL", "quantity": 1, "side": "buy"})
        _, completion = send(client, json.dumps({"message": "Hi"}))
        system = completion.call_args.kwargs["messages"][0]["content"]
        assert "FinAlly" in system
        assert '"ticker": "AAPL"' in system
        assert "cash_balance" in system

    def test_history_is_sent_in_order(self, client):
        send(client, json.dumps({"message": "first reply"}), "first")
        _, completion = send(client, json.dumps({"message": "second reply"}), "second")
        messages = completion.call_args.kwargs["messages"][1:]
        assert [m["content"] for m in messages] == ["first", "first reply", "second"]


class TestAutoExecution:
    def test_trade_executes_and_is_reported(self, client):
        content = {
            "message": "Bought.",
            "trades": [{"ticker": "aapl", "side": "buy", "quantity": 2}],
        }
        body = send(client, json.dumps(content))[0].json()

        trade = body["trades"][0]
        assert (trade["ticker"], trade["status"]) == ("AAPL", "ok")
        assert trade["price"] > 0
        assert body["message"] == "Bought."
        assert client.get("/api/portfolio").json()["positions"][0]["quantity"] == 2

    def test_add_ticker_then_buy_it(self, client):
        content = {
            "message": "Done.",
            "trades": [{"ticker": "PYPL", "side": "buy", "quantity": 1}],
            "watchlist_changes": [{"ticker": "PYPL", "action": "add"}],
        }
        body = send(client, json.dumps(content))[0].json()

        assert body["watchlist_changes"][0]["status"] == "ok"
        assert body["trades"][0]["status"] == "ok"

    def test_failed_trade_is_reported_and_others_still_run(self, client):
        content = {
            "message": "Placing both.",
            "trades": [
                {"ticker": "AAPL", "side": "buy", "quantity": 1000000},
                {"ticker": "MSFT", "side": "buy", "quantity": 1},
            ],
        }
        body = send(client, json.dumps(content))[0].json()

        assert body["trades"][0]["status"] == "failed"
        assert "Insufficient cash" in body["trades"][0]["error"]
        assert body["trades"][1]["status"] == "ok"
        assert "Insufficient cash" in body["message"]

    @pytest.mark.parametrize("quantity", [0, -5, "NaN"])
    def test_bad_quantity_never_executes(self, client, quantity):
        trade = {"ticker": "AAPL", "side": "buy", "quantity": quantity}
        with patch.object(chat.LLMResponse, "model_validate_json") as parse:
            parse.return_value = chat.LLMResponse(
                message="x", trades=[chat.TradeAction(**{**trade, "quantity": float(quantity)})]
            )
            body = send(client, "{}")[0].json()

        assert body["trades"][0]["status"] == "failed"
        assert client.get("/api/portfolio").json()["cash_balance"] == 10000.0

    def test_invalid_ticker_is_reported(self, client):
        content = {
            "message": "x",
            "watchlist_changes": [{"ticker": "not valid", "action": "add"}],
        }
        body = send(client, json.dumps(content))[0].json()
        assert body["watchlist_changes"][0]["status"] == "failed"

    def test_removing_unknown_ticker_is_reported(self, client):
        content = {"message": "x", "watchlist_changes": [{"ticker": "ZZZ", "action": "remove"}]}
        body = send(client, json.dumps(content))[0].json()
        assert "not on the watchlist" in body["watchlist_changes"][0]["error"]

    def test_actions_are_stored(self, client):
        trades = [{"ticker": "AAPL", "side": "buy", "quantity": 1}]
        content = {"message": "Bought.", "trades": trades}
        send(client, json.dumps(content))

        conn = connect(client.app.state.db_path)
        rows = conn.execute("SELECT role, actions FROM chat_messages ORDER BY rowid").fetchall()
        conn.close()
        assert [r["role"] for r in rows] == ["user", "assistant"]
        assert rows[0]["actions"] is None
        assert json.loads(rows[1]["actions"])["trades"][0]["ticker"] == "AAPL"


class TestHistoryEndpoint:
    def test_empty_on_fresh_start(self, client):
        assert client.get("/api/chat").json() == {"messages": []}

    def test_returns_conversation_with_actions(self, client):
        trades = [{"ticker": "AAPL", "side": "buy", "quantity": 1}]
        send(client, json.dumps({"message": "Bought.", "trades": trades}), "buy one")

        messages = client.get("/api/chat").json()["messages"]
        assert [m["role"] for m in messages] == ["user", "assistant"]
        assert messages[0]["content"] == "buy one"
        assert messages[0]["actions"] is None
        assert messages[1]["actions"]["trades"][0]["status"] == "ok"


class TestMockMode:
    @pytest.fixture(autouse=True)
    def mock_mode(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("LLM_MOCK", "true")

    def test_no_llm_call_and_fixed_reply(self, client):
        with patch.object(chat, "completion") as completion:
            first = client.post("/api/chat", json={"message": "how am I doing?"}).json()
            second = client.post("/api/chat", json={"message": "how am I doing?"}).json()
        completion.assert_not_called()
        assert first == second
        assert first["trades"] == []

    def test_commands_execute(self, client):
        text = "add PYPL and buy 2 PYPL then sell 1 PYPL and remove NFLX"
        body = client.post("/api/chat", json={"message": text}).json()

        assert [t["side"] for t in body["trades"]] == ["buy", "sell"]
        assert [c["action"] for c in body["watchlist_changes"]] == ["add", "remove"]
        assert all(t["status"] == "ok" for t in body["trades"])


def tool_call(name: str, arguments: dict, call_id: str = "call-1") -> SimpleNamespace:
    function = SimpleNamespace(name=name, arguments=json.dumps(arguments))
    return SimpleNamespace(id=call_id, function=function)


def turn(*calls, content=None) -> SimpleNamespace:
    """A model turn: tool calls, or a plain reply."""
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=list(calls)))]
    )


def chat_with(client, replies, text="Is NVDA overbought?"):
    with patch.object(chat, "completion", side_effect=replies) as completion:
        response = client.post("/api/chat", json={"message": text})
    return response, completion


class TestResearch:
    def test_looks_up_then_answers_from_a_separate_structured_call(self, client):
        from app.market.bars import Bar, insert_bars

        start = int(time.time() // 86400 * 86400) - 60 * 86400
        with closing(connect(client.app.state.db_path)) as conn:
            insert_bars(
                conn,
                [
                    Bar("NVDA", "1d", start + i * 86400, 800, 810, 790, 800 + i, "synthetic")
                    for i in range(60)
                ],
            )
        response, completion = chat_with(
            client,
            [
                turn(tool_call("get_indicators", {"ticker": "NVDA"})),
                turn(content="NVDA looks overbought."),  # Done looking things up
                llm_reply(json.dumps({"message": "RSI is 78, so NVDA is overbought."})),
            ],
        )
        assert response.status_code == 200
        body = response.json()
        assert body["message"] == "RSI is 78, so NVDA is overbought."
        assert body["tool_calls"] == [
            {
                "name": "get_indicators",
                "arguments": {"ticker": "NVDA"},
                "status": "ok",
                "error": None,
            }
        ]

        lookup, _, final = completion.call_args_list
        assert lookup.kwargs["tools"] is chat.assistant_tools.TOOLS
        assert "response_format" not in lookup.kwargs
        assert "tools" not in final.kwargs
        assert final.kwargs["response_format"] is chat.LLMResponse
        roles = [m["role"] for m in final.kwargs["messages"]]
        assert roles == ["system", "user", "assistant", "tool"]
        tool_message = final.kwargs["messages"][-1]
        assert tool_message["tool_call_id"] == "call-1"
        assert json.loads(tool_message["content"])["ticker"] == "NVDA"
        assert final.kwargs["messages"][2]["tool_calls"][0]["function"]["name"] == "get_indicators"

    def test_tool_failures_are_shown_to_the_model_and_recorded(self, client):
        response, completion = chat_with(
            client,
            [
                turn(tool_call("get_indicators", {"ticker": "ZZZZ"})),
                turn(),
                llm_reply(json.dumps({"message": "I have no data for ZZZZ."})),
            ],
        )
        assert response.json()["tool_calls"][0]["status"] == "failed"
        tool_message = completion.call_args_list[-1].kwargs["messages"][-1]
        assert json.loads(tool_message["content"]) == {"error": "No price history for ZZZZ."}

    def test_rounds_are_limited(self, client, monkeypatch):
        monkeypatch.setenv("CHAT_MAX_TOOL_ROUNDS", "2")
        lookup = turn(tool_call("get_portfolio_risk", {}))
        response, completion = chat_with(
            client, [lookup, lookup, llm_reply(json.dumps({"message": "Done."}))]
        )
        assert response.status_code == 200
        assert len(response.json()["tool_calls"]) == 2
        assert completion.call_count == 3

    def test_zero_rounds_answers_directly(self, client, monkeypatch):
        monkeypatch.setenv("CHAT_MAX_TOOL_ROUNDS", "0")
        response, completion = chat_with(client, [llm_reply(json.dumps({"message": "Hi"}))])
        assert response.status_code == 200 and completion.call_count == 1

    def test_budget_ends_research(self, client, monkeypatch):
        monkeypatch.setattr(chat, "RESEARCH_BUDGET_SECONDS", -1)
        response, completion = chat_with(client, [llm_reply(json.dumps({"message": "Hi"}))])
        assert response.status_code == 200 and completion.call_count == 1

    def test_failed_lookup_round_is_502_and_stores_nothing(self, client):
        response, _ = chat_with(client, RuntimeError("secret detail"))
        assert response.status_code == 502 and "secret" not in response.text
        assert client.get("/api/chat").json()["messages"] == []

    def test_tool_calls_are_stored_with_the_reply(self, client):
        chat_with(
            client,
            [
                turn(tool_call("get_portfolio_risk", {})),
                turn(),
                llm_reply(json.dumps({"message": "Here is your risk."})),
            ],
        )
        stored = client.get("/api/chat").json()["messages"][-1]
        assert [c["name"] for c in stored["actions"]["tool_calls"]] == ["get_portfolio_risk"]

    def test_prompt_explains_tools_and_simulated_data(self, client):
        _, completion = chat_with(client, [turn(), llm_reply(json.dumps({"message": "Hi"}))])
        system = completion.call_args.kwargs["messages"][0]["content"]
        assert "look them up with your tools" in system
        assert '"market_data_mode": "simulated"' in system
        assert "past patterns don't predict future moves" in system


class TestMockTools:
    @pytest.fixture(autouse=True)
    def mock_mode(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("LLM_MOCK", "true")

    def test_analyze_and_risk_run_real_tools(self, client):
        body = client.post("/api/chat", json={"message": "analyze NVDA and check my risk"}).json()
        assert [(c["name"], c["arguments"]) for c in body["tool_calls"]] == [
            ("get_indicators", {"ticker": "NVDA"}),
            ("get_portfolio_risk", {}),
        ]
        assert body["message"] == "Mock response: request received."

    def test_forecast_runs_the_tool(self, client):
        body = client.post("/api/chat", json={"message": "forecast my portfolio"}).json()
        assert [(c["name"], c["status"]) for c in body["tool_calls"]] == [("run_forecast", "ok")]

    def test_backtest_runs_the_tool(self, client):
        body = client.post("/api/chat", json={"message": "backtest NVDA"}).json()
        assert [(c["name"], c["arguments"]) for c in body["tool_calls"]] == [
            ("run_backtest", {"ticker": "NVDA", "strategy": "sma_crossover"})
        ]

    def test_plain_message_uses_no_tools(self, client):
        assert client.post("/api/chat", json={"message": "hello"}).json()["tool_calls"] == []


class TestPredictions:
    def test_recorded_with_the_live_price_and_linked_to_the_reply(self, client):
        reply = {
            "message": "I think NVDA rises.",
            "predictions": [
                {"ticker": "nvda", "direction": "up", "confidence": 0.65, "horizon_minutes": 60}
            ],
        }
        response, _ = send(client, json.dumps(reply))
        (call,) = response.json()["predictions"]
        assert call["status"] == "ok" and call["ticker"] == "NVDA"
        assert call["reference_price"] > 0 and call["resolves_at"]

        recent = client.get("/api/predictions").json()["predictions"]
        assert [(p["id"], p["direction"], p["confidence"]) for p in recent] == [
            (call["id"], "up", 0.65)
        ]
        stored = client.get("/api/chat").json()["messages"][-1]
        assert stored["actions"]["predictions"][0]["id"] == call["id"]
        with closing(connect(client.app.state.db_path)) as conn:
            linked = conn.execute(
                "SELECT c.role FROM predictions p JOIN chat_messages c ON c.id = p.chat_message_id"
            ).fetchall()
        assert [row["role"] for row in linked] == ["assistant", "assistant"]  # And its baseline

    def test_bad_calls_are_reported_in_the_reply(self, client):
        reply = {
            "message": "Calls.",
            "predictions": [
                {"ticker": "NVDA", "direction": "up", "confidence": 65, "horizon_minutes": 60},
                {"ticker": "PYPL", "direction": "down", "confidence": 0.6, "horizon_minutes": 60},
            ],
        }
        body = send(client, json.dumps(reply))[0].json()
        assert [p["status"] for p in body["predictions"]] == ["failed", "failed"]
        assert "Confidence must be between 0.5" in body["message"]
        assert "PYPL isn't tracked" in body["message"]
        assert client.get("/api/predictions").json()["predictions"] == []

    def test_prompt_asks_for_honest_scored_predictions(self, client):
        _, completion = send(client, json.dumps({"message": "Hi"}))
        system = completion.call_args.kwargs["messages"][0]["content"]
        assert 'record it in "predictions"' in system
        assert "never decline" in system


class TestMockPredictions:
    @pytest.fixture(autouse=True)
    def mock_mode(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("LLM_MOCK", "true")

    def test_predict_commands(self, client):
        body = client.post(
            "/api/chat", json={"message": "predict NVDA up and predict AAPL down 75% 30m"}
        ).json()
        assert [
            (p["ticker"], p["direction"], p["confidence"], p["horizon_minutes"], p["status"])
            for p in body["predictions"]
        ] == [("NVDA", "up", 0.6, 60, "ok"), ("AAPL", "down", 0.75, 30, "ok")]
