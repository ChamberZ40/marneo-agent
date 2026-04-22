# marneo/core/paths.py
"""Marneo data directory layout. All data lives under ~/.marneo/"""
from __future__ import annotations
from pathlib import Path


def get_marneo_dir() -> Path:
    """Return ~/.marneo/, creating it if needed."""
    d = Path.home() / ".marneo"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_employees_dir() -> Path:
    d = get_marneo_dir() / "employees"
    d.mkdir(exist_ok=True)
    return d


def get_projects_dir() -> Path:
    d = get_marneo_dir() / "projects"
    d.mkdir(exist_ok=True)
    return d


def get_config_path() -> Path:
    return get_marneo_dir() / "config.yaml"
