"""Chat flow: parsing, auto-execution and failure handling, with no real LLM."""

import json
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
        assert response.json() == {"message": "Hi", "trades": [], "watchlist_changes": []}

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
