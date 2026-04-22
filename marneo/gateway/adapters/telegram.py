# marneo/gateway/adapters/telegram.py
"""Telegram channel adapter via python-telegram-bot."""
from __future__ import annotations
import asyncio
import logging
from typing import Any
from marneo.gateway.base import BaseChannelAdapter, ChannelMessage

log = logging.getLogger(__name__)


class TelegramAdapter(BaseChannelAdapter):
    def __init__(self, manager: Any) -> None:
        super().__init__("telegram")
        self._manager = manager
        self._app: Any = None

    def validate_config(self, config: dict[str, Any]) -> tuple[bool, str]:
        if not config.get("bot_token"):
            return False, "bot_token is required"
        return True, ""

    async def connect(self, config: dict[str, Any]) -> bool:
        ok, err = self.validate_config(config)
        if not ok:
            log.error("[Telegram] %s", err)
            return False
        try:
            from telegram.ext import Application, MessageHandler, filters
            from telegram import Update

            app = Application.builder().token(config["bot_token"]).build()
            adapter = self

            async def handle(update: Update, context: Any) -> None:
                if not update.message or not update.message.text:
                    return
                msg = ChannelMessage(
                    platform="telegram",
                    chat_id=str(update.effective_chat.id),
                    chat_type="group" if update.effective_chat.type != "private" else "dm",
                    user_id=str(update.effective_user.id) if update.effective_user else "",
                    user_name=update.effective_user.first_name if update.effective_user else "",
                    text=update.message.text,
                    msg_id=str(update.message.message_id),
                )
                await adapter._manager.dispatch(msg)

            app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
            self._app = app
            self._running = True
            asyncio.create_task(app.run_polling(drop_pending_updates=True))
            log.info("[Telegram] Connected")
            return True
        except Exception as e:
            log.error("[Telegram] Connect failed: %s", e)
            return False

    async def send_reply(self, chat_id: str, text: str, **kwargs: Any) -> bool:
        if not self._app:
            return False
        try:
            await self._app.bot.send_message(chat_id=int(chat_id), text=text)
            return True
        except Exception as e:
            log.error("[Telegram] Send failed: %s", e)
            return False

    async def disconnect(self) -> None:
        self._running = False
        if self._app:
            try:
                await self._app.stop()
            except Exception:
                pass
        log.info("[Telegram] Disconnected")
