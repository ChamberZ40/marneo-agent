# tests/memory/test_integration.py
"""Integration tests for memory system — end-to-end verification."""
import pytest
from pathlib import Path

from marneo.memory.session_memory import SessionMemory, ContextBudget
from marneo.memory.episodes import EpisodeStore, Episode
from marneo.memory.retriever import HybridRetriever
from marneo.memory.core import CoreMemory
from marneo.memory.skill_index import index_skills_into_store


# ---------------------------------------------------------------------------
# D1: SessionMemory prompt building and retrieval
# ---------------------------------------------------------------------------

class TestSessionMemoryPromptBuilding:
    """Verify SessionMemory builds system prompt with SOUL, core, and capability directive."""

    def test_session_memory_builds_prompt_with_soul(self, tmp_path):
        """Create SessionMemory for 'laoqi', verify prompt contains SOUL.md content."""
        soul_text = "我是老七，Marneo 的数字员工。我专注于飞书运营和数据处理。"
        core_path = tmp_path / "core.md"
        core = CoreMemory(core_path)

        sm = SessionMemory.__new__(SessionMemory)
        sm._employee_name = "laoqi"
        sm._soul = soul_text
        sm._budget = ContextBudget(system_prompt_max=4000, core_memory_max=500)
        sm._core = core
        sm._retriever = None
        sm._store = None

        prompt = sm.build_system_prompt("", skip_retrieval=True)

        assert "老七" in prompt
        assert "飞书运营" in prompt
        assert "数据处理" in prompt

    def test_session_memory_retrieves_for_turn(self, tmp_path):
        """Add episodes to store, verify retrieve_for_turn returns relevant ones."""
        store = EpisodeStore(tmp_path / "episodes.db")
        store.add(Episode(id="ep_int1", content="pandas 处理 UTF-8 编码问题的解决方案", type="discovery"))
        store.add(Episode(id="ep_int2", content="飞书 API 调用频率限制是每秒 5 次", type="preference"))
        store.add(Episode(id="ep_int3", content="Docker 容器部署需要设置环境变量", type="decision"))

        retriever = HybridRetriever(store, tmp_path / "vectors.npy")
        retriever.rebuild_index()

        sm = SessionMemory.__new__(SessionMemory)
        sm._employee_name = "laoqi"
        sm._soul = ""
        sm._budget = ContextBudget(episodic_inject_max=1500)
        sm._core = CoreMemory(tmp_path / "core.md")
        sm._retriever = retriever
        sm._store = store

        result = sm.retrieve_for_turn("pandas 编码")

        assert result != ""
        assert "相关经验" in result
        assert "pandas" in result

    def test_session_memory_injects_capability_directive(self, tmp_path):
        """Verify 'work-focused digital employee' is in prompt."""
        sm = SessionMemory.__new__(SessionMemory)
        sm._employee_name = "test"
        sm._soul = ""
        sm._budget = ContextBudget()
        sm._core = CoreMemory(tmp_path / "core.md")
        sm._retriever = None
        sm._store = None

        prompt = sm.build_system_prompt("", skip_retrieval=True)

        assert "work-focused digital employee" in prompt
        assert "action-oriented" in prompt


# ---------------------------------------------------------------------------
# D2: Episode extraction integration
# ---------------------------------------------------------------------------

class TestEpisodeExtraction:
    """Verify episode extraction from conversation turns end-to-end."""

    def test_episode_extraction_from_conversation(self, tmp_path):
        """Call add_episode_from_turn with decision-bearing reply, verify episode saved."""
        store = EpisodeStore(tmp_path / "episodes.db")
        retriever = HybridRetriever(store, tmp_path / "vectors.npy")

        sm = SessionMemory.__new__(SessionMemory)
        sm._employee_name = "laoqi"
        sm._soul = ""
        sm._budget = ContextBudget()
        sm._core = CoreMemory(tmp_path / "core.md")
        sm._retriever = retriever
        sm._store = store

        user_msg = "用哪个库处理 PDF？"
        assistant_reply = "我们决定用 pypdf 因为 API 更简单。pdfminer 太复杂了。"

        sm.add_episode_from_turn(user_msg, assistant_reply)

        episodes = store.get_all()
        assert len(episodes) == 1
        assert "pypdf" in episodes[0].content
        assert episodes[0].type == "decision"

    def test_episode_extraction_skips_short_reply(self, tmp_path):
        """Call with short reply, verify nothing saved."""
        store = EpisodeStore(tmp_path / "episodes.db")
        retriever = HybridRetriever(store, tmp_path / "vectors.npy")

        sm = SessionMemory.__new__(SessionMemory)
        sm._employee_name = "laoqi"
        sm._soul = ""
        sm._budget = ContextBudget()
        sm._core = CoreMemory(tmp_path / "core.md")
        sm._retriever = retriever
        sm._store = store

        sm.add_episode_from_turn("你好", "好的！")

        episodes = store.get_all()
        assert len(episodes) == 0


# ---------------------------------------------------------------------------
# D3: Skill indexing and retrieval
# ---------------------------------------------------------------------------

class TestSkillIndexingAndRetrieval:
    """Verify skill files are indexed and retrievable via HybridRetriever."""

    def test_skill_indexing_and_retrieval(self, tmp_path):
        """Create a tmp skills dir with a .md skill file, index, then retrieve."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "feishu-bitable.md").write_text(
            "---\nname: 飞书多维表格操作\n"
            "description: 创建、读取、写入飞书多维表格\n"
            "enabled: true\n---\n\n详细内容",
            encoding="utf-8",
        )

        store = EpisodeStore(tmp_path / "episodes.db")

        # Add a few unrelated episodes so BM25 IDF produces positive scores
        store.add(Episode(id="ep_filler1", content="Docker 容器部署配置", type="decision"))
        store.add(Episode(id="ep_filler2", content="Python pandas 数据处理", type="discovery"))

        count = index_skills_into_store(skills_dir, store)
        assert count == 1

        # Verify the skill episode is in the store with correct metadata
        episodes = store.list_recent(source="skill")
        assert len(episodes) == 1
        skill_ep = episodes[0]
        assert skill_ep.source == "skill"
        assert skill_ep.skill_id == "feishu-bitable"
        assert "飞书多维表格" in skill_ep.content

        # Verify retriever can find it via BM25 (needs multiple docs for positive IDF)
        retriever = HybridRetriever(store, tmp_path / "vectors.npy")
        retriever.rebuild_index()
        results = retriever.retrieve_bm25("飞书", n=3)
        assert len(results) > 0
        assert any(r.skill_id == "feishu-bitable" for r in results)


# ---------------------------------------------------------------------------
# D4: Core memory in system prompt and persistence
# ---------------------------------------------------------------------------

class TestCoreMemoryIntegration:
    """Verify core memory entries appear in system prompt and persist."""

    def test_core_memory_in_system_prompt(self, tmp_path):
        """Create CoreMemory, add entry, build SessionMemory prompt, verify entry is in prompt."""
        core_path = tmp_path / "core.md"
        core = CoreMemory(core_path)
        core.add("绝对不能删除生产数据库", source="manual")

        sm = SessionMemory.__new__(SessionMemory)
        sm._employee_name = "laoqi"
        sm._soul = "我是老七。"
        sm._budget = ContextBudget(system_prompt_max=4000, core_memory_max=1000)
        sm._core = core
        sm._retriever = None
        sm._store = None

        prompt = sm.build_system_prompt("", skip_retrieval=True)

        assert "绝对不能删除生产数据库" in prompt
        assert "核心记忆" in prompt

    def test_core_memory_persistence(self, tmp_path):
        """Add entry, create new CoreMemory instance, verify entry persists."""
        core_path = tmp_path / "core.md"
        cm1 = CoreMemory(core_path)
        cm1.add("API key 不能硬编码", source="manual")
        cm1.add("所有数据库查询必须参数化", source="llm")

        # Create a completely new instance pointing to same file
        cm2 = CoreMemory(core_path)
        entries = cm2.list_entries()

        assert len(entries) == 2
        contents = [e["content"] for e in entries]
        assert "API key 不能硬编码" in contents
        assert "所有数据库查询必须参数化" in contents
