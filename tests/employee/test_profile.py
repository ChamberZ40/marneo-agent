"""Tests for employee profile CRUD."""
import pytest
from marneo.employee.profile import (
    create_employee, load_profile, save_profile, list_employees,
    increment_conversation, LEVEL_INTERN, LEVEL_ORDER, EmployeeProfile
)
import shutil


def test_create_employee_defaults():
    p = create_employee("TestEmp")
    assert p.name == "TestEmp"
    assert p.level == LEVEL_INTERN
    assert p.total_conversations == 0
    assert p.hired_at != ""


def test_load_profile_returns_none_for_missing():
    assert load_profile("nonexistent_xyz") is None


def test_save_and_load_roundtrip():
    p = create_employee("SaveTest", personality="务实", domains="编程", style="简洁")
    loaded = load_profile("SaveTest")
    assert loaded is not None
    assert loaded.personality == "务实"
    assert loaded.domains == "编程"


def test_list_employees_includes_created():
    create_employee("ListTest1")
    create_employee("ListTest2")
    names = list_employees()
    assert "ListTest1" in names
    assert "ListTest2" in names


def test_increment_conversation():
    create_employee("IncrTest")
    updated = increment_conversation("IncrTest")
    assert updated is not None
    assert updated.total_conversations == 1
    assert updated.level_conversations == 1
    updated2 = increment_conversation("IncrTest")
    assert updated2.total_conversations == 2


def test_increment_conversation_returns_none_for_missing():
    result = increment_conversation("definitely_missing_xyz")
    assert result is None


def test_level_order():
    assert LEVEL_ORDER[0] == LEVEL_INTERN
    assert len(LEVEL_ORDER) == 4
