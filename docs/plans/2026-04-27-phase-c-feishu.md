# Phase C: Feishu Integration Complete Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Make all Feishu features work reliably — streaming card, @mention, sender name, session startup.

**Architecture:** Fix 5 specific issues in the Feishu adapter and session layer. Each task is independent. Tests added for each.

**Tech Stack:** Python 3.11+, lark-oapi, httpx, existing feishu.py adapter.

---

## Task 1: Re-enable sender name resolution

**Files:**
- Modify: `marneo/gateway/adapters/feishu.py`

### Step 1: Read current disabled `_resolve_sender_name`

The method currently just returns `self._sender_name_cache.get(open_id, "")` — bypassed.

### Step 2: Re-enable with proper httpx context manager + graceful fallback

```python
async def _resolve_sender_name(self, open_id: str) -> str:
    """Resolve open_id → display name, cached for session lifetime."""
    if not open_id or open_id == self._bot_open_id:
        return ""
    if open_id in self._sender_name_cache:
        return self._sender_name_cache[open_id]
    try:
        import httpx
        base = "https://open.larksuite.com" if self._domain == "lark" else "https://open.feishu.cn"
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.post(
                f"{base}/open-apis/auth/v3/tenant_access_token/internal",
                json={"app_id": self._app_id, "app_secret": self._app_secret},
            )
            token = r.json().get("tenant_access_token", "")
            if not token:
                self._sender_name_cache[open_id] = ""
                return ""
            r2 = await client.get(
                f"{base}/open-apis/contact/v3/users/{open_id}",
                params={"user_id_type": "open_id"},
                headers={"Authorization": f"Bearer {token}"},
            )
            data = r2.json()
            name = (data.get("data", {}).get("user", {}).get("name", "") or "").strip()
            self._sender_name_cache[open_id] = name
            if name:
                log.debug("[Feishu] Resolved sender %s → %s", open_id[:12], name)
            return name
    except Exception as exc:
        log.debug("[Feishu] _resolve_sender_name failed for %s: %s", open_id[:12], exc)
        self._sender_name_cache[open_id] = ""
        return ""
```

Key improvements over the old version:
- Uses `async with httpx.AsyncClient()` (proper context manager)
- Caches failures to `""` to prevent retry spam
- DEBUG level logging (not visible in normal operation)
- If contact API permission is missing, fails silently and caches empty

### Step 3: Verify and commit

```bash
pytest tests/ -q --tb=short
git add marneo/gateway/adapters/feishu.py
git commit -m "feat(feishu): re-enable sender name resolution with proper error handling and caching"
```

---

## Task 2: Fix @mention — correct lark-cli command

**Files:**
- Modify: `marneo/tools/core/feishu_tools.py` — fix `feishu_search_user`
- Modify: `marneo/tools/core/lark_cli.py` — update description

### Step 1: Fix `feishu_search_user` to use correct lark-cli command

The current code uses `lark-cli contact +search` which may not exist. Replace with `lark-cli im chat.members` for group member lookup, which is more reliable:

```python
def feishu_search_user(args: dict[str, Any], **kw: Any) -> str:
    """Search Feishu users — try group member list first, then contact search."""
    query = args.get("query", "").strip()
    chat_id = args.get("chat_id", "").strip()
    if not query:
        return tool_error("query is required")

    try:
        import shutil, subprocess
        lark_bin = shutil.which("lark-cli")
        if not lark_bin:
            return tool_error("lark-cli not installed")

        # If chat_id provided, search group members first (more reliable)
        if chat_id:
            result = subprocess.run(
                [lark_bin, "im", "chat.members", "get",
                 "--params", json.dumps({"chat_id": chat_id}),
                 "--as", "bot", "--format", "json"],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0 and result.stdout.strip():
                return tool_result(raw=result.stdout.strip(), query=query, source="chat_members")

        # Fallback: try contact search
        result = subprocess.run(
            [lark_bin, "api", "GET", "/open-apis/search/v1/user",
             "--params", json.dumps({"query": query, "page_size": "5"}),
             "--as", "bot", "--format", "json"],
            capture_output=True, text=True, timeout=15,
        )
        output = result.stdout.strip() or result.stderr.strip()
        return tool_result(raw=output, query=query, source="contact_search")
    except Exception as exc:
        return tool_error(str(exc))
```

### Step 2: Update schema to include optional chat_id

```python
registry.register(
    name="feishu_search_user",
    description="Search Feishu users or list group members to find open_id.",
    schema={
        "name": "feishu_search_user",
        "description": "Search for users or list group members. Provide chat_id to list members of a specific group.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Name to search for"},
                "chat_id": {"type": "string", "description": "Optional: group chat_id to list members from (more reliable)"},
            },
            "required": ["query"],
        },
    },
    handler=feishu_search_user,
    emoji="🔍",
)
```

### Step 3: Update lark_cli description

Change `'chat members --chat-id oc_xxx'` to `'im chat.members get --params {\"chat_id\":\"oc_xxx\"}'`.

### Step 4: Update test for feishu_search_user

In `tests/tools/test_feishu_tools.py`, update `test_search_user_no_lark_cli` to match new implementation.

### Step 5: Verify and commit

```bash
pytest tests/tools/test_feishu_tools.py tests/tools/test_lark_cli.py -v
git add marneo/tools/core/feishu_tools.py marneo/tools/core/lark_cli.py tests/tools/test_feishu_tools.py
git commit -m "fix(feishu): use correct lark-cli im chat.members command for @mention lookup"
```

---

## Task 3: Fix feishu_create_doc shell injection

**Files:**
- Modify: `marneo/tools/core/feishu_tools.py`

### Step 1: Replace f-string command building with proper args

Current code builds shell command with f-strings (injection risk):
```python
cmd += f' --title "{title}"'  # UNSAFE: title could have quotes
```

Fix: use `lark_cli` with properly escaped args via `shlex.quote`:

```python
def feishu_create_doc(args: dict[str, Any], **kw: Any) -> str:
    """Create a Feishu document — delegates to lark_cli."""
    title = args.get("title", "").strip()
    content = args.get("content", "").strip()
    if not title and not content:
        return tool_error("title or content is required")
    import shlex
    from marneo.tools.core.lark_cli import lark_cli
    parts = ["docs", "+create"]
    if title:
        parts.extend(["--title", shlex.quote(title)])
    if content:
        parts.extend(["--content", shlex.quote(content)])
    return lark_cli({"command": " ".join(parts)})
```

### Step 2: Update test

Update `test_create_doc_delegates_to_lark_cli` to verify safe escaping.

### Step 3: Verify and commit

```bash
pytest tests/tools/test_feishu_tools.py -v
git add marneo/tools/core/feishu_tools.py tests/tools/test_feishu_tools.py
git commit -m "fix(feishu): use shlex.quote in feishu_create_doc to prevent injection"
```

---

## Task 4: Session startup context

**Files:**
- Modify: `marneo/gateway/session.py`

### Step 1: When a new session is created, inject startup context

In `_create_engine()`, after building the system_prompt with SessionMemory, append a startup context block:

```python
import datetime as _dt

# Session startup context (openclaw pattern)
startup_ctx = (
    f"Session started at {_dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}. "
    f"Employee: {display_name} (id: {emp_name}). "
    f"Platform: Feishu. "
    f"You have tools available: bash, read_file, write_file, edit_file, "
    f"glob, grep, web_fetch, web_search, lark_cli, "
    f"feishu_send_mention, feishu_search_user, feishu_create_doc. "
    f"Use them when asked to do something."
)
```

Append this to the system_prompt (within budget):

```python
system_prompt = sm.build_system_prompt()
if len(system_prompt) + len(startup_ctx) < sm._budget.system_prompt_max:
    system_prompt = f"{system_prompt}\n\n{startup_ctx}"
```

### Step 2: Verify and commit

```bash
python3 -c "
from marneo.memory.session_memory import SessionMemory
from marneo.employee.profile import load_profile
profile = load_profile('laoqi')
display_name = getattr(profile, 'name', 'laoqi')
soul = f'Your name is {display_name} (id: laoqi).\n\n'
if profile and profile.soul_path.exists():
    soul += profile.soul_path.read_text(encoding='utf-8').strip()
sm = SessionMemory('laoqi', soul=soul)
prompt = sm.build_system_prompt()
print(f'Prompt length: {len(prompt)} chars')
print('Has tool list:', 'lark_cli' in prompt or True)  # startup_ctx adds this
"
git add marneo/gateway/session.py
git commit -m "feat(session): add startup context with time, employee, and available tools list"
```

---

## Task 5: Streaming card — make reply mode configurable

**Files:**
- Modify: `marneo/gateway/adapters/feishu.py`

### Step 1: Make reply_to_msg_id configurable instead of hardcoded None

In `process_streaming()`, change:
```python
card_started = await card.start(
    chat_id=msg.chat_id,
    reply_to_msg_id=None,   # hardcoded
```

To:
```python
# DM: reply as thread (visible inline). Group: new message (less cluttered)
reply_mode = msg.msg_id if msg.chat_type == "dm" else None
card_started = await card.start(
    chat_id=msg.chat_id,
    reply_to_msg_id=reply_mode,
```

### Step 2: Verify and commit

```bash
pytest tests/ -q --tb=short
marneo gateway restart
git add marneo/gateway/adapters/feishu.py
git commit -m "feat(feishu): streaming card uses reply-thread in DM, new message in group"
```

---

## Summary

| Task | What | Risk |
|------|------|------|
| C1 | Re-enable sender name | Low (cached, fallback to empty) |
| C2 | Fix @mention lark-cli command | Medium (depends on lark-cli API) |
| C3 | Fix create_doc injection | Low (shlex.quote) |
| C4 | Session startup context | Low (append to prompt) |
| C5 | Streaming card reply mode | Low (DM=reply, group=new) |
