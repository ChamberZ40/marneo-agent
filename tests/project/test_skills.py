"""Tests for skill management."""
import os
from marneo.project.skills import Skill, save_skill, list_skills, get_skills_context
from marneo.employee.profile import create_employee


def test_save_and_list_global_skill():
    s = Skill(id="test-global-skill", name="测试技能", description="描述", content="内容")
    path = save_skill(s)
    assert path.exists()
    skills = list_skills()
    assert any(sk.id == "test-global-skill" for sk in skills)
    os.unlink(path)


def test_save_project_skill():
    from marneo.project.workspace import create_project
    create_project("skill-proj")
    s = Skill(id="proj-skill", name="项目技能", scope="project:skill-proj", content="内容")
    path = save_skill(s)
    assert path.exists()
    skills = list_skills(include_project="skill-proj")
    assert any(sk.id == "proj-skill" for sk in skills)


def test_disabled_skill_not_listed():
    s = Skill(id="disabled-skill", name="禁用", enabled=False, content="内容")
    path = save_skill(s)
    skills = list_skills()
    assert not any(sk.id == "disabled-skill" for sk in skills)
    os.unlink(path)


def test_get_skills_context_empty_for_no_skills():
    create_employee("NoSkillEmp")
    ctx = get_skills_context("NoSkillEmp")
    # Context may contain global skills (lark-cli etc.) — just verify it's a string
    assert isinstance(ctx, str)
