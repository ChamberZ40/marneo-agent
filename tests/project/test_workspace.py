"""Tests for project workspace CRUD."""
import shutil
import pytest
from marneo.project.workspace import (
    create_project, load_project, list_projects, save_project,
    assign_employee, get_employee_projects, ProjectWorkspace
)


def test_create_project():
    p = create_project("test-proj", description="测试项目")
    assert p.name == "test-proj"
    assert p.description == "测试项目"
    assert p.created_at != ""


def test_load_project_returns_none_for_missing():
    assert load_project("nonexistent_abc") is None


def test_create_and_load_roundtrip():
    create_project("roundtrip-test", description="desc", goals=["goal1"])
    loaded = load_project("roundtrip-test")
    assert loaded is not None
    assert loaded.description == "desc"
    assert "goal1" in loaded.goals


def test_list_projects():
    create_project("list-proj-1")
    create_project("list-proj-2")
    names = list_projects()
    assert "list-proj-1" in names
    assert "list-proj-2" in names


def test_assign_employee_idempotent():
    create_project("assign-test")
    assign_employee("assign-test", "Alice")
    assign_employee("assign-test", "Alice")  # second call
    loaded = load_project("assign-test")
    assert loaded.assigned_employees.count("Alice") == 1


def test_get_employee_projects():
    create_project("emp-proj-a")
    assign_employee("emp-proj-a", "Bob")
    projects = get_employee_projects("Bob")
    assert any(p.name == "emp-proj-a" for p in projects)


def test_get_employee_projects_empty_for_unassigned():
    assert get_employee_projects("nobody_xyz") == []
