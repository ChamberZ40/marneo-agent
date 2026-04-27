# tests/plugins/test_manifest.py
"""Tests for marneo.plugins.manifest."""
import json
import pytest
from marneo.plugins.manifest import PluginManifest, parse_manifest


class TestParseManifest:
    def test_parse_full_manifest(self, tmp_path):
        data = {
            "id": "weather-tool",
            "name": "Weather Tool",
            "description": "Provides weather forecasts",
            "version": "1.0.0",
            "tools": ["get_weather"],
            "entry_point": "weather_tool.main",
        }
        p = tmp_path / "manifest.json"
        p.write_text(json.dumps(data))
        m = parse_manifest(p)
        assert m.id == "weather-tool"
        assert m.name == "Weather Tool"
        assert m.version == "1.0.0"
        assert m.tools == ["get_weather"]
        assert m.entry_point == "weather_tool.main"

    def test_parse_preserves_entry_point(self, tmp_path):
        data = {"id": "ep", "name": "EP", "description": "d", "entry_point": "some.module"}
        p = tmp_path / "manifest.json"
        p.write_text(json.dumps(data))
        assert parse_manifest(p).entry_point == "some.module"

    def test_parse_missing_required_fields(self, tmp_path):
        p = tmp_path / "manifest.json"
        p.write_text(json.dumps({"id": "incomplete"}))
        with pytest.raises(ValueError, match="missing required"):
            parse_manifest(p)

    def test_parse_invalid_json(self, tmp_path):
        p = tmp_path / "manifest.json"
        p.write_text("{not json")
        with pytest.raises(ValueError):
            parse_manifest(p)

    def test_parse_nonexistent(self, tmp_path):
        with pytest.raises(ValueError, match="not found"):
            parse_manifest(tmp_path / "nope.json")


class TestManifestDefaults:
    def test_defaults(self, tmp_path):
        data = {"id": "minimal", "name": "Minimal", "description": "d"}
        p = tmp_path / "manifest.json"
        p.write_text(json.dumps(data))
        m = parse_manifest(p)
        assert m.version == "0.1.0"
        assert m.enabled_by_default is False
        assert m.tools == []
        assert m.hooks == []
        assert m.entry_point == ""
