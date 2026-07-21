import pytest
from fastapi.testclient import TestClient

from backend.app import main


@pytest.fixture
def client():
    return TestClient(main.app)


def test_health_endpoint(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_chat_endpoint_returns_reply_and_tool_calls_schema(client, monkeypatch):
    async def fake_run_chat(messages):
        return {"reply": "안녕하세요", "tool_calls": [{"name": "run_sql", "input": {}, "output": "[]"}]}

    monkeypatch.setattr(main, "run_chat", fake_run_chat)

    res = client.post("/api/chat", json={"messages": [{"role": "user", "content": "매출 알려줘"}]})

    assert res.status_code == 200
    body = res.json()
    assert body["reply"] == "안녕하세요"
    assert body["tool_calls"][0]["name"] == "run_sql"


def test_chat_endpoint_passes_empty_messages_through(client, monkeypatch):
    received = {}

    async def fake_run_chat(messages):
        received["messages"] = messages
        return {"reply": "", "tool_calls": []}

    monkeypatch.setattr(main, "run_chat", fake_run_chat)

    res = client.post("/api/chat", json={"messages": []})

    assert res.status_code == 200
    assert received["messages"] == []


def test_chat_endpoint_accepts_arbitrary_role_string(client, monkeypatch):
    # ChatMessage.role은 현재 단순 str이라 "user"/"assistant" 외 값도
    # pydantic 검증을 통과한다 — 이는 알려진 동작으로 회귀 테스트에 고정한다.
    received = {}

    async def fake_run_chat(messages):
        received["messages"] = messages
        return {"reply": "", "tool_calls": []}

    monkeypatch.setattr(main, "run_chat", fake_run_chat)

    res = client.post("/api/chat", json={"messages": [{"role": "system", "content": "hi"}]})

    assert res.status_code == 200
    assert received["messages"][0]["role"] == "system"


def test_cors_headers_reflect_allowed_origin(client, monkeypatch):
    async def fake_run_chat(messages):
        return {"reply": "", "tool_calls": []}

    monkeypatch.setattr(main, "run_chat", fake_run_chat)

    res = client.post(
        "/api/chat",
        json={"messages": []},
        headers={"Origin": "http://localhost:3000"},
    )

    assert res.headers.get("access-control-allow-origin") == "http://localhost:3000"
