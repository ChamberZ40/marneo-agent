"""Tests for employee growth system."""
from marneo.employee.growth import (
    should_level_up, next_level, days_at_level, build_level_directive,
    LEVELUP_THRESHOLDS
)
from marneo.employee.profile import create_employee, LEVEL_INTERN, LEVEL_ORDER


def test_should_level_up_false_for_new_employee():
    p = create_employee("GrowthTest")
    assert not should_level_up(p)


def test_next_level_chain():
    assert next_level("实习生") == "初级员工"
    assert next_level("初级员工") == "中级员工"
    assert next_level("中级员工") == "高级员工"
    assert next_level("高级员工") is None


def test_next_level_unknown():
    assert next_level("unknown_level") is None


def test_days_at_level_zero_for_new():
    p = create_employee("DaysTest")
    days = days_at_level(p)
    assert days == 0


def test_build_level_directive_not_empty():
    p = create_employee("DirectiveTest")
    directive = build_level_directive(p)
    assert len(directive) > 0
    assert "实习生" in directive


def test_levelup_thresholds_structure():
    for level in ["实习生", "初级员工", "中级员工", "高级员工"]:
        assert level in LEVELUP_THRESHOLDS
        days, convs, skills = LEVELUP_THRESHOLDS[level]
        assert isinstance(days, int) and isinstance(convs, int) and isinstance(skills, int)
