# marneo/employee/report_push.py
"""Push reports to gateway channel."""
from __future__ import annotations
import asyncio
import logging
import yaml
log = logging.getLogger(__name__)


async def push_to_channel(text: str, platform: str, chat_id: str) -> bool:
    from marneo.gateway.config import get_channel_config
    config = get_channel_config(platform)
    if not config or not config.get("enabled"):
        return False
    try:
        if platform == "feishu":
            from marneo.gateway.adapters.feishu import FeishuChannelAdapter
            from marneo.gateway.manager import GatewayManager
            adapter = FeishuChannelAdapter(GatewayManager())
            if await adapter.connect(config):
                result = await adapter.send_reply(chat_id, text)
                await adapter.disconnect()
                return result
        elif platform == "wechat":
            from marneo.gateway.adapters.wechat import WeChatChannelAdapter
            from marneo.gateway.manager import GatewayManager
            adapter = WeChatChannelAdapter(GatewayManager())
            if await adapter.connect(config):
                result = await adapter.send_reply(chat_id, text)
                await adapter.disconnect()
                return result
        elif platform == "telegram":
            from marneo.gateway.adapters.telegram import TelegramAdapter
            from marneo.gateway.manager import GatewayManager
            adapter = TelegramAdapter(GatewayManager())
            if await adapter.connect(config):
                result = await adapter.send_reply(chat_id, text)
                await adapter.disconnect()
                return result
    except Exception as e:
        log.error("push_to_channel error: %s", e)
    return False


def push_report(text: str, employee_name: str) -> bool:
    from marneo.core.paths import get_employees_dir
    config_path = get_employees_dir() / employee_name / "push.yaml"
    if not config_path.exists():
        return False
    try:
        cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        platform = cfg.get("platform", "")
        chat_id = cfg.get("chat_id", "")
        if not platform or not chat_id:
            return False
    except Exception:
        return False
    return asyncio.run(push_to_channel(text, platform, chat_id))


def configure_push(employee_name: str, platform: str, chat_id: str) -> None:
    from marneo.core.paths import get_employees_dir
    path = get_employees_dir() / employee_name / "push.yaml"
    path.write_text(
        yaml.dump({"platform": platform, "chat_id": chat_id}, allow_unicode=True),
        encoding="utf-8",
    )
