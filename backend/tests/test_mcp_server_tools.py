import json

import pytest

from backend.mcp_server import server
from backend.mcp_server.views_whitelist import SALES_VIEW_WHITELIST

VIEW = "dbo.JINJU_SALES"


def _payload(result):
    assert len(result) == 1
    return json.loads(result[0].text)


async def test_list_sales_views_returns_sorted_whitelist():
    result = await server.call_tool("list_sales_views", {})
    assert _payload(result) == sorted(SALES_VIEW_WHITELIST)


async def test_get_view_schema_allowed_view_delegates_to_db(monkeypatch):
    called_with = {}

    def fake_fetch_view_schema(schema, view):
        called_with["schema"] = schema
        called_with["view"] = view
        return [{"COLUMN_NAME": "SALES_AMT", "DATA_TYPE": "money", "IS_NULLABLE": "NO"}]

    monkeypatch.setattr(server.db, "fetch_view_schema", fake_fetch_view_schema)

    result = await server.call_tool("get_view_schema", {"view_name": VIEW})
    payload = _payload(result)

    assert called_with == {"schema": "dbo", "view": "JINJU_SALES"}
    assert payload == [{"COLUMN_NAME": "SALES_AMT", "DATA_TYPE": "money", "IS_NULLABLE": "NO"}]


async def test_get_view_schema_disallowed_view_returns_error_json(monkeypatch):
    called = False

    def fake_fetch_view_schema(schema, view):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(server.db, "fetch_view_schema", fake_fetch_view_schema)

    result = await server.call_tool("get_view_schema", {"view_name": "dbo.Employee"})
    payload = _payload(result)

    assert "error" in payload
    assert called is False


async def test_get_view_schema_with_korean_alias_resolves(monkeypatch):
    monkeypatch.setattr(server.db, "fetch_view_schema", lambda schema, view: [])
    result = await server.call_tool("get_view_schema", {"view_name": "매출"})
    payload = _payload(result)
    assert payload == []


async def test_get_view_aliases_passthrough():
    result = await server.call_tool("get_view_aliases", {})
    payload = _payload(result)
    assert any(item["view_name"] == VIEW for item in payload)


async def test_get_column_aliases_passthrough():
    result = await server.call_tool("get_column_aliases", {"view_name": VIEW})
    payload = _payload(result)
    assert any(item["column_name"] == "SALES_AMT" for item in payload)


async def test_run_sql_valid_query_delegates_to_db(monkeypatch):
    captured_query = {}

    def fake_run_readonly_query(sql):
        captured_query["sql"] = sql
        return [{"SALES_AMT": 1000}]

    monkeypatch.setattr(server.db, "run_readonly_query", fake_run_readonly_query)

    result = await server.call_tool("run_sql", {"query": f"SELECT SALES_AMT FROM {VIEW}"})
    payload = _payload(result)

    assert payload == [{"SALES_AMT": 1000}]
    assert "TOP 1000" in captured_query["sql"].upper()


async def test_run_sql_forbidden_query_never_reaches_db(monkeypatch):
    called = False

    def fake_run_readonly_query(sql):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(server.db, "run_readonly_query", fake_run_readonly_query)

    result = await server.call_tool("run_sql", {"query": f"DROP TABLE {VIEW}"})
    payload = _payload(result)

    assert "error" in payload
    assert called is False


async def test_unknown_tool_name_returns_error_json():
    result = await server.call_tool("delete_everything", {})
    payload = _payload(result)
    assert "error" in payload
    assert "알 수 없는 도구" in payload["error"]


async def test_db_exception_is_caught_and_returned_as_error_json(monkeypatch):
    def raise_db_error(sql):
        raise RuntimeError("DB connection lost")

    monkeypatch.setattr(server.db, "run_readonly_query", raise_db_error)

    result = await server.call_tool("run_sql", {"query": f"SELECT SALES_AMT FROM {VIEW}"})
    payload = _payload(result)

    assert "error" in payload
    assert "DB connection lost" in payload["error"]
