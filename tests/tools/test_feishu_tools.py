# tests/tools/test_feishu_tools.py
import json
import pytest
from marneo.tools.core.feishu_tools import (
    _build_mention_text, feishu_send_mention, feishu_search_user, feishu_create_doc
)


# ── _build_mention_text ──────────────────────────────────────────────────────

def test_build_mention_text_single_user():
    result = _build_mention_text(
        [{"open_id": "ou_123", "name": "张三"}],
        "你好"
    )
    assert '<at user_id="ou_123">张三</at>' in result
    assert "你好" in result


def test_build_mention_text_multiple_users():
    result = _build_mention_text([
        {"open_id": "ou_1", "name": "A"},
        {"open_id": "ou_2", "name": "B"},
    ], "开会")
    assert '<at user_id="ou_1">A</at>' in result
    assert '<at user_id="ou_2">B</at>' in result
    assert "开会" in result


def test_build_mention_text_at_all():
    result = _build_mention_text([{"open_id": "all", "name": ""}], "注意")
    assert '<at user_id="all">所有人</at>' in result


def test_build_mention_text_empty():
    result = _build_mention_text([], "hello")
    assert result == "hello"


def test_build_mention_text_no_text():
    result = _build_mention_text([{"open_id": "ou_1", "name": "X"}])
    assert '<at user_id="ou_1">X</at>' in result


def test_build_mention_text_missing_name_uses_default():
    result = _build_mention_text([{"open_id": "ou_99"}], "hi")
    assert '<at user_id="ou_99">用户</at>' in result


# ── feishu_send_mention validation ───────────────────────────────────────────

def test_send_mention_missing_chat_id():
    result = json.loads(feishu_send_mention({}))
    assert "error" in result


def test_send_mention_no_credentials():
    """When no Feishu credentials configured, returns error."""
    from unittest.mock import patch
    with patch("marneo.employee.feishu_config.list_configured_employees", return_value=[]):
        result = json.loads(feishu_send_mention({
            "chat_id": "oc_test",
            "mentions": [{"open_id": "ou_1", "name": "Test"}],
            "text": "hello",
        }))
    assert "error" in result


# ── feishu_search_user validation ────────────────────────────────────────────

def test_search_user_missing_query():
    result = json.loads(feishu_search_user({}))
    assert "error" in result


def test_search_user_no_lark_cli():
    """When lark-cli not found, returns error."""
    from unittest.mock import patch
    with patch("shutil.which", return_value=None):
        result = json.loads(feishu_search_user({"query": "test"}))
    assert "error" in result


# ── feishu_create_doc validation ─────────────────────────────────────────────

def test_create_doc_missing_content():
    result = json.loads(feishu_create_doc({}))
    assert "error" in result


def test_create_doc_delegates_to_lark_cli():
    """Verify it calls lark_cli with the right command."""
    from unittest.mock import patch
    with patch("marneo.tools.core.lark_cli.lark_cli", return_value='{"ok": true}') as mock:
        result = feishu_create_doc({"title": "Test Doc", "content": "# Hello"})
        mock.assert_called_once()
        call_args = mock.call_args[0][0]
        assert "docs +create" in call_args["command"]
        assert "Test Doc" in call_args["command"]
