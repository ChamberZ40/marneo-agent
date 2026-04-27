# tests/gateway/test_platform_hints.py
"""Tests for platform-specific hint system."""
from marneo.gateway.platform_hints import get_platform_hint


class TestPlatformHints:
    def test_feishu_hint(self):
        hint = get_platform_hint("feishu")
        assert "Feishu" in hint
        assert "Markdown" in hint

    def test_feishu_with_employee(self):
        hint = get_platform_hint("feishu:laoqi")
        assert "Feishu" in hint

    def test_telegram_hint(self):
        hint = get_platform_hint("telegram")
        assert "Telegram" in hint

    def test_unknown_platform(self):
        hint = get_platform_hint("unknown_platform")
        assert "Unknown" in hint

    def test_empty_platform(self):
        hint = get_platform_hint("")
        assert hint  # should return default hint
