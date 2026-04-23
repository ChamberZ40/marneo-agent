# tests/tools/test_bash.py
import json
import pytest
from marneo.tools.core.bash import bash


def test_bash_runs_simple_command():
    result = json.loads(bash({"command": "echo hello"}))
    assert result.get("stdout", "").strip() == "hello"
    assert result.get("exit_code") == 0


def test_bash_captures_stderr():
    result = json.loads(bash({"command": "echo error >&2; exit 1"}))
    assert result.get("exit_code") == 1
    assert "error" in result.get("stderr", "")


def test_bash_timeout():
    result = json.loads(bash({"command": "sleep 10", "timeout": 1}))
    assert "error" in result or result.get("exit_code") != 0


def test_bash_blocks_dangerous_commands():
    for cmd in ["rm -rf /", ":(){ :|:& };:", "mkfs.ext4 /dev/sda"]:
        result = json.loads(bash({"command": cmd}))
        assert "error" in result, f"Should have blocked: {cmd}"


def test_bash_returns_combined_output():
    result = json.loads(bash({"command": "echo out; echo err >&2"}))
    assert "out" in result.get("stdout", "")
    assert "err" in result.get("stderr", "")
