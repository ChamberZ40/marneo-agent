# marneo/gateway/adapters/wechat.py
"""WeChat channel adapter via Tencent iLink Bot API.

Protocol:
  - Long-poll getupdates (35s timeout) for inbound messages
  - sync_buf persisted to disk for restart continuity
  - context_token must be included in every reply (per peer)
  - Exponential backoff on errors (1s → 2s → 4s → ... → 60s)

Setup requirements:
  - account_id: iLink Bot account ID
  - token: iLink Bot token
  (Obtained via QR login: qr_login())
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

import httpx

from marneo.gateway.base import BaseChannelAdapter, ChannelMessage
from marneo.core.paths import get_marneo_dir

log = logging.getLogger(__name__)

ILINK_BASE_URL = "https://ilinkai.weixin.qq.com"
EP_GET_UPDATES = "ilink/bot/getupdates"
EP_SEND_MESSAGE = "ilink/bot/sendmessage"
EP_GET_CONFIG = "ilink/bot/getconfig"
EP_GET_BOT_QR = "ilink/bot/get_bot_qrcode"
EP_GET_QR_STATUS = "ilink/bot/get_qrcode_status"

ILINK_APP_ID = "bot"
ILINK_APP_CLIENT_VERSION = (2 << 16) | (2 << 8) | 0  # 2.2.0

POLL_TIMEOUT_MS = 35000
QR_POLL_INTERVAL = 3
QR_TIMEOUT = 480       # 8 minutes — same as Hermes
MAX_BACKOFF = 60


def _ilink_get_headers() -> dict[str, str]:
    """Headers for unauthenticated GET requests (QR login)."""
    return {
        "iLink-App-Id": ILINK_APP_ID,
        "iLink-App-ClientVersion": str(ILINK_APP_CLIENT_VERSION),
    }


def _ilink_headers(token: str) -> dict[str, str]:
    """Headers for authenticated POST requests."""
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "iLink-App-Id": ILINK_APP_ID,
        "iLink-App-ClientVersion": str(ILINK_APP_CLIENT_VERSION),
    }


def _sync_buf_path(account_id: str) -> Path:
    d = get_marneo_dir() / "wechat"
    d.mkdir(exist_ok=True)
    return d / f"{account_id}.sync_buf"


def _load_sync_buf(account_id: str) -> str:
    p = _sync_buf_path(account_id)
    return p.read_text(encoding="utf-8").strip() if p.exists() else ""


def _save_sync_buf(account_id: str, buf: str) -> None:
    _sync_buf_path(account_id).write_text(buf, encoding="utf-8")


def _context_token_path(account_id: str) -> Path:
    d = get_marneo_dir() / "wechat"
    d.mkdir(exist_ok=True)
    return d / f"{account_id}.context_tokens.json"


def _load_context_tokens(account_id: str) -> dict[str, str]:
    p = _context_token_path(account_id)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_context_token(account_id: str, peer_id: str, token: str) -> None:
    tokens = _load_context_tokens(account_id)
    tokens[peer_id] = token
    _context_token_path(account_id).write_text(
        json.dumps(tokens, ensure_ascii=False), encoding="utf-8"
    )


class WeChatChannelAdapter(BaseChannelAdapter):
    """WeChat adapter via Tencent iLink Bot API."""

    def __init__(self, manager: Any) -> None:
        super().__init__("wechat")
        self._manager = manager
        self._account_id = ""
        self._token = ""
        self._base_url = ILINK_BASE_URL
        self._poll_task: asyncio.Task | None = None
        self._seen_ids: set[str] = set()  # in-memory dedup

    def validate_config(self, config: dict[str, str]) -> tuple[bool, str]:
        if not config.get("account_id"):
            return False, "account_id is required"
        if not config.get("token"):
            return False, "token is required"
        return True, ""

    async def connect(self, config: dict[str, str]) -> bool:
        ok, err = self.validate_config(config)
        if not ok:
            log.error("[WeChat] Config error: %s", err)
            return False

        self._account_id = config["account_id"]
        self._token = config["token"]
        self._base_url = config.get("base_url", ILINK_BASE_URL).rstrip("/")

        # Verify credentials
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{self._base_url}/{EP_GET_CONFIG}",
                    json={},
                    headers=_ilink_headers(self._token),
                )
                if resp.status_code not in (200, 201):
                    log.error("[WeChat] Auth failed: %s", resp.status_code)
                    return False
        except Exception as exc:
            log.error("[WeChat] Connect check failed: %s", exc)
            return False

        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        log.info("[WeChat] Connected (account=%s)", self._account_id[:8])
        return True

    async def _poll_loop(self) -> None:
        """Long-poll getupdates with exponential backoff on errors."""
        sync_buf = _load_sync_buf(self._account_id)
        backoff = 1.0

        async with httpx.AsyncClient(timeout=POLL_TIMEOUT_MS / 1000 + 5) as client:
            while self._running:
                try:
                    resp = await client.post(
                        f"{self._base_url}/{EP_GET_UPDATES}",
                        json={"sync_buf": sync_buf, "timeout": POLL_TIMEOUT_MS},
                        headers=_ilink_headers(self._token),
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        new_buf = data.get("sync_buf", sync_buf)
                        if new_buf != sync_buf:
                            sync_buf = new_buf
                            _save_sync_buf(self._account_id, sync_buf)
                        backoff = 1.0  # reset on success
                        for msg in data.get("list", []):
                            await self._handle_msg(msg)
                    else:
                        log.warning("[WeChat] getupdates status: %s", resp.status_code)
                        await asyncio.sleep(backoff)
                        backoff = min(backoff * 2, MAX_BACKOFF)
                except asyncio.CancelledError:
                    break
                except Exception as exc:
                    log.warning("[WeChat] Poll error: %s", exc)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, MAX_BACKOFF)

    async def _handle_msg(self, msg: dict) -> None:
        """Process one inbound message from getupdates."""
        msg_id = str(msg.get("msgid") or "")
        if msg_id and msg_id in self._seen_ids:
            return
        if msg_id:
            self._seen_ids.add(msg_id)
            if len(self._seen_ids) > 5000:
                self._seen_ids.clear()

        # Extract text
        items = msg.get("message_item") or []
        if isinstance(items, dict):
            items = [items]
        text = ""
        for item in items:
            if item.get("type") == 1:  # text type
                text = (item.get("text_item") or {}).get("text", "").strip()
                break
        if not text:
            return

        peer_id = str(msg.get("ilink_user_id") or "")
        context_token = str(msg.get("context_token") or "")

        # Persist context_token for this peer
        if context_token and peer_id:
            _save_context_token(self._account_id, peer_id, context_token)

        channel_msg = ChannelMessage(
            platform="wechat",
            chat_id=peer_id,
            chat_type="dm",
            user_id=peer_id,
            text=text,
            msg_id=msg_id,
            context_token=context_token,
        )
        await self._manager.dispatch(channel_msg)

    async def send_reply(self, chat_id: str, text: str, **kwargs: Any) -> bool:
        """Send reply to a WeChat peer. Uses context_token if available."""
        context_token = kwargs.get("context_token") or ""
        if not context_token:
            tokens = _load_context_tokens(self._account_id)
            context_token = tokens.get(chat_id, "")

        payload: dict[str, Any] = {
            "ilink_user_id": chat_id,
            "message_item": [{"type": 1, "text_item": {"text": text}}],
        }
        if context_token:
            payload["context_token"] = context_token

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{self._base_url}/{EP_SEND_MESSAGE}",
                    json=payload,
                    headers=_ilink_headers(self._token),
                )
                if resp.status_code not in (200, 201):
                    log.error("[WeChat] Send failed: %s", resp.status_code)
                    return False
                return True
        except Exception as exc:
            log.error("[WeChat] send_reply error: %s", exc, exc_info=True)
            return False

    async def disconnect(self) -> None:
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        log.info("[WeChat] Disconnected")


async def qr_login(base_url: str = ILINK_BASE_URL) -> dict | None:
    """Run iLink Bot QR login flow — exactly mirrors Hermes weixin.py.

    No prior application needed. Just scan with WeChat.
    Uses GET requests with only iLink-App-Id headers (no Authorization).
    """
    from rich.console import Console
    console = Console()

    try:
        # Use longer timeout for long-poll during QR wait
        async with httpx.AsyncClient(timeout=60) as client:

            # ── Step 1: Get QR code (GET, no auth) ────────────────────────
            resp = await client.get(
                f"{base_url.rstrip('/')}/{EP_GET_BOT_QR}?bot_type=3",
                headers=_ilink_get_headers(),
            )
            if resp.status_code != 200:
                console.print(f"[red]获取 QR 码失败: {resp.status_code} {resp.text[:100]}[/red]")
                return None

            data = resp.json()
            qrcode_value = str(data.get("qrcode") or "")
            qrcode_img = str(data.get("qrcode_img_content") or "")

            if not qrcode_value:
                console.print("[red]QR 码数据获取失败，请检查网络连接。[/red]")
                return None

            # ── Display QR code ────────────────────────────────────────────
            console.print()
            console.print("[bold #FFD700]请用微信扫描以下二维码：[/bold #FFD700]")
            if qrcode_img:
                console.print(f"[dim]{qrcode_img}[/dim]")
            try:
                import qrcode as _qr
                import io
                q = _qr.QRCode()
                q.add_data(qrcode_img or qrcode_value)
                q.make(fit=True)
                buf = io.StringIO()
                q.print_ascii(invert=True, out=buf)
                print(buf.getvalue())
            except ImportError:
                console.print("[dim](安装 qrcode 库可在终端显示二维码: pip install qrcode)[/dim]")
            except Exception:
                pass

            console.print("[dim]等待扫码...[/dim]")

            # ── Step 2: Poll status (GET, no auth) ────────────────────────
            current_base = base_url
            refresh_count = 0
            deadline = time.monotonic() + QR_TIMEOUT

            while time.monotonic() < deadline:
                await asyncio.sleep(QR_POLL_INTERVAL)
                try:
                    sr = await client.get(
                        f"{current_base.rstrip('/')}/{EP_GET_QR_STATUS}?qrcode={qrcode_value}",
                        headers=_ilink_get_headers(),
                        timeout=15,
                    )
                    if sr.status_code != 200:
                        continue
                    sd = sr.json()
                except Exception:
                    continue

                status = str(sd.get("status") or "wait")

                if status == "wait":
                    print(".", end="", flush=True)

                elif status == "scaned":
                    print("\n已扫码，请在微信里确认...")

                elif status == "scaned_but_redirect":
                    # Tencent may redirect to a regional server
                    redirect_host = str(sd.get("redirect_host") or "")
                    if redirect_host:
                        current_base = f"https://{redirect_host}"

                elif status == "expired":
                    refresh_count += 1
                    if refresh_count > 3:
                        console.print("\n[yellow]二维码多次过期，请重新运行 fw channel setup。[/yellow]")
                        return None
                    console.print(f"\n[dim]二维码已过期，刷新中... ({refresh_count}/3)[/dim]")
                    try:
                        rr = await client.get(
                            f"{base_url.rstrip('/')}/{EP_GET_BOT_QR}?bot_type=3",
                            headers=_ilink_get_headers(),
                        )
                        rd = rr.json()
                        qrcode_value = str(rd.get("qrcode") or "")
                        qrcode_img = str(rd.get("qrcode_img_content") or "")
                        if qrcode_img:
                            console.print(f"[dim]{qrcode_img}[/dim]")
                    except Exception:
                        pass

                elif status == "confirmed":
                    account_id = str(sd.get("ilink_bot_id") or "")
                    token = str(sd.get("bot_token") or "")
                    new_base = str(sd.get("baseurl") or current_base)
                    user_id = str(sd.get("ilink_user_id") or "")
                    if not account_id or not token:
                        console.print("[red]登录确认但凭证不完整，请重试。[/red]")
                        return None
                    print()
                    console.print(f"[green]✓ 微信登录成功！account_id={account_id[:8]}...[/green]")
                    return {
                        "account_id": account_id,
                        "token": token,
                        "base_url": new_base,
                        "user_id": user_id,
                    }

        console.print("\n[yellow]登录超时，请重新运行 fw channel setup。[/yellow]")
        return None

    except Exception as exc:
        log.error("[WeChat] qr_login error: %s", exc, exc_info=True)
        console.print(f"[red]QR 登录出错: {exc}[/red]")
        return None
