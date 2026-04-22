# marneo/employee/growth.py
"""Employee growth system — level thresholds, level-up check, promotion."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from marneo.employee.profile import (
    LEVEL_ORDER, EmployeeProfile, load_profile, save_profile,
)

# (min_days_at_level, min_level_conversations, min_level_skills)
LEVELUP_THRESHOLDS: dict[str, tuple[int, int, int]] = {
    "实习生":  (7,  20, 0),
    "初级员工": (14, 50, 3),
    "中级员工": (30, 100, 8),
    "高级员工": (0,  0,  0),  # max level
}


def days_at_level(profile: EmployeeProfile) -> int:
    if not profile.hired_at:
        return 0
    try:
        ref = datetime.fromisoformat(profile.hired_at)
        now = datetime.now(timezone.utc)
        if ref.tzinfo is None:
            ref = ref.replace(tzinfo=timezone.utc)
        return max(0, (now - ref).days)
    except ValueError:
        return 0


def should_level_up(profile: EmployeeProfile) -> bool:
    if profile.level not in LEVELUP_THRESHOLDS:
        return False
    min_days, min_convs, min_skills = LEVELUP_THRESHOLDS[profile.level]
    if min_days == 0 and min_convs == 0:
        return False
    return (
        days_at_level(profile) >= min_days
        and profile.level_conversations >= min_convs
        and profile.level_skills >= min_skills
    )


def next_level(current: str) -> str | None:
    try:
        idx = LEVEL_ORDER.index(current)
        return LEVEL_ORDER[idx + 1] if idx + 1 < len(LEVEL_ORDER) else None
    except ValueError:
        return None


def promote(name: str) -> tuple[str | None, str | None]:
    """Promote to next level. Returns (old_level, new_level)."""
    profile = load_profile(name)
    if not profile:
        return None, None
    new_lv = next_level(profile.level)
    if not new_lv:
        return profile.level, None
    updated = replace(
        profile,
        level=new_lv,
        hired_at=datetime.now(timezone.utc).isoformat(),
        level_conversations=0,
        level_skills=0,
    )
    save_profile(updated)
    return profile.level, new_lv


def build_level_directive(profile: EmployeeProfile) -> str:
    directives = {
        "实习生": (
            "# 你的当前状态：实习生\n"
            "- 遇到不确定的地方主动询问\n"
            "- 每次帮助后思考有无可学的新知识\n"
            "- 保持谦逊，不要假装什么都会"
        ),
        "初级员工": (
            "# 你的当前状态：初级员工\n"
            "- 把份内的事做好，认真完成任务\n"
            "- 完成后简要汇报做了什么\n"
            "- 对于明确的任务直接执行"
        ),
        "中级员工": (
            "# 你的当前状态：中级员工\n"
            "- 不等用户问，主动提出观察到的问题\n"
            "- 在完成任务同时提出可改进的地方\n"
            "- 关注用户的整体目标"
        ),
        "高级员工": (
            "# 你的当前状态：高级员工\n"
            "- 理解用户的长期目标，每次回复考虑整体方向\n"
            "- 主动识别潜在问题并提出预防措施\n"
            "- 用精炼的语言传达深刻的洞察"
        ),
    }
    return directives.get(profile.level, "")
