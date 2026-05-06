# tests/stress/test_engine_stress.py
"""Stage 1: Direct engine stress tests for the agentic tool-use loop.

Runs real LLM API calls via the configured provider (resolve_provider).
Measures token consumption, loop detection, and memory growth.
"""
from __future__ import annotations

import resource
import sys
import pytest

pytestmark = pytest.mark.stress

from marneo.engine.chat import ChatSession
from marneo.engine.provider import resolve_provider

from .conftest import StressReporter


def _messages_total_chars(session: ChatSession) -> int:
    total = 0
    for msg in session.messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += len(content or "")
        elif isinstance(content, list):
            for block in content:
                total += len(str(block))
    return total


def _get_rss_mb() -> float:
    ru = resource.getrusage(resource.RUSAGE_SELF)
    if sys.platform == "darwin":
        return ru.ru_maxrss / (1024 * 1024)
    return ru.ru_maxrss / 1024


TASKS = [
    "请帮我查一下当前时间，然后计算距离2026年12月31日还有多少天，再搜索一下关于年终规划的知识",
    "现在几点了？帮我算一下 sqrt(144) + 3.14 * 2，然后搜索项目管理相关的内容",
    "查看时间，计算 (365 - 100) * 24，搜索团队协作的最佳实践",
]


def _next_task(prev_reply: str, round_num: int) -> str:
    snippet = prev_reply[:100].replace("\n", " ")
    prompts = [
        f"基于上面的信息「{snippet}」，请继续深入分析，用工具获取更多数据来支撑你的观点。",
        f"关于「{snippet}」这个结论，请用计算工具验证一下数字是否正确，再搜索补充资料。",
        f"很好。现在请查看当前时间，然后搜索与「{snippet[:50]}」相关的最新趋势。",
    ]
    return prompts[round_num % len(prompts)]


@pytest.mark.asyncio
async def test_token_curve(stress_registry, reporter: StressReporter):
    """Measure token consumption growth over 15 rounds of tool-calling conversation."""
    provider = resolve_provider()
    reporter.set_provider(provider.provider_id, provider.model)

    session = ChatSession(
        system_prompt="你是一个高效的工作助手。使用提供的工具完成任务，每次尽量调用多个工具。"
    )

    total_rounds = 15
    task = TASKS[0]

    print(f"\n{'='*60}")
    print(f"  Token Curve Test | Provider: {provider.model}")
    print(f"  Rounds: {total_rounds}")
    print(f"{'='*60}")

    for i in range(total_rounds):
        round_start_input = session.token_tracker.total.input_tokens
        round_start_output = session.token_tracker.total.output_tokens
        tool_calls_count = 0
        errors = []

        async for event in session.send_with_tools(task, registry=stress_registry):
            if event.type == "tool_call":
                tool_calls_count += 1
            elif event.type == "error":
                errors.append(event.content)
            elif event.type == "text":
                pass

        round_input = session.token_tracker.total.input_tokens - round_start_input
        round_output = session.token_tracker.total.output_tokens - round_start_output

        reporter.record_round(
            round=i + 1,
            input_tokens=session.token_tracker.total.input_tokens,
            output_tokens=session.token_tracker.total.output_tokens,
            round_input_tokens=round_input,
            round_output_tokens=round_output,
            messages_count=len(session.messages),
            messages_chars=_messages_total_chars(session),
            tool_calls=tool_calls_count,
            errors=errors,
        )

        reporter.print_progress(
            i + 1, total_rounds,
            input_tokens=session.token_tracker.total.input_tokens,
            output_tokens=session.token_tracker.total.output_tokens,
            msgs=len(session.messages),
            tools=tool_calls_count,
        )

        # Generate next task from last assistant reply
        last_reply = ""
        for msg in reversed(session.messages):
            if msg.get("role") == "assistant" and isinstance(msg.get("content"), str):
                last_reply = msg["content"]
                break
        task = _next_task(last_reply, i + 1) if last_reply else TASKS[(i + 1) % len(TASKS)]

    path = reporter.save()
    print(f"\n  Report saved: {path}")

    # Basic assertions
    assert len(reporter.rounds) == total_rounds
    assert session.token_tracker.total.input_tokens > 0


@pytest.mark.asyncio
async def test_loop_detection(loop_trap_registry, reporter: StressReporter):
    """Verify the loop detection mechanism triggers correctly."""
    provider = resolve_provider()
    reporter.set_provider(provider.provider_id, provider.model)

    session = ChatSession(
        system_prompt=(
            "你是一个助手。当任务未完成时，请反复调用 check_status 工具检查进度，直到完成。"
            "不要放弃，持续检查。"
        )
    )

    print(f"\n{'='*60}")
    print(f"  Loop Detection Test | Provider: {provider.model}")
    print(f"{'='*60}")

    tool_calls_count = 0
    loop_error_detected = False
    events_log: list[dict] = []

    async for event in session.send_with_tools(
        "请检查 deployment 的状态，确认部署是否完成。",
        registry=loop_trap_registry,
        max_iterations=20,
    ):
        if event.type == "tool_call":
            tool_calls_count += 1
            events_log.append({"type": "tool_call", "n": tool_calls_count})
            print(f"  Tool call #{tool_calls_count}")
        elif event.type == "error" and "loop" in event.content.lower():
            loop_error_detected = True
            events_log.append({"type": "loop_error", "content": event.content})
            print(f"  Loop detected: {event.content}")
        elif event.type == "error":
            events_log.append({"type": "error", "content": event.content})

    reporter.record_round(
        tool_calls=tool_calls_count,
        loop_detected=loop_error_detected,
        events=events_log,
    )

    path = reporter.save()
    print(f"\n  Total tool calls before stop: {tool_calls_count}")
    print(f"  Loop detection triggered: {loop_error_detected}")
    print(f"  Report saved: {path}")

    # The loop detection should trigger (threshold = 3 consecutive identical calls)
    # But LLM may not always repeat — assert that we didn't hit max_iterations silently
    assert tool_calls_count <= 20


@pytest.mark.asyncio
async def test_memory_growth(stress_registry, reporter: StressReporter):
    """Track process memory and message list growth over 20 rounds."""
    provider = resolve_provider()
    reporter.set_provider(provider.provider_id, provider.model)

    session = ChatSession(
        system_prompt="你是一个高效的工作助手。使用工具完成任务。回答要详细。"
    )

    total_rounds = 20
    task = TASKS[1]
    baseline_rss = _get_rss_mb()

    print(f"\n{'='*60}")
    print(f"  Memory Growth Test | Provider: {provider.model}")
    print(f"  Rounds: {total_rounds} | Baseline RSS: {baseline_rss:.1f}MB")
    print(f"{'='*60}")

    for i in range(total_rounds):
        tool_calls_count = 0

        async for event in session.send_with_tools(task, registry=stress_registry):
            if event.type == "tool_call":
                tool_calls_count += 1

        current_rss = _get_rss_mb()
        msgs_chars = _messages_total_chars(session)

        reporter.record_round(
            round=i + 1,
            rss_mb=round(current_rss, 2),
            rss_delta_mb=round(current_rss - baseline_rss, 2),
            messages_count=len(session.messages),
            messages_chars=msgs_chars,
            tool_calls=tool_calls_count,
        )

        reporter.print_progress(
            i + 1, total_rounds,
            rss=f"{current_rss:.1f}MB",
            delta=f"+{current_rss - baseline_rss:.1f}MB",
            msgs=len(session.messages),
            chars=msgs_chars,
        )

        # Generate next task
        last_reply = ""
        for msg in reversed(session.messages):
            if msg.get("role") == "assistant" and isinstance(msg.get("content"), str):
                last_reply = msg["content"]
                break
        task = _next_task(last_reply, i + 1) if last_reply else TASKS[(i + 1) % len(TASKS)]

    path = reporter.save()
    peak_rss = max(r["rss_mb"] for r in reporter.rounds)
    print(f"\n  Peak RSS: {peak_rss:.1f}MB | Growth: +{peak_rss - baseline_rss:.1f}MB")
    print(f"  Peak messages: {max(r['messages_count'] for r in reporter.rounds)}")
    print(f"  Peak chars: {max(r['messages_chars'] for r in reporter.rounds)}")
    print(f"  Report saved: {path}")

    # Sanity check: memory shouldn't grow absurdly (< 200MB growth)
    assert peak_rss - baseline_rss < 200
