# marneo/plugins/manifest.py
"""Plugin manifest dataclass and JSON parsing utilities."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Required fields that must be present in every manifest.json
_REQUIRED_FIELDS = frozenset({"id", "name", "description"})


@dataclass(frozen=True)
class PluginManifest:
    """Declarative description of a plugin, parsed from manifest.json.

    Each plugin directory contains a ``manifest.json`` that is read
    **without executing any code**.  The ``entry_point`` is only imported
    when the plugin is explicitly activated.
    """

    id: str                          # unique plugin ID, e.g. "my-search"
    name: str                        # display name
    description: str                 # what the plugin does
    version: str = "0.1.0"
    enabled_by_default: bool = False
    tools: list[str] = field(default_factory=list)      # tool names this plugin provides
    config_schema: dict[str, Any] = field(default_factory=dict)  # optional config schema
    hooks: list[str] = field(default_factory=list)       # lifecycle hooks
    entry_point: str = ""            # Python module path or file path for lazy loading

    # Resolved directory (not serialised, set during discovery)
    plugin_dir: Path | None = field(default=None, repr=False, compare=False)


def parse_manifest(path: Path) -> PluginManifest:
    """Parse a ``manifest.json`` file into a :class:`PluginManifest`.

    Raises :class:`ValueError` if the file is missing, unreadable, or
    does not contain the required fields.
    """
    if not path.is_file():
        raise ValueError(f"Manifest file not found: {path}")

    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Cannot read manifest: {path} ({exc})") from exc

    try:
        data: dict[str, Any] = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in manifest: {path} ({exc})") from exc

    if not isinstance(data, dict):
        raise ValueError(f"Manifest must be a JSON object: {path}")

    missing = _REQUIRED_FIELDS - data.keys()
    if missing:
        raise ValueError(
            f"Manifest {path} is missing required fields: {', '.join(sorted(missing))}"
        )

    # Validate types for critical fields
    _expect_str(data, "id", path)
    _expect_str(data, "name", path)
    _expect_str(data, "description", path)

    return PluginManifest(
        id=data["id"],
        name=data["name"],
        description=data["description"],
        version=str(data.get("version", "0.1.0")),
        enabled_by_default=bool(data.get("enabled_by_default", False)),
        tools=_as_str_list(data.get("tools", [])),
        config_schema=data.get("config_schema") if isinstance(data.get("config_schema"), dict) else {},
        hooks=_as_str_list(data.get("hooks", [])),
        entry_point=str(data.get("entry_point", "")),
        plugin_dir=path.parent,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _expect_str(data: dict[str, Any], key: str, path: Path) -> None:
    """Raise if *key* is present but not a string."""
    val = data.get(key)
    if val is not None and not isinstance(val, str):
        raise ValueError(f"Field '{key}' in {path} must be a string, got {type(val).__name__}")


def _as_str_list(value: Any) -> list[str]:
    """Coerce *value* to a list of strings, silently dropping non-strings."""
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str)]
