# Multimodal File Messages Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** When a user sends an image or file via Feishu, download it and pass it as a multimodal content block to the LLM so the employee can actually read/compare documents.

**Architecture:** Add `attachments: list[dict]` to `ChannelMessage`. The Feishu adapter downloads files from Feishu using `im.v1.message_resource.get()` (hermes-agent pattern) and attaches raw bytes + metadata. `ChatSession.send()` builds multimodal content blocks (OpenAI image_url for openai-compatible, Anthropic content blocks for anthropic-compatible). Supported: images (jpg/png/gif/webp), PDF, txt/md/json (text inject). DOCX falls back to placeholder until a future task.

**Tech Stack:** Python 3.11+, lark-oapi (Feishu SDK), httpx, base64, existing ChatSession/ChannelMessage. No new dependencies needed.

**Reference implementations:**
- Download pattern: `hermes-agent/gateway/platforms/feishu.py` lines 3036–3175
- OpenAI content blocks: `{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}`
- Anthropic content blocks: `{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "..."}}`
- Anthropic PDF: `{"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": "..."}}`

---

## Task 1: Add `attachments` to ChannelMessage

**Files:**
- Modify: `marneo/gateway/base.py`
- Modify: `tests/gateway/test_manager.py` (smoke check)

### Step 1: Write failing test

```python
# In tests/gateway/test_manager.py, add:
def test_channel_message_has_attachments_field():
    from marneo.gateway.base import ChannelMessage
    msg = ChannelMessage(platform="test", chat_id="c1", text="hello")
    assert hasattr(msg, "attachments")
    assert msg.attachments == []

def test_channel_message_attachments_with_data():
    from marneo.gateway.base import ChannelMessage
    att = {"data": b"bytes", "media_type": "image/jpeg", "filename": "photo.jpg"}
    msg = ChannelMessage(platform="test", chat_id="c1", text="look", attachments=[att])
    assert len(msg.attachments) == 1
    assert msg.attachments[0]["media_type"] == "image/jpeg"
```

### Step 2: Run — expect FAIL
```bash
cd /Users/chamber/code/marneo-agent && pytest tests/gateway/test_manager.py::test_channel_message_has_attachments_field tests/gateway/test_manager.py::test_channel_message_attachments_with_data -v 2>&1 | tail -10
```
Expected: AttributeError / AssertionError

### Step 3: Modify `marneo/gateway/base.py`

Current `ChannelMessage`:
```python
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
```

Add `attachments` field:
```python
from __future__ import annotations
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
    # Each attachment: {"data": bytes, "media_type": str, "filename": str}
    attachments: list[dict[str, Any]] = field(default_factory=list)
```

Read the full current `base.py` first, then add the `attachments` field and necessary imports.

### Step 4: Run — expect PASS
```bash
pytest tests/gateway/test_manager.py -v -q
```
Expected: all pass

### Step 5: Commit
```bash
git add marneo/gateway/base.py tests/gateway/test_manager.py
git commit -m "feat(gateway): add attachments field to ChannelMessage"
```

---

## Task 2: Feishu adapter — download file/image and attach to ChannelMessage

**Files:**
- Modify: `marneo/gateway/adapters/feishu.py`
- Create: `tests/gateway/test_feishu_download.py`

### Step 1: Write failing tests

```python
# tests/gateway/test_feishu_download.py
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from marneo.gateway.adapters.feishu import FeishuChannelAdapter


def _make_adapter():
    manager = MagicMock()
    adapter = FeishuChannelAdapter(manager, employee_name="test")
    adapter._app_id = "app1"
    adapter._app_secret = "secret1"
    adapter._domain = "feishu"
    return adapter


@pytest.mark.asyncio
async def test_download_resource_returns_bytes_and_media_type():
    """_download_feishu_resource returns (bytes, media_type, filename) on success."""
    adapter = _make_adapter()

    mock_response = MagicMock()
    mock_response.success.return_value = True
    mock_file = MagicMock()
    mock_file.getvalue.return_value = b"fake-image-bytes"
    mock_response.file = mock_file
    mock_response.raw = MagicMock()
    mock_response.raw.headers = {"Content-Type": "image/jpeg"}
    mock_response.file_name = "photo.jpg"

    mock_client = MagicMock()
    mock_client.im.v1.message_resource.get.return_value = mock_response

    with patch("lark_oapi.Client") as MockClient:
        MockClient.return_value = mock_client
        MockClient.builder.return_value.app_id.return_value.app_secret.return_value.domain.return_value.build.return_value = mock_client
        data, media_type, filename = await adapter._download_feishu_resource(
            message_id="msg1", file_key="fk1", resource_type="image"
        )

    assert data == b"fake-image-bytes"
    assert "image" in media_type
    assert filename == "photo.jpg"


@pytest.mark.asyncio
async def test_download_resource_returns_empty_on_failure():
    adapter = _make_adapter()

    mock_response = MagicMock()
    mock_response.success.return_value = False
    mock_response.code = 403
    mock_response.msg = "forbidden"

    mock_client = MagicMock()
    mock_client.im.v1.message_resource.get.return_value = mock_response

    with patch("lark_oapi.Client") as MockClient:
        MockClient.builder.return_value.app_id.return_value.app_secret.return_value.domain.return_value.build.return_value = mock_client
        data, media_type, filename = await adapter._download_feishu_resource(
            message_id="msg1", file_key="fk1", resource_type="file"
        )

    assert data == b""
    assert media_type == ""
```

### Step 2: Run — expect FAIL
```bash
pytest tests/gateway/test_feishu_download.py -v 2>&1 | tail -10
```

### Step 3: Add `_download_feishu_resource()` to `FeishuChannelAdapter`

Add after `_build_lark_client()` in `marneo/gateway/adapters/feishu.py`:

```python
    async def _download_feishu_resource(
        self,
        *,
        message_id: str,
        file_key: str,
        resource_type: str,
        fallback_filename: str = "",
    ) -> tuple[bytes, str, str]:
        """Download a Feishu message resource. Returns (data, media_type, filename).

        Ported from hermes-agent._download_feishu_message_resource.
        resource_type: "image", "file", "audio", "media"
        """
        import mimetypes as _mimetypes
        if not message_id or not file_key or not self._app_id:
            return b"", "", ""
        try:
            import lark_oapi as lark
            from lark_oapi.api.im.v1 import GetMessageResourceRequest

            lark_domain = lark.LARK_DOMAIN if self._domain == "lark" else lark.FEISHU_DOMAIN
            client = (
                lark.Client.builder()
                .app_id(self._app_id)
                .app_secret(self._app_secret)
                .domain(lark_domain)
                .build()
            )
            request = (
                GetMessageResourceRequest.builder()
                .message_id(message_id)
                .file_key(file_key)
                .type(resource_type)
                .build()
            )
            resp = await asyncio.to_thread(client.im.v1.message_resource.get, request)
            if not resp or not resp.success():
                log.debug("[Feishu] Resource download failed %s/%s: code=%s",
                          message_id, file_key, getattr(resp, "code", "?"))
                return b"", "", ""

            # Read binary data (BytesIO or file-like)
            file_obj = getattr(resp, "file", None)
            if file_obj is None:
                return b"", "", ""
            data = bytes(file_obj.getvalue()) if hasattr(file_obj, "getvalue") else bytes(file_obj.read())
            if not data:
                return b"", "", ""

            # Detect media type from Content-Type header
            raw = getattr(resp, "raw", None)
            headers = getattr(raw, "headers", {}) or {}
            ct = str(headers.get("Content-Type") or headers.get("content-type") or "").split(";")[0].strip().lower()

            filename = getattr(resp, "file_name", None) or fallback_filename or file_key
            if not ct:
                ct = _mimetypes.guess_type(filename)[0] or "application/octet-stream"

            return data, ct, filename

        except Exception as exc:
            log.warning("[Feishu] _download_feishu_resource error: %s", exc)
            return b"", "", ""
```

### Step 4: Update `_extract_text` and `_handle_message_event_data`

In `_extract_text`, change image and file handling to return a sentinel `None` with special marker, OR keep returning placeholder text but also trigger download in `_handle_message_event_data`.

The cleanest approach: in `_handle_message_event_data`, after building `channel_msg`, check the message type and download attachments asynchronously before dispatching:

Replace the current `_handle_message_event_data` flow for image/file types. After `text = self._extract_text(...)`:

```python
    # Download attachments for image/file messages
    attachments: list[dict] = []
    if msg_type == "image":
        image_key = content.get("image_key", "")
        if image_key and msg_id:
            data, media_type, filename = await self._download_feishu_resource(
                message_id=msg_id, file_key=image_key, resource_type="image",
                fallback_filename=f"{image_key}.jpg",
            )
            if data:
                attachments.append({"data": data, "media_type": media_type, "filename": filename})
                text = ""  # LLM will see the image directly

    elif msg_type == "file":
        file_key = content.get("file_key", "")
        file_name = content.get("file_name", "") or file_key
        if file_key and msg_id:
            data, media_type, filename = await self._download_feishu_resource(
                message_id=msg_id, file_key=file_key, resource_type="file",
                fallback_filename=file_name,
            )
            if data:
                attachments.append({"data": data, "media_type": media_type, "filename": filename})
                text = f"[已收到文件: {filename}]"

    channel_msg = ChannelMessage(
        platform=self.platform,
        chat_id=chat_id,
        chat_type="group" if chat_type == "group" else "dm",
        user_id=sender_id,
        text=text,
        msg_id=msg_id,
        attachments=attachments,
    )
```

Also update `_extract_text` so `"image"` and `"file"` types return a default text (not `None`) so they don't get filtered out:
```python
    if msg_type == "image":
        return content.get("text", "") or "[图片]"  # text may contain caption
    if msg_type == "file":
        return content.get("file_name", "") or "[文件]"
```

### Step 5: Run tests — expect PASS
```bash
pytest tests/gateway/test_feishu_download.py tests/gateway/ -v -q
```

### Step 6: Commit
```bash
git add marneo/gateway/adapters/feishu.py marneo/gateway/base.py tests/gateway/test_feishu_download.py
git commit -m "feat(feishu): download image/file attachments from Feishu messages"
```

---

## Task 3: ChatSession — build multimodal content blocks

**Files:**
- Modify: `marneo/engine/chat.py`
- Create: `tests/engine/test_multimodal.py`

### Step 1: Write failing tests

```python
# tests/engine/test_multimodal.py
import base64
import json
import pytest
from marneo.engine.chat import _build_content_blocks


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def test_build_content_blocks_text_only():
    blocks = _build_content_blocks(text="hello", attachments=[], protocol="openai-compatible")
    # Plain text → just a string, not a list
    assert blocks == "hello"


def test_build_content_blocks_image_openai():
    att = {"data": b"\xff\xd8\xff", "media_type": "image/jpeg", "filename": "photo.jpg"}
    blocks = _build_content_blocks(text="what's this?", attachments=[att], protocol="openai-compatible")
    assert isinstance(blocks, list)
    text_blocks = [b for b in blocks if b.get("type") == "text"]
    image_blocks = [b for b in blocks if b.get("type") == "image_url"]
    assert len(text_blocks) == 1
    assert text_blocks[0]["text"] == "what's this?"
    assert len(image_blocks) == 1
    assert "data:image/jpeg;base64," in image_blocks[0]["image_url"]["url"]


def test_build_content_blocks_image_anthropic():
    att = {"data": b"\xff\xd8\xff", "media_type": "image/jpeg", "filename": "photo.jpg"}
    blocks = _build_content_blocks(text="describe", attachments=[att], protocol="anthropic-compatible")
    assert isinstance(blocks, list)
    image_blocks = [b for b in blocks if b.get("type") == "image"]
    assert len(image_blocks) == 1
    assert image_blocks[0]["source"]["type"] == "base64"
    assert image_blocks[0]["source"]["media_type"] == "image/jpeg"


def test_build_content_blocks_pdf_anthropic():
    att = {"data": b"%PDF-1.4", "media_type": "application/pdf", "filename": "doc.pdf"}
    blocks = _build_content_blocks(text="summarize", attachments=[att], protocol="anthropic-compatible")
    doc_blocks = [b for b in blocks if b.get("type") == "document"]
    assert len(doc_blocks) == 1
    assert doc_blocks[0]["source"]["media_type"] == "application/pdf"


def test_build_content_blocks_pdf_openai_falls_back_to_text():
    """PDF with OpenAI protocol → inject text notice since no native PDF support."""
    att = {"data": b"%PDF-1.4 content", "media_type": "application/pdf", "filename": "report.pdf"}
    blocks = _build_content_blocks(text="compare", attachments=[att], protocol="openai-compatible")
    # Should still be a list with text content mentioning the PDF
    if isinstance(blocks, list):
        all_text = " ".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        assert "report.pdf" in all_text or "PDF" in all_text
    else:
        assert "report.pdf" in blocks or "PDF" in blocks


def test_build_content_blocks_text_file_injected():
    """Plain text files injected directly into text."""
    att = {"data": b"name,age\nAlice,30", "media_type": "text/plain", "filename": "data.csv"}
    blocks = _build_content_blocks(text="analyze this", attachments=[att], protocol="openai-compatible")
    if isinstance(blocks, list):
        all_text = " ".join(b.get("text", "") for b in blocks if b.get("type") == "text")
    else:
        all_text = blocks
    assert "Alice" in all_text
    assert "data.csv" in all_text
```

### Step 2: Run — expect FAIL
```bash
pytest tests/engine/test_multimodal.py -v 2>&1 | tail -10
```

### Step 3: Add `_build_content_blocks()` module-level function to `marneo/engine/chat.py`

Add before the `ChatSession` class definition:

```python
_MAX_TEXT_INJECT = 200_000  # 200 KB for text file injection


def _build_content_blocks(
    text: str,
    attachments: list[dict],
    protocol: str,
) -> "str | list[dict]":
    """Build LLM content from text + attachments.

    Returns plain string when no attachments.
    Returns list of content blocks when attachments present.

    OpenAI format:  [{"type": "text", "text": ...}, {"type": "image_url", ...}]
    Anthropic format: [{"type": "text", "text": ...}, {"type": "image", "source": {...}}]
    """
    import base64 as _b64

    if not attachments:
        return text

    blocks: list[dict] = []
    is_anthropic = protocol == "anthropic-compatible"

    for att in attachments:
        data: bytes = att.get("data", b"")
        media_type: str = att.get("media_type", "")
        filename: str = att.get("filename", "file")

        if not data:
            continue

        b64 = _b64.b64encode(data).decode()

        # ── Plain text files → inject as text ─────────────────────────────
        if media_type.startswith("text/") or media_type in ("application/json",):
            try:
                file_text = data.decode("utf-8", errors="replace")
                if len(file_text) > _MAX_TEXT_INJECT:
                    file_text = file_text[:_MAX_TEXT_INJECT] + "\n... (truncated)"
                blocks.append({"type": "text", "text": f"[Content of {filename}]:\n{file_text}"})
            except Exception:
                blocks.append({"type": "text", "text": f"[文件: {filename}]"})
            continue

        # ── Images ────────────────────────────────────────────────────────
        if media_type.startswith("image/"):
            if is_anthropic:
                blocks.append({
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": b64},
                })
            else:
                blocks.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{media_type};base64,{b64}"},
                })
            continue

        # ── PDF ───────────────────────────────────────────────────────────
        if media_type == "application/pdf":
            if is_anthropic:
                blocks.append({
                    "type": "document",
                    "source": {"type": "base64", "media_type": "application/pdf", "data": b64},
                })
            else:
                # OpenAI/MiniMax: no native PDF block — inject notice + first 5KB of bytes as hint
                blocks.append({
                    "type": "text",
                    "text": f"[PDF文件: {filename}，共 {len(data)} 字节。请注意这是一个PDF文档。]",
                })
            continue

        # ── Other binary (DOCX, XLSX, etc.) ──────────────────────────────
        blocks.append({"type": "text", "text": f"[文件: {filename} ({media_type})]"})

    # Prepend user text block if any
    if text.strip():
        blocks.insert(0, {"type": "text", "text": text})
    elif not blocks:
        return text  # nothing at all

    return blocks
```

### Step 4: Update `ChatSession.send()` to accept and use attachments

Modify the `send()` signature and message building:

```python
    async def send(
        self,
        user_text: str,
        attachments: list[dict] | None = None,
    ) -> AsyncIterator[ChatEvent]:
        """Stream events for a user message. attachments: list of {data, media_type, filename}."""
        provider = resolve_provider()

        # Build content: string or multimodal blocks
        content = _build_content_blocks(
            text=user_text,
            attachments=attachments or [],
            protocol=provider.protocol,
        )
        self.messages.append({"role": "user", "content": content})
        collected = ""
        try:
            if provider.protocol == "anthropic-compatible":
                async for event in self._call_anthropic(provider):
                    if event.type == "text" and event.content:
                        collected += event.content
                    yield event
            else:
                async for event in self._call_openai(provider):
                    if event.type == "text" and event.content:
                        collected += event.content
                    yield event
            if collected:
                self.messages.append({"role": "assistant", "content": collected})
        except Exception as exc:
            log.error("Chat error: %s", exc)
            yield ChatEvent(type="error", content=str(exc))
        yield ChatEvent(type="done")
```

### Step 5: Update `send_with_tools()` to forward attachments

In `send_with_tools()`, add `attachments` parameter and pass to first `self.send()` call:

```python
    async def send_with_tools(
        self,
        user_text: str,
        registry: Any = None,
        max_iterations: int = 20,
        attachments: list[dict] | None = None,
    ) -> AsyncIterator[ChatEvent]:
```

And in the loop, change the first `self.send(call_text)` to pass attachments:
```python
            # Only pass attachments on first iteration
            iter_attachments = attachments if _iteration == 0 and not pending_tool_results_injected else None
            async for event in self.send(call_text, attachments=iter_attachments):
```

Track whether we've passed attachments with a flag `pending_tool_results_injected = False`, set to `True` after first iteration.

### Step 6: Run tests — expect PASS
```bash
pytest tests/engine/test_multimodal.py tests/engine/ -v -q
```
Expected: all pass

### Step 7: Commit
```bash
git add marneo/engine/chat.py tests/engine/test_multimodal.py
git commit -m "feat(engine): add multimodal content blocks (image/pdf/text file) to ChatSession"
```

---

## Task 4: Wire attachments through GatewayManager

**Files:**
- Modify: `marneo/gateway/manager.py` — pass `msg.attachments` to `send_with_tools()`
- Create: `tests/gateway/test_multimodal_integration.py`

### Step 1: Write failing test

```python
# tests/gateway/test_multimodal_integration.py
import pytest
from unittest.mock import patch, MagicMock
from marneo.gateway.manager import GatewayManager
from marneo.gateway.base import ChannelMessage, BaseChannelAdapter
from marneo.engine.chat import ChatSession, ChatEvent


class FakeAdapter(BaseChannelAdapter):
    def __init__(self):
        super().__init__("fake")
        self.replies = []
        self._running = True
    async def connect(self, config): return True
    async def disconnect(self): pass
    async def send_reply(self, chat_id, text, **kw):
        self.replies.append(text)
        return True


@pytest.mark.asyncio
async def test_process_passes_attachments_to_send_with_tools():
    """Attachments from ChannelMessage are forwarded to send_with_tools."""
    manager = GatewayManager()
    adapter = FakeAdapter()
    manager.register(adapter)

    att = {"data": b"\xff\xd8\xff", "media_type": "image/jpeg", "filename": "photo.jpg"}
    msg = ChannelMessage(platform="fake", chat_id="c1", text="describe this", attachments=[att])

    received_attachments = []

    async def fake_send_with_tools(text, registry=None, max_iterations=20, attachments=None):
        received_attachments.extend(attachments or [])
        yield ChatEvent(type="text", content="it's a photo")
        yield ChatEvent(type="done")

    from marneo.gateway.session import SessionStore
    store = SessionStore()
    engine, lock = await store.get_or_create("fake", "c1")

    with patch.object(engine, "send_with_tools", side_effect=fake_send_with_tools):
        async with lock:
            await manager._process(msg, engine, adapter)

    assert len(received_attachments) == 1
    assert received_attachments[0]["media_type"] == "image/jpeg"
    assert adapter.replies == ["it's a photo"]
```

### Step 2: Run — expect FAIL
```bash
pytest tests/gateway/test_multimodal_integration.py -v 2>&1 | tail -10
```

### Step 3: Modify `marneo/gateway/manager.py` `_process()`

Change the `send_with_tools` call to pass attachments:

```python
    async def _process(self, msg: ChannelMessage, engine: Any, adapter: BaseChannelAdapter) -> None:
        parts: list[str] = []
        try:
            async with asyncio.timeout(REPLY_TIMEOUT):
                async for event in engine.send_with_tools(
                    msg.text,
                    registry=_tool_registry,
                    attachments=msg.attachments or None,
                ):
                    if event.type == "text" and event.content:
                        parts.append(event.content)
                    elif event.type == "tool_result":
                        log.debug("[Gateway] Tool result: %s", event.content[:100])
        except TimeoutError:
            parts = ["处理超时，请重试。"]
        except Exception as e:
            parts = [f"处理出错：{e}"]

        reply = "".join(parts).strip()
        if not reply:
            return
        while reply:
            chunk, reply = reply[:MAX_REPLY_LEN], reply[MAX_REPLY_LEN:]
            await adapter.send_reply(msg.chat_id, chunk, context_token=msg.context_token)
```

### Step 4: Run — expect PASS
```bash
pytest tests/gateway/test_multimodal_integration.py tests/gateway/ -v -q
```

### Step 5: Run full suite
```bash
pytest tests/ -q --tb=short
```

### Step 6: Commit
```bash
git add marneo/gateway/manager.py tests/gateway/test_multimodal_integration.py
git commit -m "feat(gateway): pass ChannelMessage.attachments to send_with_tools"
```

---

## Task 5: Smoke test end-to-end

### Step 1: Verify full suite passes
```bash
cd /Users/chamber/code/marneo-agent && pytest tests/ -q --tb=short
```
Expected: all pass

### Step 2: Verify multimodal content block building works
```bash
python3 -c "
import base64
from marneo.engine.chat import _build_content_blocks

# Image test
att = {'data': b'\xff\xd8\xff', 'media_type': 'image/jpeg', 'filename': 'test.jpg'}
blocks = _build_content_blocks('describe', [att], 'openai-compatible')
print('OpenAI image blocks:', type(blocks), len(blocks) if isinstance(blocks, list) else 'str')
assert isinstance(blocks, list)
assert blocks[0]['type'] == 'text'
assert blocks[1]['type'] == 'image_url'
print('  ✓ OpenAI image OK')

# Anthropic PDF
att2 = {'data': b'%PDF-1.4', 'media_type': 'application/pdf', 'filename': 'doc.pdf'}
blocks2 = _build_content_blocks('summarize', [att2], 'anthropic-compatible')
assert any(b.get('type') == 'document' for b in blocks2)
print('  ✓ Anthropic PDF OK')

# Text file injection
att3 = {'data': b'name,age\nAlice,30', 'media_type': 'text/plain', 'filename': 'data.csv'}
blocks3 = _build_content_blocks('analyze', [att3], 'openai-compatible')
all_text = ' '.join(b.get('text','') for b in blocks3 if b.get('type')=='text')
assert 'Alice' in all_text
print('  ✓ Text file injection OK')

print()
print('ALL SMOKE TESTS PASSED')
"
```

### Step 3: Restart gateway and test
```bash
marneo gateway restart
```
Then send an image or PDF file in Feishu — the employee should now respond with actual content analysis.

### Step 4: Final commit
```bash
git add -A
git commit -m "feat(multimodal): complete multimodal file message support for Feishu"
```

---

## Summary

After all tasks:
- Feishu image messages → downloaded via `im.v1.message_resource.get()` → sent as image block to LLM
- Feishu file messages (PDF, txt, md, json) → downloaded → sent as document block (Anthropic) or text inject (OpenAI/MiniMax)
- `ChannelMessage.attachments` carries `{data: bytes, media_type: str, filename: str}` per file
- `_build_content_blocks()` normalizes to the right format per provider protocol
- Works with MiniMax (openai-compatible), Anthropic, OpenAI, any provider
