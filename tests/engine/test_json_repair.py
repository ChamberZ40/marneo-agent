# tests/engine/test_json_repair.py
"""Tests for marneo.engine.json_repair."""
import json
import pytest
from marneo.engine.json_repair import repair_json


class TestRepairJson:
    def test_valid_json_unchanged(self):
        raw = '{"command": "ls -la"}'
        assert repair_json(raw) == raw

    def test_empty_string_returns_empty_object(self):
        assert repair_json("") == "{}"
        assert repair_json("  ") == "{}"

    def test_trailing_comma_object(self):
        raw = '{"a": 1, "b": 2,}'
        result = json.loads(repair_json(raw))
        assert result == {"a": 1, "b": 2}

    def test_trailing_comma_array(self):
        raw = '[1, 2, 3,]'
        result = json.loads(repair_json(raw))
        assert result == [1, 2, 3]

    def test_python_none(self):
        raw = '{"value": None}'
        result = json.loads(repair_json(raw))
        assert result == {"value": None}

    def test_python_true_false(self):
        raw = '{"a": True, "b": False}'
        result = json.loads(repair_json(raw))
        assert result == {"a": True, "b": False}

    def test_unclosed_brace(self):
        raw = '{"command": "echo hello"'
        result = json.loads(repair_json(raw))
        assert result == {"command": "echo hello"}

    def test_unclosed_bracket(self):
        raw = '["a", "b"'
        result = json.loads(repair_json(raw))
        assert result == ["a", "b"]

    def test_markdown_code_fence(self):
        raw = '```json\n{"key": "value"}\n```'
        result = json.loads(repair_json(raw))
        assert result == {"key": "value"}

    def test_single_quotes(self):
        raw = "{'command': 'ls'}"
        result = json.loads(repair_json(raw))
        assert result == {"command": "ls"}

    def test_combined_issues(self):
        raw = '{"a": True, "b": None,}'
        result = json.loads(repair_json(raw))
        assert result == {"a": True, "b": None}

    def test_unfixable_returns_original(self):
        raw = "this is not json at all {"
        assert repair_json(raw) == raw


class TestLoopDetection:
    """Test loop detection in send_with_tools via the threshold constant."""

    def test_threshold_is_reasonable(self):
        from marneo.engine.chat import _LOOP_DETECT_THRESHOLD
        assert _LOOP_DETECT_THRESHOLD >= 2
        assert _LOOP_DETECT_THRESHOLD <= 10
