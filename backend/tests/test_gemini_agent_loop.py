"""gemini_agent.run_chat()의 도구 호출 루프 테스트.

Gemini API(_client.models.generate_content)와 MCP 세션(McpSalesClient)을 모두
가짜로 대체해 네트워크/서브프로세스 없이 루프 제어 흐름만 검증한다.
"""

import logging
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


# --- 그라운딩(도구 미호출 환각) 방어 -----------------------------------------

_TABLE_REPLY = (
    "2024년 매출입니다.\n\n"
    "| 품목 | 매출 |\n"
    "| --- | --- |\n"
    "| 키보드 | 1,200,000 |\n"
    "| 모니터 | 3,400,000 |\n"
)


def _counting_generate_content(monkeypatch, responses):
    """generate_content를 순차 응답으로 대체하고 호출 횟수를 담은 카운터를 돌려준다."""
    calls = {"count": 0, "configs": []}
    it = iter(responses)

    def fake(**kwargs):
        calls["count"] += 1
        calls["configs"].append(kwargs.get("config"))
        return next(it)

    monkeypatch.setattr(gemini_agent._client.models, "generate_content", fake)
    return calls


async def test_ungrounded_table_response_triggers_retry_then_grounded_reply(
    monkeypatch, patch_mcp_client
):
    fake_client = patch_mcp_client(FakeMcpClient())
    calls = _counting_generate_content(
        monkeypatch,
        [
            _response([_text_part(_TABLE_REPLY)]),
            _response([_function_call_part("run_sql", {"query": "SELECT 1"})]),
            _response([_text_part("확인된 결과입니다")]),
        ],
    )

    result = await run_chat([{"role": "user", "content": "2024년 매출 알려줘"}])

    assert result["reply"] == "확인된 결과입니다"
    assert calls["count"] == 3
    assert [c["name"] for c in result["tool_calls"]] == ["run_sql"]
    assert fake_client.exited is True


async def test_ungrounded_table_after_retry_budget_exhausted_returns_safe_fallback(
    monkeypatch, patch_mcp_client
):
    patch_mcp_client(FakeMcpClient())
    calls = _counting_generate_content(
        monkeypatch,
        [_response([_text_part(_TABLE_REPLY)])] * (gemini_agent.MAX_GROUNDING_RETRIES + 1),
    )

    result = await run_chat([{"role": "user", "content": "2024년 매출 알려줘"}])

    assert result["reply"] == gemini_agent._UNGROUNDED_FALLBACK_REPLY
    assert "키보드" not in result["reply"]
    assert "모니터" not in result["reply"]
    assert result["tool_calls"] == []
    assert calls["count"] == gemini_agent.MAX_GROUNDING_RETRIES + 1
    assert calls["count"] <= gemini_agent.MAX_TOOL_ROUNDS


async def test_history_with_prior_reportable_content_skips_grounding_check(
    monkeypatch, patch_mcp_client
):
    """PDF/이메일 재사용 플로우 회귀 방지: 이전 답변에 표가 있으면 재시도하지 않는다."""
    patch_mcp_client(FakeMcpClient())
    calls = _counting_generate_content(
        monkeypatch, [_response([_text_part(_TABLE_REPLY)])]
    )

    result = await run_chat(
        [
            {"role": "user", "content": "2024년 매출 알려줘"},
            {"role": "assistant", "content": _TABLE_REPLY},
            {"role": "user", "content": "PDF로 만들어줘"},
        ]
    )

    assert result["reply"] == _TABLE_REPLY
    assert calls["count"] == 1
    assert result["tool_calls"] == []


async def test_non_run_sql_tool_call_with_table_reply_is_not_retried(
    monkeypatch, patch_mcp_client
):
    """스키마 질문 오탐 방지: run_sql이 아니어도 도구를 호출했다면 그라운딩된 것으로 본다."""
    patch_mcp_client(FakeMcpClient())
    calls = _counting_generate_content(
        monkeypatch,
        [
            _response([_function_call_part("get_view_schema", {"view_name": "매출"})]),
            _response([_text_part(_TABLE_REPLY)]),
        ],
    )

    result = await run_chat([{"role": "user", "content": "매출 뷰에 어떤 컬럼이 있어?"}])

    assert result["reply"] == _TABLE_REPLY
    assert calls["count"] == 2
    assert [c["name"] for c in result["tool_calls"]] == ["get_view_schema"]


async def test_plain_text_reply_without_tool_call_is_not_retried(monkeypatch, patch_mcp_client):
    """표/차트가 없는 일반 대화 응답은 그라운딩 체크 대상이 아니다."""
    patch_mcp_client(FakeMcpClient())
    calls = _counting_generate_content(
        monkeypatch, [_response([_text_part("어떤 기간의 매출이 궁금하신가요?")])]
    )

    result = await run_chat([{"role": "user", "content": "안녕"}])

    assert result["reply"] == "어떤 기간의 매출이 궁금하신가요?"
    assert calls["count"] == 1


# --- 코드 덤프(실행되지 않는 파이썬/SQL 코드 응답) 방어 -----------------------

_CODE_DUMP_REPLY = (
    "지난달 대비 순위 변동을 계산해 보겠습니다.\n\n"
    "```python\n"
    "import pandas as pd\n"
    "df_august = pd.DataFrame({'품목': ['키보드'], '매출': [1200000]})\n"
    "print(df_august.rank())\n"
    "```\n"
)

_CHART_REPLY = (
    "월별 매출 추이입니다.\n\n"
    "| 월 | 매출 |\n"
    "| --- | --- |\n"
    "| 2024-07 | 1,200,000 |\n"
    "| 2024-08 | 3,400,000 |\n\n"
    "```chart\n"
    '{"type": "line", "title": "월별 매출", "xKey": "월",'
    ' "series": [{"key": "매출", "name": "매출"}],'
    ' "data": [{"월": "2024-07", "매출": 1200000}, {"월": "2024-08", "매출": 3400000}]}\n'
    "```\n"
)


async def test_code_dump_after_tool_call_triggers_retry_then_table_reply(
    monkeypatch, patch_mcp_client
):
    """도구로 실제 데이터를 가져왔더라도 코드 블록으로 답하면 재작성시킨다."""
    fake_client = patch_mcp_client(FakeMcpClient())
    calls = _counting_generate_content(
        monkeypatch,
        [
            _response([_function_call_part("run_sql", {"query": "SELECT 1"})]),
            _response([_text_part(_CODE_DUMP_REPLY)]),
            _response([_text_part(_TABLE_REPLY)]),
        ],
    )

    result = await run_chat([{"role": "user", "content": "지난달 대비 순위 변동 보여줘"}])

    assert result["reply"] == _TABLE_REPLY
    assert "import pandas" not in result["reply"]
    assert calls["count"] == 3
    assert [c["name"] for c in result["tool_calls"]] == ["run_sql"]
    assert fake_client.exited is True


async def test_code_dump_correction_message_is_injected(monkeypatch, patch_mcp_client):
    patch_mcp_client(FakeMcpClient())
    captured: list = []

    responses = iter(
        [
            _response([_function_call_part("run_sql", {"query": "SELECT 1"})]),
            _response([_text_part(_CODE_DUMP_REPLY)]),
            _response([_text_part(_TABLE_REPLY)]),
        ]
    )

    def fake(**kwargs):
        captured.append(kwargs["contents"])
        return next(responses)

    monkeypatch.setattr(gemini_agent._client.models, "generate_content", fake)

    await run_chat([{"role": "user", "content": "지난달 대비 순위 변동 보여줘"}])

    last_texts = [
        part.text for content in captured[-1] for part in content.parts if part.text
    ]
    assert any(gemini_agent._CODE_DUMP_CORRECTION_MESSAGE == t for t in last_texts)
    # 그라운딩 사유는 아니므로 해당 문구는 주입되지 않는다.
    assert not any(gemini_agent._GROUNDING_CORRECTION_MESSAGE == t for t in last_texts)


async def test_repeated_code_dump_exhausts_budget_and_returns_fallback(
    monkeypatch, patch_mcp_client
):
    patch_mcp_client(FakeMcpClient())
    calls = _counting_generate_content(
        monkeypatch,
        [_response([_function_call_part("run_sql", {"query": "SELECT 1"})])]
        + [_response([_text_part(_CODE_DUMP_REPLY)])]
        * (gemini_agent.MAX_GROUNDING_RETRIES + 1),
    )

    result = await run_chat([{"role": "user", "content": "지난달 대비 순위 변동 보여줘"}])

    assert result["reply"] == gemini_agent._CODE_DUMP_FALLBACK_REPLY
    assert "import pandas" not in result["reply"]
    assert "pd.DataFrame" not in result["reply"]
    assert calls["count"] == gemini_agent.MAX_GROUNDING_RETRIES + 2
    assert calls["count"] <= gemini_agent.MAX_TOOL_ROUNDS


async def test_chart_block_reply_is_not_flagged_as_code_dump(monkeypatch, patch_mcp_client):
    """회귀 방지(최우선): ```chart 블록의 닫는 펜스를 코드 펜스로 오탐하면 안 된다."""
    patch_mcp_client(FakeMcpClient())
    calls = _counting_generate_content(
        monkeypatch,
        [
            _response([_function_call_part("run_sql", {"query": "SELECT 1"})]),
            _response([_text_part(_CHART_REPLY)]),
        ],
    )

    result = await run_chat([{"role": "user", "content": "월별 매출 추이 보여줘"}])

    assert result["reply"] == _CHART_REPLY
    assert calls["count"] == 2


async def test_plain_text_with_inline_code_is_not_flagged_as_code_dump(
    monkeypatch, patch_mcp_client
):
    """인라인 백틱(`SELECT TOP 5`)만 있는 설명 텍스트는 재시도 대상이 아니다."""
    patch_mcp_client(FakeMcpClient())
    reply = "매출 조회는 `SELECT TOP 5` 형태로 수행됩니다. 어떤 기간이 궁금하신가요?"
    calls = _counting_generate_content(monkeypatch, [_response([_text_part(reply)])])

    result = await run_chat([{"role": "user", "content": "어떻게 조회해?"}])

    assert result["reply"] == reply
    assert calls["count"] == 1


async def test_code_dump_retry_emits_distinguishable_warning_log(
    monkeypatch, patch_mcp_client, caplog
):
    patch_mcp_client(FakeMcpClient())
    _counting_generate_content(
        monkeypatch,
        [
            _response([_function_call_part("run_sql", {"query": "SELECT 1"})]),
            _response([_text_part(_CODE_DUMP_REPLY)]),
            _response([_text_part(_TABLE_REPLY)]),
        ],
    )

    with caplog.at_level(logging.WARNING, logger="backend.app.gemini_agent"):
        await run_chat([{"role": "user", "content": "지난달 대비 순위 변동 보여줘"}])

    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("reason=code_dump" in m for m in warnings)
    assert not any("reason=ungrounded" in m for m in warnings)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("```python\nimport pandas as pd\n```", True),
        ("```sql\nSELECT 1\n```", True),
        ("```\nplain code\n```", True),
        ("```chart\n{}\n```", False),
        ("```CHART\n{}\n```", False),
        ("```chart\n{}\n```\n\n```python\nx = 1\n```", True),
        ("인라인 `코드`만 있는 문장", False),
        ("| a | b |\n| --- | --- |\n| 1 | 2 |", False),
        ("", False),
        (None, False),
    ],
)
def test_contains_non_chart_code_block(text, expected):
    assert gemini_agent._contains_non_chart_code_block(text) is expected


async def test_tool_call_is_logged_at_info(monkeypatch, patch_mcp_client, caplog):
    patch_mcp_client(FakeMcpClient())
    _counting_generate_content(
        monkeypatch,
        [
            _response([_function_call_part("run_sql", {"query": "SELECT 1"})]),
            _response([_text_part("완료")]),
        ],
    )

    with caplog.at_level(logging.INFO, logger="backend.app.gemini_agent"):
        await run_chat([{"role": "user", "content": "매출 알려줘"}])

    messages = [r.getMessage() for r in caplog.records]
    assert any("tool_call: name=run_sql" in m for m in messages)
    assert any("result-of-run_sql" in m for m in messages)


async def test_grounding_retry_emits_warning_log(monkeypatch, patch_mcp_client, caplog):
    patch_mcp_client(FakeMcpClient())
    _counting_generate_content(
        monkeypatch,
        [
            _response([_text_part(_TABLE_REPLY)]),
            _response([_function_call_part("run_sql", {"query": "SELECT 1"})]),
            _response([_text_part("확인된 결과입니다")]),
        ],
    )

    with caplog.at_level(logging.WARNING, logger="backend.app.gemini_agent"):
        await run_chat([{"role": "user", "content": "2024년 매출 알려줘"}])

    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("ungrounded_reply" in m for m in warnings)


async def test_generate_content_config_uses_low_temperature(monkeypatch, patch_mcp_client):
    patch_mcp_client(FakeMcpClient())
    calls = _counting_generate_content(monkeypatch, [_response([_text_part("ok")])])

    await run_chat([{"role": "user", "content": "안녕"}])

    assert calls["configs"][0].temperature == gemini_agent.GEMINI_TEMPERATURE
    assert calls["configs"][0].temperature == 0.2


async def test_grounding_retry_does_not_break_max_tool_rounds_fallback(
    monkeypatch, patch_mcp_client
):
    """재시도 도중 MAX_TOOL_ROUNDS가 먼저 소진돼도 기존 폴백으로 안전하게 끝난다."""
    patch_mcp_client(FakeMcpClient())
    monkeypatch.setattr(gemini_agent, "MAX_TOOL_ROUNDS", 2)
    calls = _counting_generate_content(
        monkeypatch, [_response([_text_part(_TABLE_REPLY)])] * 2
    )

    result = await run_chat([{"role": "user", "content": "2024년 매출 알려줘"}])

    assert "도구 호출 횟수를 초과했습니다" in result["reply"]
    assert "키보드" not in result["reply"]
    assert result["tool_calls"] == []
    assert calls["count"] == 2
