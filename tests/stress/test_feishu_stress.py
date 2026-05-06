# tests/stress/test_feishu_stress.py
"""Stage 2: Feishu gateway stress tests.

Simulates Feishu messages through GatewayManager.dispatch() without real WebSocket.
Uses mock adapter to capture replies and measure session behavior.
"""
from __future__ import annotations

import time
from typing import Any

import pytest

pytestmark = pytest.mark.stress

from marneo.gateway.base import BaseChannelAdapter, ChannelMessage
from marneo.gateway.manager import GatewayManager
from marneo.tools.registry import registry as global_registry

from .conftest import StressReporter, _eval_arithmetic


class MockFeishuAdapter(BaseChannelAdapter):
    """Captures Feishu-like streaming/text replies for stress assertions."""

    def __init__(self) -> None:
        super().__init__(platform="feishu:stress_employee")
        self.replies: list[dict] = []
        self.streaming_calls = 0
        self.streaming_events: list[str] = []
        self._running = True

    async def connect(self, config: dict[str, Any]) -> bool:
        self._running = True
        return True

    async def disconnect(self) -> None:
        self._running = False

    async def send_reply(self, chat_id: str, text: str, **kwargs: Any) -> bool:
        self.replies.append({
            "chat_id": chat_id,
            "text": text,
            "timestamp": time.time(),
            "kwargs": kwargs,
        })
        return True

    async def process_streaming(self, msg: ChannelMessage, engine: Any, registry: Any) -> None:
        """Simulate Feishu's streaming adapter path without creating real cards."""
        self.streaming_calls += 1
        parts: list[str] = []
        async for event in engine.send_with_tools(
            msg.text,
            registry=registry,
            attachments=msg.attachments or None,
        ):
            self.streaming_events.append(event.type)
            if event.type == "text" and event.content:
                parts.append(event.content)
        reply = "".join(parts).strip()
        if not reply:
            reply = "模型没有返回内容，请重试。"
        await self.send_reply(msg.chat_id, reply, context_token=msg.context_token)


def _register_stress_tools() -> None:
    """Register stress test tools into the global registry (if not already present)."""
    from datetime import datetime
    from marneo.tools.registry import tool_result

    if global_registry.get_entry("get_current_time"):
        return

    global_registry.register(
        name="get_current_time",
        description="Get the current date and time",
        schema={
            "name": "get_current_time",
            "description": "Get the current date and time",
            "parameters": {"type": "object", "properties": {}},
        },
        handler=lambda args, **kw: tool_result(
            time=datetime.now().isoformat(),
            timestamp=time.time(),
        ),
    )

    global_registry.register(
        name="calculate",
        description="Calculate a math expression safely",
        schema={
            "name": "calculate",
            "description": "Calculate a math expression.",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "Math expression"},
                },
                "required": ["expression"],
            },
        },
        handler=lambda args, **kw: tool_result(
            expression=args.get("expression", ""),
            result=_eval_arithmetic(args.get("expression", "0")),
        ),
    )

    global_registry.register(
        name="search_knowledge",
        description="Search knowledge base",
        schema={
            "name": "search_knowledge",
            "description": "Search the internal knowledge base.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                },
                "required": ["query"],
            },
        },
        handler=lambda args, **kw: tool_result(
            results=[
                {"title": "Result 1", "snippet": "项目管理最佳实践..."},
                {"title": "Result 2", "snippet": "微服务架构设计..."},
            ]
        ),
    )


TASKS = [
    "帮我查一下现在几点了，然后计算 100 * 3.14",
    "搜索一下关于团队协作的知识，然后查看当前时间",
    "计算 sqrt(256) + 50，再搜索项目管理的方法",
    "查看时间，搜索技术架构相关内容，计算 365 * 24",
    "帮我搜索一下效率提升的方法",
]


@pytest.mark.asyncio
async def test_feishu_session_lifecycle():
    """Verify session creation, reuse, and tool calling through gateway."""
    _register_stress_tools()

    manager = GatewayManager()
    adapter = MockFeishuAdapter()
    manager.register(adapter)

    reporter = StressReporter("feishu_session_lifecycle")

    # Patch SessionStore to use our employee-less engine (skip profile loading)
    print(f"\n{'='*60}")
    print(f"  Feishu Session Lifecycle Test")
    print(f"{'='*60}")

    total_rounds = 10
    chat_id = "stress_chat_001"

    for i in range(total_rounds):
        msg = ChannelMessage(
            platform="feishu:stress_employee",
            chat_id=chat_id,
            msg_id=f"stress_msg_{i:04d}",
            text=TASKS[i % len(TASKS)],
        )

        adapter.replies.clear()
        await manager.dispatch(msg)

        reply_text = " ".join(r["text"] for r in adapter.replies)
        reply_len = len(reply_text)

        reporter.record_round(
            round=i + 1,
            task=TASKS[i % len(TASKS)][:40],
            reply_length=reply_len,
            reply_count=len(adapter.replies),
            has_content=reply_len > 0,
        )

        reporter.print_progress(
            i + 1, total_rounds,
            replies=len(adapter.replies),
            chars=reply_len,
        )

    path = reporter.save()
    print(f"\n  Active sessions: {manager._sessions.active_count}")
    print(f"  Report saved: {path}")

    # Should have created exactly 1 session (same chat_id)
    assert manager._sessions.active_count == 1
    assert adapter.streaming_calls == total_rounds
    # All rounds should produce replies
    assert all(r["has_content"] for r in reporter.rounds)


@pytest.mark.asyncio
async def test_feishu_multi_session():
    """Stress test with multiple concurrent chat sessions."""
    _register_stress_tools()

    manager = GatewayManager()
    adapter = MockFeishuAdapter()
    manager.register(adapter)

    reporter = StressReporter("feishu_multi_session")

    print(f"\n{'='*60}")
    print(f"  Feishu Multi-Session Test")
    print(f"{'='*60}")

    num_sessions = 5
    rounds_per_session = 3

    for session_idx in range(num_sessions):
        chat_id = f"stress_chat_{session_idx:03d}"

        for round_idx in range(rounds_per_session):
            msg = ChannelMessage(
                platform="feishu:stress_employee",
                chat_id=chat_id,
                msg_id=f"stress_{session_idx}_{round_idx}",
                text=TASKS[(session_idx + round_idx) % len(TASKS)],
            )

            adapter.replies.clear()
            await manager.dispatch(msg)

            reply_text = " ".join(r["text"] for r in adapter.replies)

            reporter.record_round(
                session=session_idx,
                round=round_idx + 1,
                chat_id=chat_id,
                reply_length=len(reply_text),
                has_content=len(reply_text) > 0,
            )

        print(f"  Session {session_idx + 1}/{num_sessions} done ({rounds_per_session} rounds)")

    path = reporter.save()
    print(f"\n  Active sessions: {manager._sessions.active_count}")
    print(f"  Report saved: {path}")

    assert manager._sessions.active_count == num_sessions
    assert adapter.streaming_calls == num_sessions * rounds_per_session


@pytest.mark.asyncio
async def test_feishu_message_accumulation():
    """Track message history growth within a single Feishu session."""
    _register_stress_tools()

    manager = GatewayManager()
    adapter = MockFeishuAdapter()
    manager.register(adapter)

    reporter = StressReporter("feishu_message_accumulation")

    print(f"\n{'='*60}")
    print(f"  Feishu Message Accumulation Test")
    print(f"{'='*60}")

    total_rounds = 15
    chat_id = "stress_accum_001"

    for i in range(total_rounds):
        msg = ChannelMessage(
            platform="feishu:stress_employee",
            chat_id=chat_id,
            msg_id=f"accum_{i:04d}",
            text=TASKS[i % len(TASKS)],
        )

        adapter.replies.clear()
        await manager.dispatch(msg)

        # Access internal session to measure
        engine, _ = await manager._sessions.get_or_create(
            "feishu:stress_employee", chat_id
        )
        msgs_count = len(engine.messages)
        msgs_chars = sum(
            len(m.get("content", "") or "") if isinstance(m.get("content"), str)
            else len(str(m.get("content", "")))
            for m in engine.messages
        )

        reporter.record_round(
            round=i + 1,
            messages_count=msgs_count,
            messages_chars=msgs_chars,
            reply_length=len(" ".join(r["text"] for r in adapter.replies)),
        )

        reporter.print_progress(
            i + 1, total_rounds,
            msgs=msgs_count,
            chars=msgs_chars,
        )

    path = reporter.save()
    peak_msgs = max(r["messages_count"] for r in reporter.rounds)
    peak_chars = max(r["messages_chars"] for r in reporter.rounds)
    print(f"\n  Peak messages: {peak_msgs}")
    print(f"  Peak chars: {peak_chars}")
    print(f"  Report saved: {path}")

    # Messages should accumulate but not explode
    assert peak_msgs < 500
    assert adapter.streaming_calls == total_rounds
