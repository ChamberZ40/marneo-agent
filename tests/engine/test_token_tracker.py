# tests/engine/test_token_tracker.py
"""Tests for marneo.engine.token_tracker."""
from marneo.engine.token_tracker import TokenTracker, TokenUsage


class TestTokenTracker:
    def test_record_basic(self):
        t = TokenTracker()
        t.record("gpt-4o", input_tokens=100, output_tokens=50)
        assert t.total.input_tokens == 100
        assert t.total.output_tokens == 50
        assert t.total.total_calls == 1

    def test_record_multiple_models(self):
        t = TokenTracker()
        t.record("gpt-4o", input_tokens=100, output_tokens=50)
        t.record("claude-3", input_tokens=200, output_tokens=80)
        assert t.total.input_tokens == 300
        assert t.total.output_tokens == 130
        assert t.total.total_calls == 2

    def test_record_accumulates(self):
        t = TokenTracker()
        t.record("gpt-4o", input_tokens=100, output_tokens=50)
        t.record("gpt-4o", input_tokens=100, output_tokens=50)
        assert t.total.input_tokens == 200
        assert t.total.total_calls == 2
        assert t._by_model["gpt-4o"].total_calls == 2

    def test_summary(self):
        t = TokenTracker()
        t.record("gpt-4o", input_tokens=100, output_tokens=50, cache_read=20)
        s = t.summary()
        assert s["total_calls"] == 1
        assert s["input_tokens"] == 100
        assert s["cache_read_tokens"] == 20
        assert "gpt-4o" in s["by_model"]

    def test_empty_tracker(self):
        t = TokenTracker()
        assert t.total.total_calls == 0
        s = t.summary()
        assert s["total_calls"] == 0
