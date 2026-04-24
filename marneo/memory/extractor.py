# marneo/memory/extractor.py
"""Heuristic episode extractor — no LLM required.

Detects signal phrases → classifies type → extracts summary.
"""
from __future__ import annotations

import re
from typing import Optional

from marneo.memory.episodes import Episode

_MIN_REPLY_LEN = 20

_PATTERNS = [
    ("decision", [
        r"我们决定", r"选择了", r"用.{1,10}而不是", r"改用", r"决定用", r"最终选",
        r"we decided", r"chose to", r"switched to",
    ]),
    ("discovery", [
        r"发现是", r"原来是", r"原因是", r"问题在于", r"解决方案", r"解决了",
        r"found that", r"turns out", r"figured out",
    ]),
    ("preference", [
        r"始终", r"一律", r"不要用", r"必须.*约定", r"约定是", r"规范",
        r"always use", r"never do", r"convention",
    ]),
    ("problem", [
        r"出错了", r"报错", r"失败.*原因", r"bug.*是", r"问题是.*导致",
        r"error.*because", r"failed.*due",
    ]),
    ("advice", [
        r"建议.*使用", r"推荐.*方案", r"最好.*方式", r"注意.*要",
        r"recommend", r"best practice",
    ]),
]


def _detect_type(text: str) -> Optional[str]:
    text_lower = text.lower()
    for mem_type, patterns in _PATTERNS:
        for pattern in patterns:
            if re.search(pattern, text_lower):
                return mem_type
    return None


def _extract_summary(reply: str, max_len: int = 200) -> str:
    sentences = re.split(r"[。！？\n]", reply)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 10]
    if not sentences:
        return reply[:max_len]
    summary = "。".join(sentences[:2])
    return summary[:max_len] if len(summary) > max_len else summary


def extract_episode(user_msg: str, assistant_reply: str) -> Optional[Episode]:
    """Extract an episode from a conversation turn. No LLM required."""
    if len(assistant_reply) < _MIN_REPLY_LEN:
        return None
    mem_type = _detect_type(assistant_reply)
    if mem_type is None:
        return None
    summary = _extract_summary(assistant_reply)
    tags = re.findall(r"[a-zA-Z][a-zA-Z0-9_\-\.]{2,}", user_msg + " " + assistant_reply)
    tags = list(dict.fromkeys(t.lower() for t in tags if len(t) < 30))[:5]
    return Episode(content=summary, type=mem_type, source="episode", tags=tags)
