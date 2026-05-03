from marneo.tools.registry import registry


def test_load_all_tools_skips_external_tools_in_local_only_mode(monkeypatch):
    from marneo.core.paths import get_config_path
    from marneo.tools.loader import load_all_tools

    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("privacy:\n  local_only: true\n", encoding="utf-8")
    registry._tools.clear()

    load_all_tools()

    assert "read_file" in registry._tools
    assert "write_file" in registry._tools
    assert "bash" in registry._tools
    assert "web_fetch" not in registry._tools
    assert "web_search" not in registry._tools
    assert "lark_cli" not in registry._tools
    assert "feishu_send_mention" not in registry._tools
