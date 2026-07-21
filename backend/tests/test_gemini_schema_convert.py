from google.genai import types

from backend.app.gemini_agent import _json_schema_to_gemini_schema
from backend.mcp_server.server import list_tools


def test_object_with_properties_and_required():
    schema = {
        "type": "object",
        "properties": {"view_name": {"type": "string", "description": "뷰 이름"}},
        "required": ["view_name"],
    }
    result = _json_schema_to_gemini_schema(schema)
    assert result.type == types.Type.OBJECT
    assert "view_name" in result.properties
    assert result.properties["view_name"].type == types.Type.STRING
    assert result.required == ["view_name"]


def test_simple_scalar_types():
    for json_type, gemini_type in [
        ("string", types.Type.STRING),
        ("number", types.Type.NUMBER),
        ("integer", types.Type.INTEGER),
        ("boolean", types.Type.BOOLEAN),
    ]:
        result = _json_schema_to_gemini_schema({"type": json_type})
        assert result.type == gemini_type


def test_array_with_items_recurses():
    schema = {"type": "array", "items": {"type": "string"}}
    result = _json_schema_to_gemini_schema(schema)
    assert result.type == types.Type.ARRAY
    assert result.items.type == types.Type.STRING


def test_object_without_properties_has_no_properties_field():
    result = _json_schema_to_gemini_schema({"type": "object", "properties": {}})
    assert result.properties is None


def test_description_included_when_present():
    result = _json_schema_to_gemini_schema({"type": "string", "description": "desc"})
    assert result.description == "desc"


def test_description_omitted_when_absent():
    result = _json_schema_to_gemini_schema({"type": "string"})
    assert result.description is None


async def test_real_server_tool_schemas_convert_without_error():
    tools = await list_tools()
    assert len(tools) == 5
    for tool in tools:
        converted = _json_schema_to_gemini_schema(tool.inputSchema)
        assert converted.type == types.Type.OBJECT
