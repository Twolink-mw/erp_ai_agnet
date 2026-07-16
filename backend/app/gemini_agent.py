"""Gemini 기반 대화 + MCP 도구 호출 루프."""

from google import genai
from google.genai import types

from .config import GEMINI_API_KEY, GEMINI_MODEL, GEMINI_USE_VERTEX, SYSTEM_PROMPT
from .mcp_client import McpSalesClient

# Vertex AI Express Mode: an API key alone selects the project, so project/
# location must be omitted (the SDK rejects passing both).
_client = genai.Client(api_key=GEMINI_API_KEY, vertexai=GEMINI_USE_VERTEX)

MAX_TOOL_ROUNDS = 6


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

        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=[gemini_tool],
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
                return {"reply": reply_text, "tool_calls": tool_calls_log}

            contents.append(candidate.content)

            response_parts = []
            for call in function_calls:
                args = dict(call.args or {})
                output = await mcp_client.call_tool(call.name, args)
                tool_calls_log.append({"name": call.name, "input": args, "output": output})
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
