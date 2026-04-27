# tests/plugins/test_plugin_registry.py
"""Tests for PluginRegistry — discover / activate / deactivate cycle."""
import json
from pathlib import Path

import pytest
from marneo.plugins.registry import PluginRegistry
from marneo.plugins.manifest import parse_manifest
from marneo.tools.registry import ToolRegistry


def _write_manifest(plugin_dir: Path, data: dict) -> Path:
    plugin_dir.mkdir(parents=True, exist_ok=True)
    p = plugin_dir / "manifest.json"
    p.write_text(json.dumps(data, indent=2))
    return p


def _sample(pid: str, enabled: bool = False) -> dict:
    return {
        "id": pid,
        "name": pid,
        "description": f"Test plugin {pid}",
        "enabled_by_default": enabled,
        "tools": [f"{pid}_tool"],
        "entry_point": "",
    }


class TestDiscoverFindsManifests:
    def test_discover_finds_manifests(self, tmp_path):
        _write_manifest(tmp_path / "plugin-a", _sample("plugin-a"))
        _write_manifest(tmp_path / "plugin-b", _sample("plugin-b"))

        reg = PluginRegistry(ToolRegistry())
        reg.discover([tmp_path])

        names = [m.id for m in reg.list_plugins()]
        assert "plugin-a" in names
        assert "plugin-b" in names


class TestDiscoverIgnoresInvalid:
    def test_discover_ignores_invalid(self, tmp_path):
        _write_manifest(tmp_path / "valid", _sample("valid"))
        bad_dir = tmp_path / "bad"
        bad_dir.mkdir()
        (bad_dir / "manifest.json").write_text("{bad json!")

        reg = PluginRegistry(ToolRegistry())
        reg.discover([tmp_path])

        names = [m.id for m in reg.list_plugins()]
        assert "valid" in names
        assert len(names) == 1


class TestListPlugins:
    def test_list_plugins(self, tmp_path):
        for n in ("alpha", "beta", "gamma"):
            _write_manifest(tmp_path / n, _sample(n))

        reg = PluginRegistry(ToolRegistry())
        reg.discover([tmp_path])
        names = {m.id for m in reg.list_plugins()}
        assert {"alpha", "beta", "gamma"} <= names


class TestEnabledByDefault:
    def test_enabled_by_default(self, tmp_path):
        _write_manifest(tmp_path / "auto-on", _sample("auto-on", enabled=True))
        _write_manifest(tmp_path / "auto-off", _sample("auto-off", enabled=False))

        reg = PluginRegistry(ToolRegistry())
        reg.discover([tmp_path])

        manifests = {m.id: m for m in reg.list_plugins()}
        assert manifests["auto-on"].enabled_by_default is True
        assert manifests["auto-off"].enabled_by_default is False
