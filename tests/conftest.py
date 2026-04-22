# tests/conftest.py
"""Pytest configuration and shared fixtures."""
import pytest
import shutil
from pathlib import Path


@pytest.fixture(autouse=True)
def clean_test_marneo_dir(tmp_path, monkeypatch):
    """Redirect ~/.marneo to a temp dir for all tests."""
    # Monkeypatch get_marneo_dir to use tmp_path
    import marneo.core.paths as paths_module
    monkeypatch.setattr(paths_module, 'get_marneo_dir', lambda: tmp_path / '.marneo')
    (tmp_path / '.marneo').mkdir()
    yield
    # cleanup handled by pytest tmp_path
