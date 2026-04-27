# marneo/plugins/registry.py
"""Plugin registry — discovers, loads, and manages plugins via manifest files.

Follows the **manifest-first** pattern ported from openclaw:

1. **Discover** — scan plugin directories for ``manifest.json`` files.
   No Python code is executed at this stage.
2. **Activate** — lazily import the plugin's ``entry_point`` and call its
   ``register(tool_registry)`` function so tools become available.
3. **Deactivate** — unregister the tools that a plugin provided.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from marneo.plugins.loader import load_plugin_module
from marneo.plugins.manifest import PluginManifest, parse_manifest
from marneo.tools.registry import ToolRegistry

log = logging.getLogger(__name__)

# Default directories to scan for plugins (first match wins for a given ID).
_DEFAULT_PLUGIN_DIRS: list[Path] = [
    Path.home() / ".marneo" / "plugins",
]


class PluginRegistry:
    """Discovers, loads, and manages plugins via manifest files.

    Parameters
    ----------
    tool_registry:
        The application-wide :class:`ToolRegistry` that plugins register
        their tools into.
    """

    def __init__(self, tool_registry: ToolRegistry) -> None:
        self._tool_registry = tool_registry
        self._lock = threading.RLock()

        # plugin_id -> manifest (populated by discover())
        self._manifests: dict[str, PluginManifest] = {}

        # plugin_id -> set of tool names actually registered
        self._active: dict[str, set[str]] = {}

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def discover(self, plugin_dirs: list[Path] | None = None) -> list[PluginManifest]:
        """Scan directories for ``manifest.json`` files. **No code execution.**

        Parameters
        ----------
        plugin_dirs:
            Directories to scan.  Each immediate sub-directory that contains
            a ``manifest.json`` is considered a plugin.  Defaults to
            ``~/.marneo/plugins/``.

        Returns
        -------
        list[PluginManifest]
            All successfully parsed manifests.
        """
        dirs = plugin_dirs if plugin_dirs is not None else _DEFAULT_PLUGIN_DIRS
        discovered: list[PluginManifest] = []

        for base_dir in dirs:
            resolved = base_dir.expanduser().resolve()
            if not resolved.is_dir():
                log.debug("[Plugins] Directory does not exist, skipping: %s", resolved)
                continue

            for child in sorted(resolved.iterdir()):
                manifest_path = child / "manifest.json"
                if not child.is_dir() or not manifest_path.is_file():
                    continue

                try:
                    manifest = parse_manifest(manifest_path)
                except ValueError as exc:
                    log.warning("[Plugins] Skipping invalid manifest %s: %s", manifest_path, exc)
                    continue

                with self._lock:
                    if manifest.id in self._manifests:
                        log.debug(
                            "[Plugins] Duplicate plugin id '%s' in %s — keeping first",
                            manifest.id,
                            manifest_path,
                        )
                        continue
                    self._manifests[manifest.id] = manifest

                discovered.append(manifest)
                log.info(
                    "[Plugins] Discovered plugin '%s' v%s (%s)",
                    manifest.id,
                    manifest.version,
                    manifest.name,
                )

        return discovered

    # ------------------------------------------------------------------
    # Activation / Deactivation
    # ------------------------------------------------------------------

    def activate(self, plugin_id: str, config: dict[str, Any] | None = None) -> bool:
        """Lazy-load a plugin's ``entry_point`` and register its tools.

        Parameters
        ----------
        plugin_id:
            The ``id`` field from the plugin's manifest.
        config:
            Optional configuration dict passed to the plugin's ``register``
            function (if it accepts a second argument).

        Returns
        -------
        bool
            ``True`` if the plugin was successfully activated (or was
            already active).  ``False`` on any error.
        """
        with self._lock:
            if plugin_id in self._active:
                log.debug("[Plugins] Plugin '%s' is already active", plugin_id)
                return True

            manifest = self._manifests.get(plugin_id)
            if manifest is None:
                log.warning("[Plugins] Cannot activate unknown plugin '%s'", plugin_id)
                return False

        entry_point = manifest.entry_point
        if not entry_point:
            # Fallback: try __init__.py in the plugin directory.
            if manifest.plugin_dir is not None:
                init_file = manifest.plugin_dir / "__init__.py"
                if init_file.is_file():
                    entry_point = str(init_file)

        if not entry_point:
            log.warning(
                "[Plugins] Plugin '%s' has no entry_point and no __init__.py — nothing to load",
                plugin_id,
            )
            return False

        # --- Lazy import ---
        try:
            module = load_plugin_module(entry_point)
        except (ImportError, AttributeError) as exc:
            log.error("[Plugins] Failed to load plugin '%s': %s", plugin_id, exc)
            return False
        except Exception as exc:
            log.error(
                "[Plugins] Unexpected error loading plugin '%s': %s",
                plugin_id,
                exc,
                exc_info=True,
            )
            return False

        # --- Snapshot tools before registration so we can diff ---
        tools_before = set(self._tool_registry._tools.keys())

        try:
            register_fn = module.register
            # Support both register(registry) and register(registry, config)
            import inspect
            sig = inspect.signature(register_fn)
            if len(sig.parameters) >= 2:
                register_fn(self._tool_registry, config or {})
            else:
                register_fn(self._tool_registry)
        except Exception as exc:
            log.error(
                "[Plugins] register() failed for plugin '%s': %s",
                plugin_id,
                exc,
                exc_info=True,
            )
            return False

        tools_after = set(self._tool_registry._tools.keys())
        registered_tools = tools_after - tools_before

        with self._lock:
            self._active[plugin_id] = registered_tools

        log.info(
            "[Plugins] Activated plugin '%s' — registered tools: %s",
            plugin_id,
            sorted(registered_tools) or "(none)",
        )
        return True

    def deactivate(self, plugin_id: str) -> bool:
        """Unregister a plugin's tools and mark it as inactive.

        Returns
        -------
        bool
            ``True`` if the plugin was deactivated.  ``False`` if it was
            not active or the ID is unknown.
        """
        with self._lock:
            tool_names = self._active.pop(plugin_id, None)

        if tool_names is None:
            log.debug("[Plugins] Plugin '%s' is not active — nothing to deactivate", plugin_id)
            return False

        with self._tool_registry._lock:
            for name in tool_names:
                self._tool_registry._tools.pop(name, None)

        log.info(
            "[Plugins] Deactivated plugin '%s' — unregistered tools: %s",
            plugin_id,
            sorted(tool_names),
        )
        return True

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def list_plugins(self) -> list[PluginManifest]:
        """Return all discovered manifests (active or not)."""
        with self._lock:
            return list(self._manifests.values())

    def get_active(self) -> list[str]:
        """Return IDs of currently active plugins."""
        with self._lock:
            return list(self._active.keys())

    def get_manifest(self, plugin_id: str) -> PluginManifest | None:
        """Return the manifest for a specific plugin, or ``None``."""
        with self._lock:
            return self._manifests.get(plugin_id)

    def is_active(self, plugin_id: str) -> bool:
        """Check whether a plugin is currently active."""
        with self._lock:
            return plugin_id in self._active
