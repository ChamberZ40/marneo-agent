# marneo/project/interview.py
"""LLM-driven project interview — generates project.yaml data + AGENT.md."""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

MAX_ROUNDS = 8
MIN_ROUNDS = 5

_INTERVIEWER_SYSTEM = """\
你是一位项目管理顾问，正在帮助团队梳理一个新项目的背景信息。
你的目标是通过对话收集足够信息，最终生成项目配置和数字员工的项目工作档案。

访谈规则：
- 每次只问一个问题，简短有力
- 根据前面的回答动态调整下一个问题
- 前 {min_rounds} 轮必须继续；之后如果信息足够，输出 ##DONE##
- 问题要覆盖：项目目标/KPI/团队/工具/挑战/工作方式
- 每个问题附带 3-4 个选项（字母编号），允许追加自由回答

格式（严格遵守）：
问题文本

A. 选项一
B. 选项二
C. 选项三
D. 其他（请自行描述）

只输出问题+选项（或 ##DONE##），不要任何前缀。
"""

_AGENT_SYSTEM = """\
你是一位 HR 专家，请根据以下项目访谈记录，为数字员工生成项目工作档案（AGENT.md）。

项目名称：{project_name}
访谈记录：
{qa_content}

要求：
1. 第一行：# {project_name} — 工作档案
2. 包含 ## 核心职责 / ## 工作目标 / ## 工作规范 / ## 协作方式 四节
3. 每节 3-5 条精炼要点，总字数 300-500 字
4. 基于访谈内容，专业具体

直接输出内容，不要解释。
"""

_YAML_SYSTEM = """\
根据以下项目访谈记录，提取结构化信息。

访谈记录：
{qa_content}

请用 JSON 格式输出以下字段（如无明确信息则用空字符串或空列表）：
{{
  "description": "一句话描述项目",
  "goals": ["目标1", "目标2"],
  "kpis": [{{"name": "KPI名称", "target": "目标值", "unit": "单位"}}],
  "tools": ["工具1", "工具2"]
}}

只输出 JSON，不要任何其他内容。
"""


def _call_llm(messages: list[dict], *, system: str, max_tokens: int = 800) -> str:
    """Reuse employee interview LLM caller."""
    from marneo.employee.interview import _call_llm as _base
    return _base(messages, system=system, max_tokens=max_tokens)


def next_question(history: list[dict], round_number: int) -> str | None:
    system = _INTERVIEWER_SYSTEM.format(min_rounds=MIN_ROUNDS)
    msgs = history if history else [{"role": "user", "content": "请开始项目访谈，提出第一个问题。"}]
    try:
        response = _call_llm(msgs, system=system, max_tokens=300)
    except Exception as e:
        log.error("Project interview error: %s", e)
        return None
    if "##DONE##" in response or round_number >= MAX_ROUNDS:
        return None
    return response.replace("##DONE##", "").strip() or None


def synthesize_agent_md(history: list[dict], project_name: str) -> str:
    qa_content = "\n\n".join(
        f"{'问' if m['role'] == 'assistant' else '答'}：{m['content']}"
        for m in history
    )
    system = _AGENT_SYSTEM.format(project_name=project_name, qa_content=qa_content)
    try:
        return _call_llm(
            [{"role": "user", "content": f"请为 {project_name} 项目生成工作档案。"}],
            system=system, max_tokens=800,
        )
    except Exception as e:
        log.error("AGENT.md synthesis error: %s", e)
        return f"# {project_name} — 工作档案\n\n## 核心职责\n- 推进项目目标\n"


def extract_project_yaml_data(history: list[dict]) -> dict:
    import json
    qa_content = "\n\n".join(
        f"{'问' if m['role'] == 'assistant' else '答'}：{m['content']}"
        for m in history
    )
    system = _YAML_SYSTEM.format(qa_content=qa_content)
    try:
        raw = _call_llm(
            [{"role": "user", "content": "请提取项目信息。"}],
            system=system, max_tokens=400,
        )
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(lines[1:])
        if raw.endswith("```"):
            raw = "\n".join(raw.splitlines()[:-1])
        return json.loads(raw.strip())
    except Exception as e:
        log.error("YAML extraction error: %s", e)
        return {"description": "", "goals": [], "kpis": [], "tools": []}
