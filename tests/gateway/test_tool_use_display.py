# tests/gateway/test_tool_use_display.py
"""Tests for _format_tool_trace — tool call display in streaming cards."""
from marneo.gateway.adapters.feishu import _format_tool_trace


def test_format_tool_trace_single():
    """One tool in progress shows spinner-style indicator."""
    trace = [{"name": "web_search", "done": False}]
    result = _format_tool_trace(trace)
    assert "web_search" in result
    assert "执行中" in result
    # Should use the wrench emoji for in-progress
    assert "\U0001f527" in result  # 🔧


def test_format_tool_trace_completed():
    """One tool completed shows check-mark indicator."""
    trace = [{"name": "read_file", "done": True}]
    result = _format_tool_trace(trace)
    assert "read_file" in result
    assert "完成" in result
    # Should use the check emoji for completed
    assert "\u2705" in result  # ✅
    # Should NOT show in-progress for completed tool
    assert "执行中" not in result


def test_format_tool_trace_multiple():
    """Multiple tools, mix of done and pending — renders all in order."""
    trace = [
        {"name": "web_search", "done": True},
        {"name": "read_file", "done": True},
        {"name": "bash", "done": False},
    ]
    result = _format_tool_trace(trace)
    # All tool names present
    assert "web_search" in result
    assert "read_file" in result
    assert "bash" in result
    # Completed tools marked done, pending not
    lines = result.strip().splitlines()
    # First line is the header; tools start from index 1+
    tool_lines = [l for l in lines if "web_search" in l or "read_file" in l or "bash" in l]
    assert len(tool_lines) == 3
    # Check that done tools have ✅ and pending has 🔧
    for line in tool_lines:
        if "bash" in line:
            assert "\U0001f527" in line  # 🔧 pending
            assert "执行中" in line
        else:
            assert "\u2705" in line  # ✅ completed
            assert "完成" in line


def test_format_tool_trace_empty():
    """Empty trace still returns the header (not a crash)."""
    result = _format_tool_trace([])
    # Should return something (at minimum the header line)
    assert isinstance(result, str)
    # The header always contains 工具调用中
    assert "工具调用" in result
    # No tool lines beyond the header
    lines = [l for l in result.strip().splitlines() if l.strip()]
    # Only the header line(s) — no tool entries
    tool_indicator_lines = [l for l in lines if "\u2705" in l or "\U0001f527" in l]
    assert len(tool_indicator_lines) == 0


def test_format_tool_trace_preserves_order():
    """Tool trace preserves insertion order so the user sees chronological calls."""
    trace = [
        {"name": "alpha", "done": False},
        {"name": "bravo", "done": False},
        {"name": "charlie", "done": False},
    ]
    result = _format_tool_trace(trace)
    idx_a = result.index("alpha")
    idx_b = result.index("bravo")
    idx_c = result.index("charlie")
    assert idx_a < idx_b < idx_c


def test_format_tool_trace_returns_string():
    """Return type is always a plain string (card content payload)."""
    trace = [{"name": "x", "done": True}]
    result = _format_tool_trace(trace)
    assert isinstance(result, str)
