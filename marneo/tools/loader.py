# marneo/tools/loader.py
"""Import all tool modules to trigger self-registration in the registry."""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def load_all_tools() -> None:
    """Import every tool module and discover plugins. Call once at startup."""
    from marneo.tools.core import files        # noqa: F401
    from marneo.tools.core import bash         # noqa: F401
    from marneo.tools.core import web          # noqa: F401
    from marneo.tools.core import lark_cli     # noqa: F401
    from marneo.tools.core import feishu_tools  # noqa: F401
    from marneo.tools.core import ask_user     # noqa: F401

    # --- Manifest-first plugin discovery ---
    _load_plugins()


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
