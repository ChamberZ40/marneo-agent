# marneo/plugins/loader.py
"""Lazy-load a plugin module by its entry_point string.

Supports two forms:

* **Dotted module path** — ``"marneo.plugins.contrib.my_search"``
  imported via :func:`importlib.import_module`.
* **File path** — ``"~/.marneo/plugins/my-search/__init__.py"``
  loaded via :func:`importlib.util.spec_from_file_location`.

Every plugin module **must** expose a ``register(registry)`` callable.
"""
from __future__ import annotations

import importlib
import importlib.util
import logging
import sys
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def load_plugin_module(entry_point: str) -> Any:
    """Import and return a plugin module.

    Parameters
    ----------
    entry_point:
        Either a dotted Python module path (``"marneo.plugins.contrib.foo"``)
        or an absolute/~ file path ending in ``.py``.

    Returns
    -------
    module
        The imported module object.

    Raises
    ------
    ImportError
        If the module cannot be located or imported.
    AttributeError
        If the module does not expose a ``register`` callable.
    """
    module = _import_entry_point(entry_point)

    register_fn = getattr(module, "register", None)
    if register_fn is None or not callable(register_fn):
        raise AttributeError(
            f"Plugin module '{entry_point}' does not expose a callable 'register' function"
        )

    return module


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _import_entry_point(entry_point: str) -> Any:
    """Resolve *entry_point* to a Python module."""
    resolved = Path(entry_point).expanduser()

    # Heuristic: if it looks like a file path, load from file.
    if resolved.suffix == ".py" or "/" in entry_point or "\\" in entry_point:
        return _import_from_file(resolved, entry_point)

    return _import_from_dotted(entry_point)


def _import_from_dotted(dotted_path: str) -> Any:
    """Import a module via its dotted Python path."""
    try:
        return importlib.import_module(dotted_path)
    except ModuleNotFoundError as exc:
        raise ImportError(
            f"Cannot import plugin module '{dotted_path}': {exc}"
        ) from exc


def _import_from_file(file_path: Path, original: str) -> Any:
    """Import a module from an absolute file path."""
    if not file_path.is_file():
        raise ImportError(f"Plugin file not found: {file_path} (entry_point={original!r})")

    # Derive a stable module name from the parent directory name.
    module_name = f"marneo_plugin_{file_path.parent.name.replace('-', '_')}"

    # Avoid re-importing if already loaded (e.g. repeated activate/deactivate).
    if module_name in sys.modules:
        return sys.modules[module_name]

    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot create module spec for {file_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module

    try:
        spec.loader.exec_module(module)  # type: ignore[union-attr]
    except Exception:
        # Clean up on failure so a retry can re-attempt.
        sys.modules.pop(module_name, None)
        raise

    return module
