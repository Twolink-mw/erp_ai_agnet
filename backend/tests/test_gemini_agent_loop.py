"""gemini_agent.run_chat()의 도구 호출 루프 테스트.

Gemini API(_client.models.generate_content)와 MCP 세션(McpSalesClient)을 모두
가짜로 대체해 네트워크/서브프로세스 없이 루프 제어 흐름만 검증한다.
"""

from types import SimpleNamespace

import pytest

from backend.app import gemini_agent
from backend.app.gemini_agent import run_chat


class FakeMcpTool(SimpleNamespace):
    pass


class FakeMcpClient:
    """__aenter__/__aexit__/list_tools/call_tool을 흉내내는 가짜 MCP 세션."""

    def __init__(self, tools=None, enter_error=None):
        self._tools = tools or [
            FakeMcpTool(name="run_sql", description="", inputSchema={"type": "object", "properties": {}})
        ]
        self._enter_error = enter_error
        self.entered = False
        self.exited = False
        self.call_log: list[tuple[str, dict]] = []

    async def __aenter__(self):
        if self._enter_error:
            raise self._enter_error
        self.entered = True
        return self

    async def __aexit__(self, *exc_info):
        self.exited = True

    async def list_tools(self):
        return self._tools

    async def call_tool(self, name, arguments):
        self.call_log.append((name, arguments))
        return f"result-of-{name}"


def _text_part(text):
    return SimpleNamespace(text=text, function_call=None)


def _function_call_part(name, args):
    return SimpleNamespace(text=None, function_call=SimpleNamespace(name=name, args=args))


def _response(parts):
    return SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=parts))])


@pytest.fixture
def patch_mcp_client(monkeypatch):
    def _install(fake_client):
        monkeypatch.setattr(gemini_agent, "McpSalesClient", lambda: fake_client)
        return fake_client

    return _install


async def test_no_function_call_returns_text_immediately(monkeypatch, patch_mcp_client):
    fake_client = patch_mcp_client(FakeMcpClient())
    monkeypatch.setattr(
        gemini_agent._client.models,
        "generate_content",
        lambda **kwargs: _response([_text_part("답변입니다")]),
    )

    result = await run_chat([{"role": "user", "content": "안녕"}])

    assert result == {"reply": "답변입니다", "tool_calls": []}
    assert fake_client.exited is True


async def test_single_tool_call_then_text(monkeypatch, patch_mcp_client):
    fake_client = patch_mcp_client(FakeMcpClient())
    responses = iter(
        [
            _response([_function_call_part("run_sql", {"query": "SELECT 1"})]),
            _response([_text_part("결과입니다")]),
        ]
    )
    monkeypatch.setattr(
        gemini_agent._client.models, "generate_content", lambda **kwargs: next(responses)
    )

    result = await run_chat([{"role": "user", "content": "매출 알려줘"}])

    assert result["reply"] == "결과입니다"
    assert len(result["tool_calls"]) == 1
    assert result["tool_calls"][0]["name"] == "run_sql"
    assert result["tool_calls"][0]["input"] == {"query": "SELECT 1"}
    assert fake_client.call_log == [("run_sql", {"query": "SELECT 1"})]


async def test_exceeding_max_tool_rounds_returns_fallback_message(monkeypatch, patch_mcp_client):
    fake_client = patch_mcp_client(FakeMcpClient())
    monkeypatch.setattr(
        gemini_agent._client.models,
        "generate_content",
        lambda **kwargs: _response([_function_call_part("run_sql", {"query": "SELECT 1"})]),
    )

    result = await run_chat([{"role": "user", "content": "계속 물어봐"}])

    assert "도구 호출 횟수를 초과했습니다" in result["reply"]
    assert len(result["tool_calls"]) == gemini_agent.MAX_TOOL_ROUNDS
    assert fake_client.exited is True


async def test_mcp_enter_failure_returns_fallback_reply(patch_mcp_client):
    fake_client = patch_mcp_client(FakeMcpClient(enter_error=RuntimeError("연결 실패")))

    result = await run_chat([{"role": "user", "content": "매출 알려줘"}])

    assert "도구 연결 실패" in result["reply"]
    assert result["tool_calls"] == []
    assert fake_client.exited is True


async def test_mcp_session_closed_even_if_generate_content_raises(monkeypatch, patch_mcp_client):
    fake_client = patch_mcp_client(FakeMcpClient())

    def boom(**kwargs):
        raise RuntimeError("gemini api error")

    monkeypatch.setattr(gemini_agent._client.models, "generate_content", boom)

    with pytest.raises(RuntimeError, match="gemini api error"):
        await run_chat([{"role": "user", "content": "매출 알려줘"}])

    assert fake_client.exited is True


async def test_multiple_function_calls_in_single_response_all_processed(monkeypatch, patch_mcp_client):
    fake_client = patch_mcp_client(FakeMcpClient())
    responses = iter(
        [
            _response(
                [
                    _function_call_part("run_sql", {"query": "SELECT 1"}),
                    _function_call_part("get_view_schema", {"view_name": "매출"}),
                ]
            ),
            _response([_text_part("완료")]),
        ]
    )
    monkeypatch.setattr(
        gemini_agent._client.models, "generate_content", lambda **kwargs: next(responses)
    )

    result = await run_chat([{"role": "user", "content": "매출 스키마와 데이터 알려줘"}])

    assert len(result["tool_calls"]) == 2
    assert {c["name"] for c in result["tool_calls"]} == {"run_sql", "get_view_schema"}
    assert len(fake_client.call_log) == 2


async def test_assistant_role_mapped_to_model_for_gemini(monkeypatch, patch_mcp_client):
    patch_mcp_client(FakeMcpClient())
    captured = {}

    def fake_generate_content(**kwargs):
        captured["contents"] = kwargs["contents"]
        return _response([_text_part("ok")])

    monkeypatch.setattr(gemini_agent._client.models, "generate_content", fake_generate_content)

    await run_chat(
        [
            {"role": "user", "content": "질문"},
            {"role": "assistant", "content": "이전 답변"},
        ]
    )

    roles = [c.role for c in captured["contents"]]
    assert roles == ["user", "model"]
