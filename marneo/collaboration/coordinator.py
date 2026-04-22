# marneo/collaboration/coordinator.py
"""Coordinator: decides if team is needed, delegates, aggregates."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

log = logging.getLogger(__name__)

SPECIALIST_TIMEOUT = 60  # seconds to wait for each specialist


async def should_use_team(user_message: str, team_size: int) -> bool:
    """Use LLM to decide if this task needs team collaboration."""
    if team_size < 2:
        return False
    # Simple heuristic: long messages or explicit keywords suggest team work
    keywords = ["分析", "计划", "报告", "全面", "详细", "多方面", "综合"]
    if len(user_message) > 100 or any(k in user_message for k in keywords):
        return True
    return False


async def split_task_for_specialists(
    user_message: str,
    specialists: list[Any],  # list of TeamMember
    coordinator_engine: Any,
) -> dict[str, str]:
    """Use coordinator LLM to split task and assign to specialists."""
    if not specialists:
        return {}

    roles_desc = "\n".join(f"- {m.employee}（{m.role}）" for m in specialists)
    prompt = (
        f"你需要把以下任务分配给团队成员，每人处理自己专长的部分。\n\n"
        f"任务：{user_message}\n\n"
        f"团队成员：\n{roles_desc}\n\n"
        f"请为每位成员生成一句简洁的子任务描述（20-50字）。\n"
        f"输出格式（每行一个，不要其他内容）：\n"
        + "\n".join(f"{m.employee}: <子任务描述>" for m in specialists)
    )

    assignments: dict[str, str] = {}
    try:
        collected = []
        async for event in coordinator_engine.send(prompt):
            if event.type == "text":
                collected.append(event.content)
        text = "".join(collected)
        for line in text.splitlines():
            for member in specialists:
                if line.startswith(f"{member.employee}:"):
                    task = line[len(member.employee) + 1:].strip()
                    assignments[member.employee] = task
                    break
    except Exception as e:
        log.error("Task split error: %s", e)
        # Fallback: send same task to all
        for m in specialists:
            assignments[m.employee] = user_message

    return assignments


async def aggregate_results(
    original_task: str,
    results: dict[str, str],  # employee_name -> reply
    coordinator_engine: Any,
) -> str:
    """Use coordinator LLM to synthesize specialist results."""
    if not results:
        return ""

    parts = "\n\n".join(f"【{emp}的结果】\n{reply}" for emp, reply in results.items())
    prompt = (
        f"原始任务：{original_task}\n\n"
        f"团队各成员的工作结果：\n{parts}\n\n"
        "请综合以上结果，生成一份完整、连贯的回复。"
    )

    collected = []
    try:
        async for event in coordinator_engine.send(prompt):
            if event.type == "text":
                collected.append(event.content)
    except Exception as e:
        log.error("Aggregation error: %s", e)
        return "\n\n".join(f"{emp}：{r}" for emp, r in results.items())

    return "".join(collected).strip()


async def send_feishu_mention(
    feishu_config: Any,   # EmployeeFeishuConfig of coordinator
    team_chat_id: str,
    specialist_open_id: str,
    specialist_name: str,
    task_text: str,
) -> bool:
    """Send @mention message to specialist in team chat."""
    try:
        import lark_oapi as lark
        from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody
        import json

        domain = lark.LARK_DOMAIN if feishu_config.domain == "lark" else lark.FEISHU_DOMAIN
        client = lark.Client.builder() \
            .app_id(feishu_config.app_id) \
            .app_secret(feishu_config.app_secret) \
            .domain(domain) \
            .build()

        # Rich text with @mention
        content = {
            "zh_cn": {
                "content": [
                    [
                        {"tag": "at", "user_id": specialist_open_id},
                        {"tag": "text", "text": f" {task_text}"},
                    ]
                ]
            }
        }
        body = CreateMessageRequestBody.builder() \
            .receive_id(team_chat_id) \
            .msg_type("post") \
            .content(json.dumps(content, ensure_ascii=False)) \
            .build()
        req = CreateMessageRequest.builder() \
            .receive_id_type("chat_id") \
            .request_body(body) \
            .build()

        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(None, lambda: client.im.v1.message.create(req))  # type: ignore[union-attr]
        return resp.success()
    except Exception as e:
        log.error("Feishu mention error: %s", e)
        return False


async def run_team_session(
    user_message: str,
    team_config: Any,
    coordinator_engine: Any,
    progress_cb: Any = None,
) -> str:
    """Orchestrate parallel specialist sessions and aggregate results.

    Args:
        user_message: Original user request
        team_config: TeamConfig with coordinator, members, roles
        coordinator_engine: Coordinator's ChatSession for splitting + aggregating
        progress_cb: Optional async callback(msg: str) for TUI progress display

    Returns:
        Aggregated final reply string, or "" on failure
    """
    from marneo.employee.profile import load_profile  # type: ignore[import]
    from marneo.engine.chat import ChatSession  # type: ignore[import]

    specialists = team_config.specialists
    if not specialists:
        return ""

    async def _notify(msg: str) -> None:
        if progress_cb:
            try:
                await progress_cb(msg)
            except Exception:
                pass

    # ── Step 1: Split task ────────────────────────────────────────────
    await _notify(f"🔀 协调者正在拆分任务（{len(specialists)} 位专员）...")
    assignments = await split_task_for_specialists(
        user_message, specialists, coordinator_engine
    )
    if not assignments:
        return ""

    # ── Step 2: Parallel specialist sessions ─────────────────────────
    async def _run_specialist(member: Any) -> tuple[str, str]:
        emp_name = member.employee
        sub_task = assignments.get(emp_name, user_message)
        await _notify(f"⚡ {emp_name}（{member.role}）开始处理...")

        profile = load_profile(emp_name)
        system = f"你是 {emp_name}，{member.role}。专注处理分配给你的子任务，简洁回答。"
        if profile and profile.soul_path.exists():
            soul = profile.soul_path.read_text(encoding="utf-8").strip()
            system = f"{soul}\n\n{system}"

        session = ChatSession(system_prompt=system)
        parts: list[str] = []
        try:
            async for event in session.send(sub_task):
                if event.type == "text" and event.content:
                    parts.append(event.content)
        except Exception as e:
            log.error("[Team] specialist %s error: %s", emp_name, e)
            parts = [f"（{emp_name} 处理出错：{e}）"]

        reply = "".join(parts).strip()
        await _notify(f"✓ {emp_name} 完成")
        return emp_name, reply

    results_raw = await asyncio.gather(
        *[_run_specialist(m) for m in specialists],
        return_exceptions=True,
    )
    results: dict[str, str] = {
        emp: reply
        for item in results_raw
        if isinstance(item, tuple)
        for emp, reply in [item]
    }

    if not results:
        return ""

    # ── Step 3: Aggregate ─────────────────────────────────────────────
    await _notify("🔗 协调者正在汇总结果...")
    return await aggregate_results(user_message, results, coordinator_engine)
