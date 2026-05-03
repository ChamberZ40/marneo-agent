# tests/tools/test_registry.py
import json
import pytest
from marneo.tools.registry import ToolRegistry, tool_result, tool_error


def test_register_and_dispatch_sync():
    reg = ToolRegistry()
    reg.register(
        name="echo",
        description="echo args",
        schema={"name": "echo", "description": "echo", "parameters": {"type": "object", "properties": {"msg": {"type": "string"}}, "required": ["msg"]}},
        handler=lambda args, **kw: tool_result(msg=args["msg"]),
    )
    out = reg.dispatch("echo", {"msg": "hello"})
    assert json.loads(out) == {"msg": "hello"}


def test_dispatch_unknown_returns_error():
    reg = ToolRegistry()
    out = reg.dispatch("nope", {})
    assert "error" in json.loads(out)


def test_register_and_dispatch_async():
    import asyncio
    reg = ToolRegistry()

    async def async_handler(args, **kw):
        return tool_result(value=42)

    reg.register(name="async_tool", description="", schema={"name": "async_tool", "description": "", "parameters": {"type": "object", "properties": {}}}, handler=async_handler, is_async=True)
    out = reg.dispatch("async_tool", {})
    assert json.loads(out) == {"value": 42}


def test_get_definitions_returns_openai_format():
    reg = ToolRegistry()
    reg.register(name="t", description="test", schema={"name": "t", "description": "test", "parameters": {"type": "object", "properties": {}}}, handler=lambda args, **kw: tool_result())
    defs = reg.get_definitions()
    assert len(defs) == 1
    assert defs[0]["type"] == "function"
    assert defs[0]["function"]["name"] == "t"


def test_tool_error_helper():
    out = tool_error("something broke")
    assert json.loads(out) == {"error": "something broke"}


def test_tool_result_helper():
    out = tool_result(x=1, y=2)
    assert json.loads(out) == {"x": 1, "y": 2}


def test_check_fn_excludes_unavailable_tools():
    reg = ToolRegistry()
    reg.register(name="maybe", description="", schema={"name": "maybe", "description": "", "parameters": {"type": "object", "properties": {}}}, handler=lambda args, **kw: "", check_fn=lambda: False)
    defs = reg.get_definitions()
    assert len(defs) == 0


def test_local_only_blocks_network_tool_definitions(monkeypatch):
    from marneo.core.paths import get_config_path

    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("privacy:\n  local_only: true\n", encoding="utf-8")

    reg = ToolRegistry()
    reg.register(
        name="web_fetch",
        description="fetch",
        schema={"name": "web_fetch", "description": "fetch", "parameters": {"type": "object", "properties": {}}},
        handler=lambda args, **kw: tool_result(),
        network_scope="external",
    )
    reg.register(
        name="read_file",
        description="read",
        schema={"name": "read_file", "description": "read", "parameters": {"type": "object", "properties": {}}},
        handler=lambda args, **kw: tool_result(),
        network_scope="local",
    )

    defs = reg.get_definitions()

    assert [d["function"]["name"] for d in defs] == ["read_file"]


def test_local_only_blocks_external_tool_dispatch():
    from marneo.core.paths import get_config_path

    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("privacy:\n  local_only: true\n", encoding="utf-8")

    reg = ToolRegistry()
    reg.register(
        name="web_fetch",
        description="fetch",
        schema={"name": "web_fetch", "description": "fetch", "parameters": {"type": "object", "properties": {}}},
        handler=lambda args, **kw: tool_result(ok=True),
        network_scope="external",
    )

    out = json.loads(reg.dispatch("web_fetch", {"url": "https://example.com"}))

    assert "error" in out
    assert "local-only" in out["error"]
