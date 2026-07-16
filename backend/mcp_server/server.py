"""매출 뷰 전용 MS-SQL MCP 서버.

stdio 기반 MCP 서버로, 다음 도구만 노출한다:
- list_sales_views: 접근 가능한 매출 뷰 목록 조회
- get_view_schema: 특정 뷰의 컬럼 스키마 조회
- run_sql: 화이트리스트 뷰에 대한 SELECT 전용 쿼리 실행

이 서버 프로세스만 실제 DB 자격증명을 알고 있으며,
에이전트(Claude)는 이 도구들을 통해서만 데이터에 접근한다.
"""

import asyncio
import json

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from . import db
from .sql_guard import SqlGuardError, validate_and_prepare
from .views_whitelist import (
    SALES_VIEW_WHITELIST,
    get_column_aliases,
    get_view_aliases,
    resolve_view_name,
)

server = Server("mssql-sales-view-server")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="list_sales_views",
            description="접근 가능한 매출 관련 뷰 목록을 반환한다.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="get_view_schema",
            description="지정한 매출 뷰의 컬럼명/타입 스키마를 반환한다.",
            inputSchema={
                "type": "object",
                "properties": {
                    "view_name": {
                        "type": "string",
                        "description": "schema.view 형식 또는 한글 별칭(예: dbo.JINJU_SALES 또는 매출)",
                    }
                },
                "required": ["view_name"],
            },
        ),
        Tool(
            name="get_view_aliases",
            description="한글 뷰 별칭과 실제 뷰 이름을 반환한다.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="get_column_aliases",
            description="지정한 뷰의 한글 컬럼 별칭을 반환한다.",
            inputSchema={
                "type": "object",
                "properties": {
                    "view_name": {
                        "type": "string",
                        "description": "schema.view 형식 또는 한글 뷰 별칭(예: dbo.JINJU_SALES 또는 매출)",
                    }
                },
                "required": ["view_name"],
            },
        ),
        Tool(
            name="run_sql",
            description=(
                "허용된 매출 뷰에 대한 SELECT 쿼리를 실행한다. "
                "집계(GROUP BY), 필터(WHERE), 정렬 등 읽기 전용 분석 쿼리만 가능하다."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "실행할 SELECT SQL 문"}
                },
                "required": ["query"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "list_sales_views":
            payload = sorted(SALES_VIEW_WHITELIST)
        elif name == "get_view_schema":
            view_name = arguments["view_name"]
            canonical = resolve_view_name(view_name)
            if canonical is None or canonical.lower() not in {v.lower() for v in SALES_VIEW_WHITELIST}:
                raise SqlGuardError(f"'{view_name}' 은(는) 허용되지 않은 뷰입니다.")
            schema, view = canonical.split(".", 1)
            payload = db.fetch_view_schema(schema, view)
        elif name == "get_view_aliases":
            payload = get_view_aliases()
        elif name == "get_column_aliases":
            view_name = arguments["view_name"]
            payload = get_column_aliases(view_name)
        elif name == "run_sql":
            safe_query = validate_and_prepare(arguments["query"])
            payload = db.run_readonly_query(safe_query)
        else:
            raise ValueError(f"알 수 없는 도구: {name}")

        return [TextContent(type="text", text=json.dumps(payload, default=str, ensure_ascii=False))]
    except SqlGuardError as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}, ensure_ascii=False))]
    except Exception as e:  # noqa: BLE001 - MCP 도구 에러는 텍스트로 반환
        return [TextContent(type="text", text=json.dumps({"error": f"실행 오류: {e}"}, ensure_ascii=False))]


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
