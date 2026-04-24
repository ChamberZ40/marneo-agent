# tests/memory/test_session_memory.py
import pytest
from marneo.memory.session_memory import SessionMemory, ContextBudget


def test_budget_defaults():
    b = ContextBudget()
    assert b.system_prompt_max == 4000
    assert b.working_memory_turns == 20
    assert b.episodic_inject_max == 1500


def test_build_system_prompt_fixed_size(tmp_path):
    sm = SessionMemory.__new__(SessionMemory)
    sm._soul = "我是老七，一名专注的数字员工。"
    sm._core = type("C", (), {"as_prompt": lambda self: "## 核心记忆\n- 绝对不删数据"})()
    sm._retriever = None
    sm._store = None
    sm._employee_name = "test"
    sm._budget = ContextBudget(system_prompt_max=200, core_memory_max=100)

    prompt = sm.build_system_prompt("", skip_retrieval=True)
    assert len(prompt) <= 300
    assert "老七" in prompt
    assert "核心记忆" in prompt


def test_trim_working_memory():
    sm = SessionMemory.__new__(SessionMemory)
    sm._budget = ContextBudget(working_memory_turns=3)
    messages = []
    for i in range(5):
        messages.append({"role": "user", "content": f"msg {i}"})
        messages.append({"role": "assistant", "content": f"reply {i}"})
    trimmed = sm.trim_working_memory(messages)
    assert len(trimmed) == 6  # last 3 turns = 6 messages
    assert "msg 4" in trimmed[-1]["content"] or "reply 4" in trimmed[-1]["content"]


def test_context_budget_from_config():
    budget = ContextBudget.from_config()
    assert budget.system_prompt_max > 0
    assert budget.working_memory_turns > 0
