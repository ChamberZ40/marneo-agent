# marneo/gateway/adapters/discord_adapter.py
"""Discord channel adapter via discord.py."""
from __future__ import annotations
import asyncio
import logging
from typing import Any
from marneo.gateway.base import BaseChannelAdapter, ChannelMessage

log = logging.getLogger(__name__)


class DiscordAdapter(BaseChannelAdapter):
    def __init__(self, manager: Any) -> None:
        super().__init__("discord")
        self._manager = manager
        self._client: Any = None

    def validate_config(self, config: dict[str, Any]) -> tuple[bool, str]:
        if not config.get("bot_token"):
            return False, "bot_token is required"
        return True, ""

    async def connect(self, config: dict[str, Any]) -> bool:
        ok, err = self.validate_config(config)
        if not ok:
            log.error("[Discord] %s", err)
            return False
        try:
            import discord
            intents = discord.Intents.default()
            intents.message_content = True
            client = discord.Client(intents=intents)
            adapter = self

            @client.event
            async def on_message(message: discord.Message) -> None:
                if message.author == client.user:
                    return
                msg = ChannelMessage(
                    platform="discord",
                    chat_id=str(message.channel.id),
                    chat_type="dm" if isinstance(message.channel, discord.DMChannel) else "group",
                    user_id=str(message.author.id),
                    user_name=str(message.author.name),
                    text=message.content,
                    msg_id=str(message.id),
                )
                await adapter._manager.dispatch(msg)

            self._client = client
            self._running = True
            asyncio.create_task(client.start(config["bot_token"]))
            log.info("[Discord] Connected")
            return True
        except Exception as e:
            log.error("[Discord] Connect failed: %s", e)
            return False

    async def send_reply(self, chat_id: str, text: str, **kwargs: Any) -> bool:
        if not self._client:
            return False
        try:
            channel = self._client.get_channel(int(chat_id))
            if channel:
                await channel.send(text)
                return True
            return False
        except Exception as e:
            log.error("[Discord] Send failed: %s", e)
            return False

    async def disconnect(self) -> None:
        self._running = False
        if self._client:
            try:
                await self._client.close()
            except Exception:
                pass
        log.info("[Discord] Disconnected")
