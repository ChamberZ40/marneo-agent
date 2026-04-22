# marneo/employee/interview.py
"""LLM-driven interview engine for marneo hire."""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

MAX_ROUNDS = 8
MIN_ROUNDS = 5

_INTERVIEWER_SYSTEM = """\
你是一位资深的数字员工档案顾问，正在对一名新入职的数字员工进行入职深度访谈。
你的目标是通过对话收集足够的信息，最终生成这名员工的 SOUL.md 身份档案。

访谈规则：
- 每次只问一个问题，简短有力
- 根据前面的回答动态调整问题方向
- 前 {min_rounds} 轮必须继续；之后如果信息足够，输出 ##DONE##
- 问题要覆盖：价值观/性格/热情/工作哲学/与用户相处方式
- 每个问题附带 3-4 个选项（字母编号），允许追加自由回答

格式（严格遵守）：
问题文本

A. 选项一
B. 选项二
C. 选项三
D. 其他（请自行描述）

只输出问题+选项（或 ##DONE##），不要任何前缀。
"""

_SOUL_SYSTEM = """\
你是一位精通人物传记的写作专家。
根据以下访谈记录，为这名数字员工撰写 SOUL.md 私人自述。

访谈记录：
{qa_content}

要求：
1. 用第一人称，语气真实有温度，200-350 字，像写给用户的信
2. 融合访谈内容自然叙述，不要直接引用问题
3. 末尾一行是标志性口头禅（10 字以内，加 > 引用格式）

直接输出内容，不要任何前缀或标题。
"""


def _call_llm(messages: list[dict], *, system: str, max_tokens: int = 800) -> str:
    """Synchronous LLM call. Returns text content."""
    import os
    from marneo.core.config import load_config

    cfg = load_config()
    if cfg.provider and cfg.provider.api_key:
        api_key = cfg.provider.api_key
        base_url = cfg.provider.base_url or None
        model = cfg.provider.model or "claude-haiku-4-5-20251001"
        protocol = cfg.provider.protocol
    else:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        base_url = None
        model = "claude-haiku-4-5-20251001"
        protocol = "anthropic-compatible"

    if protocol == "openai-compatible":
        from openai import OpenAI
        client_kwargs: dict = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
        client = OpenAI(**client_kwargs)
        all_msgs = [{"role": "system", "content": system}] + messages
        resp = client.chat.completions.create(
            model=model, max_tokens=max_tokens,
            messages=all_msgs,  # type: ignore[arg-type]
        )
        # Use model_dump() to get actual content — msg.content attribute
        # may return empty string on some providers (e.g. MiniMax) even when
        # the raw dict has content, due to Pydantic field resolution order.
        msg = resp.choices[0].message
        content = (msg.model_dump().get("content") or msg.content or "").strip()
        return content
    else:
        import anthropic
        client_kwargs = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
        client = anthropic.Anthropic(**client_kwargs)
        msg = client.messages.create(
            model=model, max_tokens=max_tokens,
            system=system,
            messages=messages,  # type: ignore[arg-type]
        )
        for block in msg.content:
            if hasattr(block, "text"):
                return block.text.strip()  # type: ignore[union-attr]
        return ""


def next_question(history: list[dict], round_number: int) -> str | None:
    """Ask LLM for next interview question. Returns None when done."""
    system = _INTERVIEWER_SYSTEM.format(min_rounds=MIN_ROUNDS)
    msgs = history if history else [{"role": "user", "content": "请开始面试，提出第一个问题。"}]
    try:
        response = _call_llm(msgs, system=system, max_tokens=300)
    except Exception as e:
        log.error("Interview LLM error: %s", e)
        return None
    if "##DONE##" in response or round_number >= MAX_ROUNDS:
        return None
    return response.replace("##DONE##", "").strip() or None


def parse_question(raw: str) -> tuple[str, list[tuple[str, str]]]:
    """Parse 'question\\nA. opt\\nB. opt' → (question_text, [(letter, text)])."""
    lines = [l.rstrip() for l in raw.strip().splitlines()]
    options: list[tuple[str, str]] = []
    question_lines: list[str] = []
    in_options = False
    for line in lines:
        stripped = line.strip()
        if (len(stripped) >= 3 and stripped[0].isupper()
                and stripped[1] in ".、)" and stripped[2] == " "):
            in_options = True
            options.append((stripped[0], stripped[3:].strip()))
        elif not in_options and stripped:
            question_lines.append(stripped)
    return " ".join(question_lines).strip(), options


def synthesize_soul(history: list[dict]) -> str:
    """Generate SOUL.md from interview history."""
    qa_content = "\n\n".join(
        f"{'问' if m['role'] == 'assistant' else '答'}：{m['content']}"
        for m in history
    )
    system = _SOUL_SYSTEM.format(qa_content=qa_content)
    try:
        return _call_llm(
            [{"role": "user", "content": "请根据以上访谈记录生成 SOUL.md。"}],
            system=system, max_tokens=800,
        )
    except Exception as e:
        log.error("SOUL synthesis error: %s", e)
        return "# 数字员工\n\n我是一名专注的数字员工，致力于帮助用户推进项目目标。\n\n> 数据即答案。"
