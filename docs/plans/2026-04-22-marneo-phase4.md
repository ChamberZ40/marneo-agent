# Marneo Agent Phase 4 — Gateway Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 实现 Gateway 系统：后台守护进程管理所有 IM 渠道连接，`marneo gateway start` 后台启动立即返回，消息路由到正确的员工，支持飞书/微信/Telegram/Discord。

**Architecture:** 直接迁移 flaming-warkhorse 的 channels/ 基建（已验证可用），适配 marneo 数据目录和员工系统。Gateway 以守护进程方式运行（PID 文件存 `~/.marneo/gateway.pid`），渠道配置存 `~/.marneo/config.yaml` 的 `channels:` 节。`marneo gateway start` 后台 fork，`stop` 读 PID 终止，`status` 检查进程是否存活。

**Tech Stack:** Python 3.11+, lark-oapi（飞书）, httpx（微信 iLink），python-telegram-bot（Telegram），discord.py（Discord），asyncio subprocess

**Reference（直接迁移）:**
- `/Users/chamber/code/flaming-warkhorse/flaming_warhorse/channels/` — base.py, manager.py, session_store.py
- `/Users/chamber/code/flaming-warkhorse/flaming_warhorse/channels/adapters/feishu.py` — 飞书 WebSocket
- `/Users/chamber/code/flaming-warkhorse/flaming_warhorse/channels/adapters/wechat.py` — 微信 iLink

---

## Task 1: Gateway 基础层（迁移 + 适配）

**Files:**
- Create: `marneo/gateway/__init__.py`
- Create: `marneo/gateway/base.py`
- Create: `marneo/gateway/session.py`
- Create: `marneo/gateway/manager.py`

### Step 1: 创建 `marneo/gateway/__init__.py`（空）

### Step 2: 创建 `marneo/gateway/base.py`（从 fw 迁移精简）

```python
# marneo/gateway/base.py
"""Base types for marneo gateway adapters."""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChannelMessage:
    platform: str        # "feishu" | "wechat" | "telegram" | "discord"
    chat_id: str         # Platform conversation ID
    user_id: str = ""
    user_name: str = ""
    chat_type: str = "dm"   # "dm" | "group"
    text: str = ""
    msg_id: str = ""         # For dedup
    context_token: str = ""  # WeChat iLink


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
```

### Step 3: 创建 `marneo/gateway/session.py`（从 fw channels/session_store.py 迁移）

```python
# marneo/gateway/session.py
"""Session store: (platform, chat_id) → ChatEngine instance."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

log = logging.getLogger(__name__)
SESSION_TTL = 1800  # 30 min


class _Entry:
    def __init__(self, engine: Any) -> None:
        self.engine = engine
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    def touch(self) -> None:
        self._last = time.monotonic()

    @property
    def expired(self) -> bool:
        return time.monotonic() - self._last > SESSION_TTL


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, _Entry] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(self, platform: str, chat_id: str) -> tuple[Any, asyncio.Lock]:
        key = f"{platform}:{chat_id}"
        async with self._lock:
            self._evict()
            if key not in self._sessions:
                engine = await self._create_engine()
                self._sessions[key] = _Entry(engine)
                log.info("[Session] new %s", key)
            else:
                self._sessions[key].touch()
        entry = self._sessions[key]
        return entry.engine, entry._lock

    async def _create_engine(self) -> Any:
        from marneo.engine.chat import ChatSession
        return ChatSession(system_prompt=(
            "你是一名专注的数字员工，通过 IM 渠道与用户协作。"
            "保持专业、简洁的沟通风格。"
        ))

    def _evict(self) -> None:
        for k in [k for k, e in self._sessions.items() if e.expired]:
            del self._sessions[k]

    @property
    def active_count(self) -> int:
        return len(self._sessions)
```

### Step 4: 创建 `marneo/gateway/manager.py`（从 fw channels/manager.py 精简迁移）

```python
# marneo/gateway/manager.py
"""GatewayManager: orchestrates all channel adapters."""
from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from typing import Any

from marneo.gateway.base import BaseChannelAdapter, ChannelMessage
from marneo.gateway.session import SessionStore

log = logging.getLogger(__name__)
DEDUP_TTL = 60
REPLY_TIMEOUT = 60
MAX_REPLY_LEN = 3000


class _Dedup:
    def __init__(self) -> None:
        self._cache: OrderedDict[str, float] = OrderedDict()

    def seen(self, msg_id: str) -> bool:
        if not msg_id:
            return False
        now = time.monotonic()
        if msg_id in self._cache:
            if now - self._cache[msg_id] < DEDUP_TTL:
                return True
            del self._cache[msg_id]
        self._cache[msg_id] = now
        self._cache.move_to_end(msg_id)
        if len(self._cache) > 2000:
            self._cache.popitem(last=False)
        return False


class GatewayManager:
    def __init__(self) -> None:
        self._adapters: dict[str, BaseChannelAdapter] = {}
        self._sessions = SessionStore()
        self._dedup = _Dedup()
        self._running = False

    def register(self, adapter: BaseChannelAdapter) -> None:
        self._adapters[adapter.platform] = adapter

    async def dispatch(self, msg: ChannelMessage) -> None:
        if msg.msg_id and self._dedup.seen(msg.msg_id):
            return
        if not msg.text.strip():
            return

        engine, lock = await self._sessions.get_or_create(msg.platform, msg.chat_id)
        adapter = self._adapters.get(msg.platform)
        if not adapter:
            return

        async with lock:
            await self._process(msg, engine, adapter)

    async def _process(self, msg: ChannelMessage, engine: Any, adapter: BaseChannelAdapter) -> None:
        parts: list[str] = []
        try:
            async with asyncio.timeout(REPLY_TIMEOUT):
                async for event in engine.send(msg.text):
                    if event.type == "text" and event.content:
                        parts.append(event.content)
        except TimeoutError:
            parts = ["处理超时，请重试。"]
        except Exception as e:
            parts = [f"处理出错：{e}"]

        reply = "".join(parts).strip()
        if not reply:
            return

        # Chunk if too long
        while reply:
            chunk, reply = reply[:MAX_REPLY_LEN], reply[MAX_REPLY_LEN:]
            await adapter.send_reply(msg.chat_id, chunk, context_token=msg.context_token)

    async def start_all(self) -> None:
        """Connect all enabled adapters from config."""
        from marneo.gateway.config import load_channel_configs
        configs = load_channel_configs()
        for platform, config in configs.items():
            if not config.get("enabled", False):
                continue
            adapter = self._adapters.get(platform)
            if not adapter:
                continue
            try:
                ok = await adapter.connect(config)
                log.info("[Gateway] %s: %s", platform, "connected" if ok else "failed")
            except Exception as e:
                log.error("[Gateway] %s connect error: %s", platform, e)

    async def stop_all(self) -> None:
        for adapter in self._adapters.values():
            try:
                await adapter.disconnect()
            except Exception:
                pass

    async def run_forever(self) -> None:
        self._running = True
        await self.start_all()
        log.info("[Gateway] Running. Ctrl+C to stop.")
        try:
            while self._running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop_all()
```

### Step 5: 创建 `marneo/gateway/config.py`（渠道配置读写）

```python
# marneo/gateway/config.py
"""Channel configuration — stored in ~/.marneo/config.yaml under channels:"""
from __future__ import annotations
from typing import Any
import yaml
from marneo.core.paths import get_config_path


def load_channel_configs() -> dict[str, dict[str, Any]]:
    path = get_config_path()
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data.get("channels", {})
    except Exception:
        return {}


def save_channel_config(platform: str, config: dict[str, Any]) -> None:
    path = get_config_path()
    data: dict[str, Any] = {}
    if path.exists():
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            pass
    if "channels" not in data:
        data["channels"] = {}
    data["channels"][platform] = config
    path.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")


def get_channel_config(platform: str) -> dict[str, Any] | None:
    configs = load_channel_configs()
    return configs.get(platform)
```

### Step 6: 冒烟测试

```bash
cd /Users/chamber/code/marneo-agent && python3 -c "
from marneo.gateway.base import BaseChannelAdapter, ChannelMessage
from marneo.gateway.session import SessionStore
from marneo.gateway.manager import GatewayManager, _Dedup
from marneo.gateway.config import load_channel_configs, save_channel_config, get_channel_config

d = _Dedup()
assert not d.seen('m1') and d.seen('m1')
mgr = GatewayManager()
assert mgr._sessions.active_count == 0
print('ALL OK')
"
```

### Step 7: Commit

```bash
cd /Users/chamber/code/marneo-agent
git add marneo/gateway/
git commit -m "feat: add gateway base layer (GatewayManager, SessionStore, config)"
```

---

## Task 2: 飞书 + 微信适配器（从 fw 迁移）

**Files:**
- Create: `marneo/gateway/adapters/__init__.py`
- Create: `marneo/gateway/adapters/feishu.py`
- Create: `marneo/gateway/adapters/wechat.py`

### Step 1: 创建 `marneo/gateway/adapters/__init__.py`（空）

### Step 2: 迁移 `marneo/gateway/adapters/feishu.py`

从 `/Users/chamber/code/flaming-warkhorse/flaming_warhorse/channels/adapters/feishu.py` 迁移，修改：
- 所有 `from flaming_warhorse.` → `from marneo.`
- `from marneo.channels.base` → `from marneo.gateway.base`
- `from marneo.core.config import get_global_claude_path` → 删除（飞书不需要）
- 保留 `FeishuChannelAdapter` 类名，改为继承 `from marneo.gateway.base import BaseChannelAdapter`
- `self._manager.dispatch(msg)` 调用格式保持（manager 接口相同）

关键：Feishu 适配器已经在 flaming-warkhorse 中完整实现并测试，直接迁移。

### Step 3: 迁移 `marneo/gateway/adapters/wechat.py`

从 `/Users/chamber/code/flaming-warkhorse/flaming_warhorse/channels/adapters/wechat.py` 迁移，同样修改 import 路径。

关键：WeChat iLink Bot 适配器已经完整实现，包含 QR 登录、长轮询、context_token 缓存。

数据目录改为 `~/.marneo/wechat/`（原来是 `~/.flaming-warhorse/wechat/`）：
```python
# 在 wechat.py 中
def _sync_buf_path(account_id: str) -> Path:
    from marneo.core.paths import get_marneo_dir
    d = get_marneo_dir() / "wechat"
    d.mkdir(exist_ok=True)
    return d / f"{account_id}.sync_buf"
```

### Step 4: 冒烟测试

```bash
cd /Users/chamber/code/marneo-agent && python3 -c "
from marneo.gateway.adapters.feishu import FeishuChannelAdapter
from marneo.gateway.adapters.wechat import WeChatChannelAdapter, ILINK_BASE_URL
from marneo.gateway.manager import GatewayManager

mgr = GatewayManager()
fa = FeishuChannelAdapter(mgr)
wa = WeChatChannelAdapter(mgr)
assert fa.platform == 'feishu'
assert wa.platform == 'wechat'
assert ILINK_BASE_URL == 'https://ilinkai.weixin.qq.com'

ok, _ = fa.validate_config({'app_id': 'x', 'app_secret': 'y'})
assert ok
ok, _ = wa.validate_config({'account_id': 'a', 'token': 't'})
assert ok
print('ALL OK')
"
```

### Step 5: Commit

```bash
cd /Users/chamber/code/marneo-agent
git add marneo/gateway/adapters/
git commit -m "feat: port Feishu + WeChat adapters to marneo gateway"
```

---

## Task 3: Telegram + Discord 适配器（轻量版）

**Files:**
- Create: `marneo/gateway/adapters/telegram.py`
- Create: `marneo/gateway/adapters/discord_adapter.py`

### Step 1: 创建 `marneo/gateway/adapters/telegram.py`

```python
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
```

### Step 2: 创建 `marneo/gateway/adapters/discord_adapter.py`

```python
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
```

### Step 3: 冒烟测试

```bash
cd /Users/chamber/code/marneo-agent && python3 -c "
from marneo.gateway.adapters.telegram import TelegramAdapter
from marneo.gateway.adapters.discord_adapter import DiscordAdapter
from marneo.gateway.manager import GatewayManager

mgr = GatewayManager()
t = TelegramAdapter(mgr)
d = DiscordAdapter(mgr)
assert t.platform == 'telegram'
assert d.platform == 'discord'
assert not t.validate_config({})[0]
assert t.validate_config({'bot_token': 'x'})[0]
print('ALL OK')
"
```

### Step 4: Commit

```bash
cd /Users/chamber/code/marneo-agent
git add marneo/gateway/adapters/
git commit -m "feat: add Telegram + Discord adapters"
```

---

## Task 4: Gateway CLI（start/stop/status/channels）

**Files:**
- Create: `marneo/cli/gateway_cmd.py`
- Modify: `marneo/cli/app.py`

### Step 1: 创建 `marneo/cli/gateway_cmd.py`

```python
# marneo/cli/gateway_cmd.py
"""marneo gateway — start/stop/status/logs + channel management."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()
gateway_app = typer.Typer(help="IM 网关管理。", invoke_without_command=True)
channels_app = typer.Typer(help="渠道管理。")

# ── Daemon helpers ────────────────────────────────────────────────────────

def _pid_file() -> Path:
    from marneo.core.paths import get_marneo_dir
    return get_marneo_dir() / "gateway.pid"


def _log_file() -> Path:
    from marneo.core.paths import get_marneo_dir
    return get_marneo_dir() / "gateway.log"


def _read_pid() -> int | None:
    p = _pid_file()
    if not p.exists():
        return None
    try:
        pid = int(p.read_text().strip())
        os.kill(pid, 0)  # check if alive
        return pid
    except (ValueError, OSError):
        p.unlink(missing_ok=True)
        return None


def _gateway_runner() -> None:
    """Entry point for background gateway process."""
    import asyncio
    import logging
    logging.basicConfig(
        filename=str(_log_file()),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    from marneo.gateway.manager import GatewayManager
    from marneo.gateway.adapters.feishu import FeishuChannelAdapter
    from marneo.gateway.adapters.wechat import WeChatChannelAdapter
    from marneo.gateway.adapters.telegram import TelegramAdapter
    from marneo.gateway.adapters.discord_adapter import DiscordAdapter

    manager = GatewayManager()
    manager.register(FeishuChannelAdapter(manager))
    manager.register(WeChatChannelAdapter(manager))
    manager.register(TelegramAdapter(manager))
    manager.register(DiscordAdapter(manager))

    asyncio.run(manager.run_forever())


# ── Commands ──────────────────────────────────────────────────────────────

@gateway_app.callback(invoke_without_command=True)
def gateway_default(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        cmd_status()


@gateway_app.command("start")
def cmd_start(
    foreground: bool = typer.Option(False, "--fg", help="前台运行（调试用）"),
) -> None:
    """启动 IM 网关（后台守护进程）。"""
    if _read_pid():
        console.print("[yellow]网关已在运行。[/yellow]")
        raise typer.Exit()

    if foreground:
        console.print(Panel(
            "[bold #FF6611]IM 网关（前台模式）[/bold #FF6611]\n"
            "[dim]Ctrl+C 停止[/dim]",
            border_style="#FF6611", padding=(0, 2),
        ))
        _gateway_runner()
        return

    # Fork to background
    log_path = _log_file()
    pid_path = _pid_file()

    proc = subprocess.Popen(
        [sys.executable, "-c",
         "from marneo.cli.gateway_cmd import _gateway_runner; _gateway_runner()"],
        stdout=open(log_path, "a"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
        cwd=str(Path.home()),
    )
    pid_path.write_text(str(proc.pid))
    console.print(f"[green]✓ 网关已启动 (PID: {proc.pid})[/green]")
    console.print(f"[dim]日志: {log_path}[/dim]")
    console.print(f"[dim]运行 marneo gateway status 查看状态[/dim]")


@gateway_app.command("stop")
def cmd_stop() -> None:
    """停止 IM 网关。"""
    pid = _read_pid()
    if not pid:
        console.print("[dim]网关未运行。[/dim]")
        raise typer.Exit()
    try:
        os.kill(pid, signal.SIGTERM)
        _pid_file().unlink(missing_ok=True)
        console.print(f"[green]✓ 网关已停止 (PID: {pid})[/green]")
    except OSError as e:
        console.print(f"[red]停止失败: {e}[/red]")
        _pid_file().unlink(missing_ok=True)


@gateway_app.command("status")
def cmd_status() -> None:
    """查看网关状态。"""
    pid = _read_pid()
    if pid:
        console.print(f"[green]🟢 网关运行中 (PID: {pid})[/green]")
        log = _log_file()
        if log.exists():
            lines = log.read_text(encoding="utf-8", errors="ignore").splitlines()
            if lines:
                console.print(f"[dim]最新日志: {lines[-1][:80]}[/dim]")
    else:
        console.print("[dim]⚪ 网关未运行[/dim]")
        console.print("[dim]运行 marneo gateway start 启动[/dim]")


@gateway_app.command("logs")
def cmd_logs(n: int = typer.Option(50, "-n", help="显示最近 N 行")) -> None:
    """查看网关日志。"""
    log = _log_file()
    if not log.exists():
        console.print("[dim]暂无日志。[/dim]")
        return
    lines = log.read_text(encoding="utf-8", errors="ignore").splitlines()[-n:]
    for line in lines:
        console.print(f"[dim]{line}[/dim]")


# ── Channels sub-commands ─────────────────────────────────────────────────

KNOWN_PLATFORMS = ["feishu", "wechat", "telegram", "discord"]

PLATFORM_INFO = {
    "feishu": {"label": "飞书 / Feishu", "keys": ["app_id", "app_secret"]},
    "wechat": {"label": "微信 / WeChat (iLink)", "keys": ["account_id", "token"]},
    "telegram": {"label": "Telegram", "keys": ["bot_token"]},
    "discord": {"label": "Discord", "keys": ["bot_token"]},
}


@channels_app.command("list")
def channels_list() -> None:
    """列出所有渠道配置状态。"""
    from marneo.gateway.config import load_channel_configs

    configs = load_channel_configs()
    t = Table(title="IM 渠道", show_header=True, header_style="bold #FFD700")
    t.add_column("平台")
    t.add_column("名称")
    t.add_column("状态", justify="center")
    t.add_column("已配置", justify="center")

    for platform in KNOWN_PLATFORMS:
        info = PLATFORM_INFO[platform]
        config = configs.get(platform, {})
        enabled = config.get("enabled", False)
        has_creds = all(config.get(k) for k in info["keys"])
        status = "[green]✓[/green]" if enabled else "[dim]○[/dim]"
        creds = "[green]✓[/green]" if has_creds else "[red]✗[/red]"
        t.add_row(platform, info["label"], status, creds)

    console.print()
    console.print(t)


@channels_app.command("add")
def channels_add(
    platform: str = typer.Argument(..., help="平台名称 (feishu/wechat/telegram/discord)"),
) -> None:
    """配置渠道（向导模式）。"""
    from prompt_toolkit import prompt as pt_prompt
    from marneo.gateway.config import save_channel_config

    if platform not in KNOWN_PLATFORMS:
        console.print(f"[red]未知平台: {platform}。可用: {', '.join(KNOWN_PLATFORMS)}[/red]")
        raise typer.Exit(1)

    info = PLATFORM_INFO[platform]
    console.print()
    console.print(Panel(
        f"[bold #FF6611]配置 {info['label']}[/bold #FF6611]",
        border_style="#FF6611", padding=(0, 2),
    ))

    config: dict = {"enabled": True}
    for key in info["keys"]:
        try:
            val = pt_prompt(f"  {key}: ", is_password="token" in key or "secret" in key).strip()
            if not val:
                console.print(f"[yellow]{key} 不能为空。[/yellow]")
                raise typer.Exit(1)
            config[key] = val
        except KeyboardInterrupt:
            console.print("\n[dim]已取消。[/dim]")
            raise typer.Exit()

    save_channel_config(platform, config)
    console.print(f"[green]✓ {platform} 配置已保存[/green]")
    console.print(f"[dim]运行 marneo gateway channels test {platform} 验证连接[/dim]")


@channels_app.command("test")
def channels_test(
    platform: str = typer.Argument(..., help="平台名称"),
) -> None:
    """测试渠道连接。"""
    from marneo.gateway.config import get_channel_config
    import asyncio

    config = get_channel_config(platform)
    if not config:
        console.print(f"[red]平台 '{platform}' 未配置。运行 marneo gateway channels add {platform}[/red]")
        raise typer.Exit(1)

    console.print(f"[dim]测试 {platform} 连接...[/dim]")

    async def _test() -> bool:
        if platform == "feishu":
            from marneo.gateway.adapters.feishu import FeishuChannelAdapter
            from marneo.gateway.manager import GatewayManager
            info = await FeishuChannelAdapter(GatewayManager()).probe_bot(
                config.get("app_id", ""), config.get("app_secret", ""),
                config.get("domain", "feishu"),
            )
            return info is not None
        elif platform == "wechat":
            import httpx
            from marneo.gateway.adapters.wechat import ILINK_BASE_URL, _ilink_get_headers
            base = config.get("base_url", ILINK_BASE_URL)
            try:
                async with httpx.AsyncClient(timeout=10) as c:
                    r = await c.get(f"{base}/ilink/bot/getconfig", headers=_ilink_get_headers())
                    return r.status_code in (200, 400)
            except Exception:
                return False
        return False

    import asyncio as _asyncio
    ok = _asyncio.run(_test())
    if ok:
        console.print(f"[green]✓ {platform} 连接成功[/green]")
    else:
        console.print(f"[yellow]⚠ {platform} 连接失败，请检查配置[/yellow]")


@channels_app.command("enable")
def channels_enable(platform: str = typer.Argument(...)) -> None:
    """启用渠道。"""
    from marneo.gateway.config import get_channel_config, save_channel_config
    config = get_channel_config(platform) or {}
    config["enabled"] = True
    save_channel_config(platform, config)
    console.print(f"[green]✓ {platform} 已启用[/green]")


@channels_app.command("disable")
def channels_disable(platform: str = typer.Argument(...)) -> None:
    """禁用渠道。"""
    from marneo.gateway.config import get_channel_config, save_channel_config
    config = get_channel_config(platform) or {}
    config["enabled"] = False
    save_channel_config(platform, config)
    console.print(f"[dim]{platform} 已禁用[/dim]")
```

### Step 2: 注册到 app.py

```python
from marneo.cli.gateway_cmd import gateway_app, channels_app
app.add_typer(gateway_app, name="gateway")
app.add_typer(channels_app, name="gateway channels", no_default_command=True)
# 更简洁的方式：把 channels_app 嵌入 gateway_app
```

实际上 typer 嵌套方式：在 `gateway_cmd.py` 中最后加：
```python
gateway_app.add_typer(channels_app, name="channels")
```

并在 `app.py` 只注册 `gateway_app`：
```python
from marneo.cli.gateway_cmd import gateway_app
app.add_typer(gateway_app, name="gateway")
```

### Step 3: 测试

```bash
cd /Users/chamber/code/marneo-agent
python3 -c "from marneo.cli.gateway_cmd import gateway_app, channels_app; print('OK')"
marneo gateway --help
marneo gateway channels --help
```

### Step 4: Commit

```bash
git add marneo/cli/gateway_cmd.py marneo/cli/app.py
git commit -m "feat: add marneo gateway CLI (start/stop/status/logs + channels)"
```

---

## Task 5: 最终集成验证

### Step 1: 全量测试

```bash
cd /Users/chamber/code/marneo-agent && python3 -c "
print('=== Marneo Phase 4 Integration Checks ===')

from marneo.gateway.base import BaseChannelAdapter, ChannelMessage
from marneo.gateway.session import SessionStore
from marneo.gateway.manager import GatewayManager, _Dedup
from marneo.gateway.config import load_channel_configs, save_channel_config, get_channel_config
from marneo.gateway.adapters.feishu import FeishuChannelAdapter
from marneo.gateway.adapters.wechat import WeChatChannelAdapter, ILINK_BASE_URL
from marneo.gateway.adapters.telegram import TelegramAdapter
from marneo.gateway.adapters.discord_adapter import DiscordAdapter
from marneo.cli.gateway_cmd import gateway_app, channels_app, _read_pid, _pid_file
print('✓ All imports OK')

# Dedup
d = _Dedup()
assert not d.seen('m1') and d.seen('m1')
print('✓ Dedup OK')

# Manager
mgr = GatewayManager()
mgr.register(FeishuChannelAdapter(mgr))
mgr.register(WeChatChannelAdapter(mgr))
mgr.register(TelegramAdapter(mgr))
mgr.register(DiscordAdapter(mgr))
assert set(mgr._adapters.keys()) == {'feishu','wechat','telegram','discord'}
print('✓ Manager + adapters OK')

# Config
save_channel_config('feishu', {'app_id': 'test', 'enabled': False})
cfg = get_channel_config('feishu')
assert cfg and cfg['app_id'] == 'test'
print('✓ Channel config OK')

# Adapter validation
fa = FeishuChannelAdapter(mgr)
assert fa.validate_config({'app_id':'x','app_secret':'y'})[0]
wa = WeChatChannelAdapter(mgr)
assert wa.validate_config({'account_id':'a','token':'t'})[0]
assert ILINK_BASE_URL == 'https://ilinkai.weixin.qq.com'
print('✓ Adapter validation OK')

# PID helpers
assert _read_pid() is None  # gateway not running
print('✓ PID helpers OK')

import subprocess
for cmd in [['marneo','gateway','--help'],['marneo','gateway','status'],['marneo','gateway','channels','list']]:
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == 0, f'{cmd}: {r.stderr[:60]}'
print('✓ CLI commands OK')

print()
print('ALL CHECKS PASSED')
"
```

### Step 2: 清理测试配置

```bash
python3 -c "
from marneo.gateway.config import save_channel_config
save_channel_config('feishu', {'app_id': '', 'enabled': False})
print('cleanup done')
"
```

### Step 3: 最终提交

```bash
cd /Users/chamber/code/marneo-agent
git log --oneline -5
```
