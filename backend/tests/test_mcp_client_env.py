"""McpSalesClient의 서브프로세스 실행 파라미터 및 결과 처리 검증.

실제 stdio 서브프로세스를 띄우지 않도록 mcp_client 모듈이 참조하는
stdio_client / ClientSession을 가짜로 치환한다.
"""

import os
import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from backend.app import mcp_client as mcp_client_module
from backend.app.mcp_client import McpSalesClient


class FakeClientSession:
    def __init__(self, read_stream, write_stream):
        self.read_stream = read_stream
        self.write_stream = write_stream
        self.initialized = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        pass

    async def initialize(self):
        self.initialized = True

    async def list_tools(self):
        return SimpleNamespace(tools=["dummy"])

    async def call_tool(self, name, arguments):
        return SimpleNamespace(
            content=[
                SimpleNamespace(type="text", text="첫번째"),
                SimpleNamespace(type="text", text="두번째"),
                SimpleNamespace(type="image", text="무시되어야 함"),
            ]
        )


@pytest.fixture
def captured_params(monkeypatch):
    captured = {}

    @asynccontextmanager
    async def fake_stdio_client(params):
        captured["params"] = params
        yield ("read-stream", "write-stream")

    monkeypatch.setattr(mcp_client_module, "stdio_client", fake_stdio_client)
    monkeypatch.setattr(mcp_client_module, "ClientSession", FakeClientSession)
    return captured


async def test_subprocess_env_includes_full_parent_environment(monkeypatch, captured_params):
    monkeypatch.setenv("MSSQL_SERVER", "test-server")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    async with McpSalesClient():
        pass

    env = captured_params["params"].env
    assert env["MSSQL_SERVER"] == "test-server"
    assert env["GEMINI_API_KEY"] == "test-key"
    assert env == dict(os.environ)


async def test_subprocess_command_and_args(captured_params):
    async with McpSalesClient():
        pass

    params = captured_params["params"]
    assert params.command == sys.executable
    assert params.args == ["-m", "backend.mcp_server.server"]


async def test_call_tool_joins_text_blocks_and_skips_non_text(captured_params):
    async with McpSalesClient() as client:
        result = await client.call_tool("run_sql", {"query": "SELECT 1"})

    assert result == "첫번째\n두번째"
