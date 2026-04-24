# tests/memory/test_skill_index.py
import pytest
from pathlib import Path
from marneo.memory.skill_index import index_skills_into_store, get_skill_content
from marneo.memory.episodes import EpisodeStore


def test_index_skills_from_dir(tmp_path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "pandas-encoding.md").write_text(
        "---\nname: pandas 编码处理\ndescription: 处理飞书导出 UTF-8 编码问题\nenabled: true\n---\n\n解决方案内容",
        encoding="utf-8",
    )
    (skills_dir / "disabled-skill.md").write_text(
        "---\nname: 禁用技能\ndescription: 不应该被索引\nenabled: false\n---\n内容",
        encoding="utf-8",
    )
    store = EpisodeStore(tmp_path / "episodes.db")
    count = index_skills_into_store(skills_dir, store)
    assert count == 1
    episodes = store.list_recent(source="skill")
    assert len(episodes) == 1
    assert "pandas 编码处理" in episodes[0].content
    assert episodes[0].skill_id == "pandas-encoding"


def test_index_skills_idempotent(tmp_path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "s1.md").write_text(
        "---\nname: skill one\ndescription: does X\nenabled: true\n---\ncontent",
        encoding="utf-8",
    )
    store = EpisodeStore(tmp_path / "episodes.db")
    index_skills_into_store(skills_dir, store)
    index_skills_into_store(skills_dir, store)
    episodes = store.list_recent(source="skill")
    assert len(episodes) == 1


def test_get_skill_content_not_found():
    content = get_skill_content("nonexistent-xyz-skill-abc")
    assert "not found" in content.lower()
