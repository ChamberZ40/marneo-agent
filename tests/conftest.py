# tests/conftest.py
"""Pytest configuration and shared fixtures.

Hermetic isolation: all tests run with credentials stripped, MARNEO_HOME
redirected to tmp_path, and deterministic environment (hermes pattern).
"""
import os
import pytest


_CREDENTIAL_SUBSTRINGS = ("_API_KEY", "_TOKEN", "_SECRET", "_PASSWORD", "_CREDENTIAL")


@pytest.fixture(autouse=True)
def hermetic_env(tmp_path, monkeypatch):
    """Ensure every test runs in a hermetic environment.

    - Strips credential environment variables (prevent accidental API calls)
    - Redirects MARNEO_HOME to a temp directory
    - Sets deterministic locale / timezone / hash seed
    """
    # ── Strip credentials ────────────────────────────────────────────────
    for key in list(os.environ):
        if any(s in key.upper() for s in _CREDENTIAL_SUBSTRINGS):
            monkeypatch.delenv(key, raising=False)

    # ── Redirect MARNEO_HOME ─────────────────────────────────────────────
    marneo_home = tmp_path / ".marneo"
    marneo_home.mkdir()
    monkeypatch.setenv("MARNEO_HOME", str(marneo_home))

    import marneo.core.paths as paths_module
    monkeypatch.setattr(paths_module, "get_marneo_dir", lambda: marneo_home)

    # ── Deterministic environment ────────────────────────────────────────
    monkeypatch.setenv("TZ", "UTC")
    monkeypatch.setenv("LANG", "C.UTF-8")
    monkeypatch.setenv("PYTHONHASHSEED", "0")

    yield
