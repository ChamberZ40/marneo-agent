# marneo/employee/skill_learner.py
"""Auto-extract learnable skills from conversations."""
from __future__ import annotations
import logging
log = logging.getLogger(__name__)

MIN_TEXT_LEN = 200
LEARNING_LEVELS = {"实习生", "初级员工"}


def should_learn(level: str, reply_text: str) -> bool:
    return level in LEARNING_LEVELS and len(reply_text) >= MIN_TEXT_LEN


def extract_skill_insight(user_msg: str, assistant_reply: str) -> str | None:
    from marneo.employee.interview import _call_llm
    prompt = (
        f"分析以下对话，判断其中是否有值得提炼为可复用技能的知识点。\n\n"
        f"用户：{user_msg[:300]}\n助手：{assistant_reply[:800]}\n\n"
        "如果有，用一句话（20-60字）概括这个技能点，直接输出内容。\n"
        "如果没有值得提炼的技能（闲聊、简单问答等），只输出：SKIP"
    )
    try:
        result = _call_llm(
            [{"role": "user", "content": prompt}],
            system="你是一个技能提炼助手，简洁输出。",
            max_tokens=100,
        )
        return None if result.upper().startswith("SKIP") else result.strip() or None
    except Exception as e:
        log.debug("skill extraction error: %s", e)
        return None


def maybe_save_skill(employee_name: str, user_msg: str, reply: str) -> str | None:
    """Extract and save skill if appropriate. Returns insight or None."""
    from marneo.employee.profile import load_profile
    profile = load_profile(employee_name)
    if not profile or not should_learn(profile.level, reply):
        return None

    insight = extract_skill_insight(user_msg, reply)
    if not insight:
        return None

    from marneo.project.skills import Skill, save_skill, list_skills
    import time

    # Avoid duplicates
    existing = [s.description for s in list_skills()]
    if any(insight[:20] in desc for desc in existing):
        return None

    skill_id = f"auto-{int(time.time())}"
    skill = Skill(
        id=skill_id,
        name=insight[:30],
        description=insight,
        scope="global",
        content=f"从对话中提炼：\n{insight}",
    )
    save_skill(skill)
    return insight
