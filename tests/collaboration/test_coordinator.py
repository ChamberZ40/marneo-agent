# tests/collaboration/test_coordinator.py
"""Unit tests for team coordinator logic."""
import asyncio
import pytest
from marneo.collaboration.coordinator import should_use_team
from marneo.collaboration.team import TeamConfig, TeamMember


def test_should_use_team_complex_task():
    result = asyncio.run(should_use_team("帮我综合分析数据并制定详细的营销计划", 2))
    assert result is True


def test_should_use_team_simple_task():
    result = asyncio.run(should_use_team("hi", 2))
    assert result is False


def test_should_use_team_single_member_always_false():
    # team_size < 2 → never use team
    result = asyncio.run(should_use_team("帮我综合分析并制定详细计划", 1))
    assert result is False


def test_should_use_team_long_message():
    long_msg = "x" * 150
    result = asyncio.run(should_use_team(long_msg, 2))
    assert result is True


def test_team_config_specialists_excludes_coordinator():
    config = TeamConfig(
        project_name="test",
        coordinator="GAI",
        members=[
            TeamMember("GAI", "协调者"),
            TeamMember("ARIA", "专员"),
            TeamMember("BOB", "专员"),
        ],
    )
    specs = config.specialists
    assert len(specs) == 2
    assert all(m.employee != "GAI" for m in specs)


def test_team_config_is_configured_true():
    config = TeamConfig(
        project_name="test",
        coordinator="GAI",
        members=[TeamMember("GAI", "协调者"), TeamMember("ARIA", "专员")],
    )
    assert config.is_configured()


def test_team_config_not_configured_single_member():
    config = TeamConfig(
        project_name="test",
        coordinator="GAI",
        members=[TeamMember("GAI", "协调者")],
    )
    assert not config.is_configured()


def test_team_config_member_names():
    config = TeamConfig(
        project_name="test",
        coordinator="GAI",
        members=[TeamMember("GAI", "协调者"), TeamMember("ARIA", "专员")],
    )
    assert config.member_names == ["GAI", "ARIA"]
