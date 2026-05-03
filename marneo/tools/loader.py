# marneo/tools/loader.py
"""Import all tool modules to trigger self-registration in the registry."""
from __future__ import annotations

import importlib
import logging
import sys

log = logging.getLogger(__name__)


def _load_tool_module(module_name: str) -> None:
    """Import or reload a self-registering tool module.

    Tests may clear the global registry after a module was already imported;
    reload makes load_all_tools() idempotent and restores registrations.
    """
    if module_name in sys.modules:
        importlib.reload(sys.modules[module_name])
    else:
        importlib.import_module(module_name)


def load_all_tools() -> None:
    """Import every tool module and discover plugins. Call once at startup."""
    from marneo.core.config import is_local_only_mode

    local_only = is_local_only_mode()

    _load_tool_module("marneo.tools.core.files")
    _load_tool_module("marneo.tools.core.bash")

    if not local_only:
        _load_tool_module("marneo.tools.core.web")
        _load_tool_module("marneo.tools.core.lark_cli")
        _load_tool_module("marneo.tools.core.feishu_tools")
        _load_tool_module("marneo.tools.core.ask_user")

        # --- Manifest-first plugin discovery ---
        _load_plugins()
    else:
        log.info("[Tools] local-only/private mode enabled; external network tools are disabled")


def _load_plugins() -> None:
    """Discover and auto-activate plugins with ``enabled_by_default=True``."""
    from marneo.plugins.registry import PluginRegistry
    from marneo.tools.registry import registry

    plugin_registry = PluginRegistry(registry)

    try:
        manifests = plugin_registry.discover()
    except Exception as exc:
        log.error("[Plugins] Discovery failed: %s", exc, exc_info=True)
        return

    for manifest in manifests:
        if manifest.enabled_by_default:
            try:
                plugin_registry.activate(manifest.id)
            except Exception as exc:
                log.error(
                    "[Plugins] Auto-activation failed for '%s': %s",
                    manifest.id,
                    exc,
                    exc_info=True,
                )
