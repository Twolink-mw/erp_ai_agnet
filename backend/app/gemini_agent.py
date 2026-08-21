"""Gemini 기반 대화 + MCP 도구 호출 루프."""

import logging
import re

from google import genai
from google.genai import types

from .config import GEMINI_API_KEY, GEMINI_MODEL, GEMINI_USE_VERTEX, SYSTEM_PROMPT
from .mcp_client import McpSalesClient
from .pdf_report import has_reportable_content

logger = logging.getLogger(__name__)

# Vertex AI Express Mode: an API key alone selects the project, so project/
# location must be omitted (the SDK rejects passing both).
_client = genai.Client(api_key=GEMINI_API_KEY, vertexai=GEMINI_USE_VERTEX)

# 다단계 분석(별칭 해석 2회 + 스키마 조회 + 여러 뷰/기간 순차 조회 + 재시도)에
# 6라운드는 부족했다. 프론트의 proxyTimeout(next.config.js, 240초) 안에서 끝나야
# 하므로, 라운드당 대략 3~8초(Gemini 호출 + SQL 실행)를 가정해 10으로 상향한다.
# 다만 Gemini API 응답 자체가 드물게 100초 이상 걸리는 지연 스파이크가 실측된 바
# 있어, 그런 라운드가 한두 번만 겹쳐도 최악 케이스는 이 가정보다 훨씬 커질 수
# 있다 — proxyTimeout을 120초에서 240초로 올린 이유이기도 하다.
MAX_TOOL_ROUNDS = 10

# 도구 호출 없이 표/차트(=데이터처럼 보이는 응답)를 만들어냈거나, 실행되지 않는
# 코드를 답변으로 출력한 경우 모델에게 재작성을 요구하는 횟수 상한.
# 두 사유가 이 예산을 공유하며, MAX_TOOL_ROUNDS 예산 안에서 소비되므로
# 별도의 타임아웃 위험은 없다.
MAX_GROUNDING_RETRIES = 2

# 코드 펜스 "줄"만 잡는다 (pdf_report._FENCE_RE와 같은 계약: 줄 전체가 펜스여야 한다).
# 문장 중간의 백틱이나 인라인 코드(`SELECT`)는 걸리지 않아 오탐이 적다.
_FENCE_LINE_RE = re.compile(r"^[ \t]*```[ \t]*([A-Za-z0-9_+#.-]*)[ \t]*$", re.M)
_CHART_FENCE_LANG = "chart"


def _contains_non_chart_code_block(text: str) -> bool:
    """```chart 이외의 코드 펜스(=실행되지 않는 코드 덤프)가 있는지 판정한다.

    닫는 펜스는 언어 태그가 없으므로 단순히 "```chart가 아닌 펜스"를 찾으면
    정상적인 ```chart 블록의 닫는 줄까지 오탐한다. 그래서 펜스를
    열림/닫힘으로 번갈아 해석해 "여는 펜스"의 언어 태그만 검사한다.
    """
    if not text:
        return False
    inside = False
    for match in _FENCE_LINE_RE.finditer(text):
        if inside:
            inside = False  # 닫는 펜스 — 언어 태그를 보지 않는다.
            continue
        inside = True
        if (match.group(1) or "").strip().lower() != _CHART_FENCE_LANG:
            return True
    return False

# 데이터 요약 워크로드에서 응답 변동성을 줄이기 위한 보조 수단.
# 근본 방어는 아래 그라운딩 체크가 담당한다.
GEMINI_TEMPERATURE = 0.2

_GROUNDING_CORRECTION_MESSAGE = (
    "[시스템] 방금 응답에는 표나 차트 등 데이터가 포함됐지만, 이번 대화에서 run_sql 도구를"
    " 한 번도 호출하지 않았다. 조회하지 않은 수치를 지어내서는 안 된다."
    " 반드시 필요한 도구(get_view_aliases / get_column_aliases / get_view_schema / run_sql)를"
    " 먼저 호출해 실제 값을 확인한 뒤 답변을 다시 작성하라."
    " 도구로 확인할 수 없다면 수치를 만들어내지 말고 확인할 수 없다고 솔직히 답하라."
)

_CODE_DUMP_CORRECTION_MESSAGE = (
    "[시스템] 방금 응답에 코드 블록(```python / ```sql 등)이 포함됐다. 이 대화에는 코드를"
    " 실행해줄 도구가 없으므로 사용자에게는 실행되지 않은 코드 텍스트만 보인다."
    " 코드를 제시하지 말고, 필요한 계산(정렬, 순위, 전월 대비 증감 등)은 네가 직접 수행해"
    " 최종 결과만 마크다운 표와 설명 텍스트로 다시 작성하라."
    " 계산에 필요한 값이 부족하면 run_sql로 먼저 조회하라."
    " ```chart 블록 외의 코드 블록은 절대 포함하지 않는다."
)

_CODE_DUMP_FALLBACK_REPLY = (
    "죄송합니다. 요청하신 계산 결과를 표 형태로 정리하지 못했습니다. "
    "조회 조건(기간, 항목, 비교 대상)을 조금 더 구체적으로 알려주시면 다시 정리해 드리겠습니다."
)

_UNGROUNDED_FALLBACK_REPLY = (
    "죄송합니다. 실제 데이터를 조회해 확인하지 못했습니다. "
    "확인되지 않은 수치를 안내할 수는 없어 답변을 제공하지 않습니다. "
    "질문의 기간이나 항목을 조금 더 구체적으로 알려주시면 다시 조회해 보겠습니다."
)


def _truncate(value, limit: int) -> str:
    """로그용 문자열 길이 제한 (SQL 원문 등 과다 노출 방지)."""
    text = str(value)
    if len(text) <= limit:
        return text
    return text[:limit] + "...(truncated)"


def _json_schema_to_gemini_schema(schema: dict) -> types.Schema:
    type_map = {
        "object": types.Type.OBJECT,
        "string": types.Type.STRING,
        "number": types.Type.NUMBER,
        "integer": types.Type.INTEGER,
        "boolean": types.Type.BOOLEAN,
        "array": types.Type.ARRAY,
    }
    kwargs: dict = {"type": type_map.get(schema.get("type", "object"), types.Type.OBJECT)}
    if "description" in schema:
        kwargs["description"] = schema["description"]
    if schema.get("type") == "object":
        props = schema.get("properties", {})
        if props:
            kwargs["properties"] = {k: _json_schema_to_gemini_schema(v) for k, v in props.items()}
        if schema.get("required"):
            kwargs["required"] = schema["required"]
    if schema.get("type") == "array" and "items" in schema:
        kwargs["items"] = _json_schema_to_gemini_schema(schema["items"])
    return types.Schema(**kwargs)


async def _mcp_tools_as_gemini_tool(mcp_client: McpSalesClient) -> types.Tool:
    tools = await mcp_client.list_tools()
    declarations = [
        types.FunctionDeclaration(
            name=t.name,
            description=t.description or "",
            parameters=_json_schema_to_gemini_schema(t.inputSchema),
        )
        for t in tools
    ]
    return types.Tool(function_declarations=declarations)


async def run_chat(messages: list[dict]) -> dict:
    """messages: [{"role": "user"|"assistant", "content": str}, ...]

    반환: {"reply": str, "tool_calls": [{"name": str, "input": dict, "output": str}]}
    """
    mcp_client = McpSalesClient()
    try:
        await mcp_client.__aenter__()
        gemini_tool = await _mcp_tools_as_gemini_tool(mcp_client)
    except Exception:
        # MCP 연결/도구 목록 조회 실패 시 개발용 폴백 응답을 반환합니다.
        await mcp_client.__aexit__(None, None, None)
        return {
            "reply": (
                "도구 연결 실패: 내부 MCP 서비스에 접근할 수 없습니다. "
                "개발 환경에서는 제한된 응답이 제공됩니다. 요청을 다시 시도해 주세요."
            ),
            "tool_calls": [],
        }

    try:
        contents = [
            types.Content(
                role="model" if m["role"] == "assistant" else "user",
                parts=[types.Part.from_text(text=m["content"])],
            )
            for m in messages
        ]
        tool_calls_log: list[dict] = []
        grounding_retries = 0
        # 이전 assistant 메시지에 이미 표/차트가 있으면 "직전 결과 재사용"(PDF/이메일)
        # 정상 플로우이므로 그라운딩 체크를 건너뛴다.
        history_already_grounded = any(
            m.get("role") == "assistant" and has_reportable_content(m.get("content") or "")
            for m in messages
        )

        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=[gemini_tool],
            temperature=GEMINI_TEMPERATURE,
        )

        for _ in range(MAX_TOOL_ROUNDS):
            response = _client.models.generate_content(
                model=GEMINI_MODEL,
                contents=contents,
                config=config,
            )

            candidate = response.candidates[0]
            function_calls = [
                part.function_call for part in candidate.content.parts if part.function_call
            ]

            if not function_calls:
                reply_text = "".join(
                    part.text for part in candidate.content.parts if part.text
                )

                # 도구를 "전혀" 호출하지 않고 데이터를 지어낸 경우만 잡는다.
                # get_view_schema/list_sales_views 등 어떤 도구든 실제로 호출됐다면
                # 모델이 실제 조회를 시도한 것으로 보고 신뢰한다 — run_sql만 인정하면
                # 스키마 질문에 표로 답하는 정상 응답까지 폐기되는 오탐이 난다.
                any_tool_called_this_turn = bool(tool_calls_log)
                looks_like_data = has_reportable_content(reply_text)

                is_ungrounded = (
                    looks_like_data
                    and not any_tool_called_this_turn
                    and not history_already_grounded
                )
                # 코드 덤프는 도구 호출 여부와 무관하게 형식 위반이다 — 실제 데이터를
                # 조회했더라도 결과를 실행되지 않는 코드로 포장하면 답이 되지 않는다.
                is_code_dump = _contains_non_chart_code_block(reply_text)

                if is_ungrounded or is_code_dump:
                    reasons = []
                    corrections = []
                    if is_ungrounded:
                        reasons.append("ungrounded")
                        corrections.append(_GROUNDING_CORRECTION_MESSAGE)
                    if is_code_dump:
                        reasons.append("code_dump")
                        corrections.append(_CODE_DUMP_CORRECTION_MESSAGE)
                    reason = "+".join(reasons)

                    if grounding_retries < MAX_GROUNDING_RETRIES:
                        grounding_retries += 1
                        logger.warning(
                            "ungrounded_reply: reason=%s (%s) — 재요청 %d/%d, preview=%s",
                            reason,
                            "run_sql 미호출 상태로 표/차트 응답 감지"
                            if is_ungrounded
                            else "실행되지 않는 코드 블록을 최종 답변으로 출력",
                            grounding_retries,
                            MAX_GROUNDING_RETRIES,
                            _truncate(reply_text, 300),
                        )
                        contents.append(candidate.content)
                        contents.append(
                            types.Content(
                                role="user",
                                parts=[
                                    types.Part.from_text(text="\n".join(corrections))
                                ],
                            )
                        )
                        continue

                    logger.warning(
                        "ungrounded_reply_dropped: reason=%s, 재시도 예산 소진, 안전 폴백 반환."
                        " preview=%s",
                        reason,
                        _truncate(reply_text, 300),
                    )
                    return {
                        # 근거 없는 수치가 문제인 경우가 더 심각하므로 그쪽 문구를 우선한다.
                        "reply": _UNGROUNDED_FALLBACK_REPLY
                        if is_ungrounded
                        else _CODE_DUMP_FALLBACK_REPLY,
                        "tool_calls": tool_calls_log,
                    }

                return {"reply": reply_text, "tool_calls": tool_calls_log}

            contents.append(candidate.content)

            response_parts = []
            for call in function_calls:
                args = dict(call.args or {})
                output = await mcp_client.call_tool(call.name, args)
                tool_calls_log.append({"name": call.name, "input": args, "output": output})
                logger.info(
                    "tool_call: name=%s args=%s output_preview=%s",
                    call.name,
                    _truncate(args, 300),
                    _truncate(output, 300),
                )
                response_parts.append(
                    types.Part.from_function_response(
                        name=call.name,
                        response={"result": output},
                    )
                )

            contents.append(types.Content(role="user", parts=response_parts))

        return {
            "reply": "죄송합니다, 요청을 처리하는 데 필요한 도구 호출 횟수를 초과했습니다. 질문을 더 구체적으로 나눠서 다시 시도해 주세요.",
            "tool_calls": tool_calls_log,
        }
    finally:
        await mcp_client.__aexit__(None, None, None)
