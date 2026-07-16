"""MSSQL 매출 뷰 MCP 서버에 대한 클라이언트 세션 관리.

FastAPI 프로세스가 stdio로 mcp_server.server 를 서브프로세스로 띄우고,
Gemini 도구 호출을 이 MCP 세션으로 그대로 중계한다.

세션은 요청(대화 1턴)마다 새로 열고 닫는다 — 앱 전체에서 세션 하나를
공유하면 동시 채팅 요청이 같은 stdio 파이프를 두고 경합하며 서로의
도구 호출을 직렬화시켜, 동시 사용 시 응답이 크게 느려지거나 타임아웃난다.
"""

import os
import sys
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class McpSalesClient:
    """요청 하나의 수명 동안만 사용하는 MCP 세션. `async with`로 사용한다."""

    def __init__(self) -> None:
        self._stack = AsyncExitStack()
        self.session: ClientSession | None = None

    async def __aenter__(self) -> "McpSalesClient":
        params = StdioServerParameters(
            command=sys.executable,
            # Run the MCP server as a module using the full package path so
            # it can be found when the backend is started from the workspace root.
            args=["-m", "backend.mcp_server.server"],
            # mcp's default subprocess env only inherits a small OS whitelist
            # (PATH, APPDATA, ...), so MSSQL_*/GEMINI_* from our .env would be
            # dropped unless passed through explicitly here.
            env=dict(os.environ),
        )
        read_stream, write_stream = await self._stack.enter_async_context(stdio_client(params))
        self.session = await self._stack.enter_async_context(ClientSession(read_stream, write_stream))
        await self.session.initialize()
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self._stack.aclose()

    async def list_tools(self):
        assert self.session is not None
        result = await self.session.list_tools()
        return result.tools

    async def call_tool(self, name: str, arguments: dict) -> str:
        assert self.session is not None
        result = await self.session.call_tool(name, arguments)
        return "\n".join(
            block.text for block in result.content if getattr(block, "type", None) == "text"
        )
