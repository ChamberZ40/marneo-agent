from __future__ import annotations

import json
from pathlib import Path

import pytest

from marneo.tools.registry import ToolRegistry, tool_result
from tests.stress import conftest as stress_conftest
from tests.stress import test_feishu_stress


def _existing_tool_schema(name: str) -> dict:
    return {
        "name": name,
        "description": f"existing {name}",
        "parameters": {"type": "object", "properties": {}},
    }


def test_stress_tool_registration_fills_missing_tools_without_overwriting_existing(monkeypatch):
    reg = ToolRegistry()
    reg.register(
        name="get_current_time",
        description="existing time tool",
        schema=_existing_tool_schema("get_current_time"),
        handler=lambda args, **kw: tool_result(existing=True),
    )
    monkeypatch.setattr(test_feishu_stress, "global_registry", reg)

    test_feishu_stress._register_stress_tools()

    assert json.loads(reg.dispatch("get_current_time", {})) == {"existing": True}
    assert reg.get_entry("calculate") is not None
    assert reg.get_entry("search_knowledge") is not None


def test_stress_tool_registration_is_idempotent_for_all_existing_tools(monkeypatch):
    reg = ToolRegistry()
    for tool_name in ("get_current_time", "calculate", "search_knowledge"):
        reg.register(
            name=tool_name,
            description=f"existing {tool_name}",
            schema=_existing_tool_schema(tool_name),
            handler=lambda args, name=tool_name, **kw: tool_result(existing=name),
        )
    monkeypatch.setattr(test_feishu_stress, "global_registry", reg)

    before = {
        name: (entry.description, entry.schema, entry.handler)
        for name in ("get_current_time", "calculate", "search_knowledge")
        for entry in [reg.get_entry(name)]
    }

    test_feishu_stress._register_stress_tools()
    test_feishu_stress._register_stress_tools()

    after = {
        name: (entry.description, entry.schema, entry.handler)
        for name in ("get_current_time", "calculate", "search_knowledge")
        for entry in [reg.get_entry(name)]
    }
    assert after == before
    assert json.loads(reg.dispatch("calculate", {})) == {"existing": "calculate"}
    assert json.loads(reg.dispatch("search_knowledge", {})) == {"existing": "search_knowledge"}


def test_stress_reporter_redacts_secret_like_values(tmp_path, monkeypatch):
    monkeypatch.setattr(stress_conftest, "RESULTS_DIR", tmp_path)
    reporter = stress_conftest.StressReporter("redaction_check")

    bearer_token = "abcdefghijklmnopqrstuvwxyz123456"
    json_access_token = "zyxwvutsrqponmlkjihgfedcba654321"
    provider_key = "sk-proj_abcdefghijklmnopqrstuvwxyz123456"
    raw_authorization = "Authorization: zyxwvutsrqponmlkjihgfedcba654321"
    reporter.set_provider("provider", f"model access_key: {json_access_token}")
    reporter.record_round(
        error=f"Authorization: Bearer {bearer_token}",
        auth_header=raw_authorization,
        json_error=f'{{"access_token": "{json_access_token}", "safe": true}}',
        key_value_error=f"api_key: {provider_key}",
        nested={
            "api_key": provider_key,
            "safe": "ordinary value",
        },
        values=[f"ticket={bearer_token}", f"ticket: {json_access_token}"],
    )

    path = reporter.save()
    saved = Path(path).read_text(encoding="utf-8")

    saved_report = json.loads(saved)

    assert bearer_token not in saved
    assert json_access_token not in saved
    assert provider_key not in saved
    assert raw_authorization not in saved
    assert saved_report["rounds"][0]["error"] == "Authorization: Bearer [REDACTED]"
    assert saved_report["rounds"][0]["auth_header"] == "Authorization: [REDACTED]"
    assert saved_report["rounds"][0]["json_error"] == '{"access_token": "[REDACTED]", "safe": true}'
    assert saved_report["provider"] == "model access_key: [REDACTED] (provider)"
    assert "[REDACTED" in saved
    assert "ordinary value" in saved


def test_stress_opt_in_skips_before_provider_pool_import(monkeypatch):
    monkeypatch.delenv(stress_conftest.STRESS_OPT_IN_ENV, raising=False)

    with pytest.raises(pytest.skip.Exception):
        next(stress_conftest.hermetic_env.__wrapped__())
