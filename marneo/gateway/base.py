# marneo/gateway/base.py
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChannelMessage:
    platform: str
    chat_id: str
    user_id: str = ""
    user_name: str = ""
    chat_type: str = "dm"
    text: str = ""
    msg_id: str = ""
    context_token: str = ""
    attachments: list[dict[str, Any]] = field(default_factory=list)  # Each: {"data": bytes, "media_type": str, "filename": str}


class BaseChannelAdapter(ABC):
    def __init__(self, platform: str) -> None:
        self.platform = platform
        self._running = False

    @abstractmethod
    async def connect(self, config: dict[str, Any]) -> bool: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    @abstractmethod
    async def send_reply(self, chat_id: str, text: str, **kwargs: Any) -> bool: ...

    def validate_config(self, config: dict[str, Any]) -> tuple[bool, str]:
        return True, ""

    @property
    def is_running(self) -> bool:
        return self._running
