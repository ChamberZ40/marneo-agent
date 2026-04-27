# Phase B: Cleanup Sprint Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Stabilize the codebase after rapid iteration — fix exception handling, add missing tests, fix employee identity, clean debug artifacts.

**Architecture:** Targeted fixes across 5 areas. No new features. Each task is independent and can be committed separately. Focus on preventing regressions and improving debuggability.

**Tech Stack:** Python 3.11+, pytest, existing marneo modules.

---

## Task 1: Fix employee identity in system prompt

**Files:**
- Modify: `marneo/gateway/session.py`

### Step 1: Read current code

```bash
grep -A5 "Your name is" /Users/chamber/code/marneo-agent/marneo/gateway/session.py
cat ~/.marneo/employees/laoqi/profile.yaml | head -8
```

### Step 2: Fix — use display name from profile.yaml, not directory name

Currently `session.py` line 69 does: `soul = f"Your name is {emp_name}.\n\n"` where `emp_name = "laoqi"` (directory name). Should use the display name `老七` from `profile.yaml`.

```python
                profile = load_profile(emp_name)
                # Use display name from profile, fallback to directory name
                display_name = getattr(profile, 'name', emp_name) if profile else emp_name
                soul = f"Your name is {display_name} (id: {emp_name}).\n\n"
```

### Step 3: Verify

```bash
python3 -c "
from marneo.memory.session_memory import SessionMemory
from marneo.employee.profile import load_profile
from marneo.employee.growth import build_level_directive
profile = load_profile('laoqi')
display_name = getattr(profile, 'name', 'laoqi') if profile else 'laoqi'
soul = f'Your name is {display_name} (id: laoqi).\n\n'
if profile and profile.soul_path.exists():
    soul += profile.soul_path.read_text(encoding='utf-8').strip()
sm = SessionMemory('laoqi', soul=soul)
prompt = sm.build_system_prompt()
print('Contains 老七:', '老七' in prompt)
print('Contains laoqi:', 'laoqi' in prompt)
print('First 200 chars:', prompt[:200])
"
```
Expected: `Contains 老七: True`, `Contains laoqi: True`

### Step 4: Commit

```bash
git add marneo/gateway/session.py
git commit -m "fix: use display name from profile.yaml in system prompt (老七 not laoqi)"
```

---

## Task 2: Clean debug logs

**Files:**
- Modify: `marneo/gateway/adapters/feishu.py`

### Step 1: Change debug logs to appropriate levels

Find and fix:
1. `_on_message_event` debug log (line ~462) — change from `log.info` to `log.debug`
2. `Group msg dropped` log (line ~548) — change from `log.info` to `log.debug`

### Step 2: Verify no INFO debug noise

```bash
grep -n "log.info.*_on_message_event\|log.info.*Group msg dropped" /Users/chamber/code/marneo-agent/marneo/gateway/adapters/feishu.py
```
Expected: no matches (both should be `log.debug` now)

### Step 3: Run tests + commit

```bash
pytest tests/ -q --tb=short
git add marneo/gateway/adapters/feishu.py
git commit -m "chore: demote debug logs to DEBUG level in feishu adapter"
```

---

## Task 3: Tests for feishu_tools.py

**Files:**
- Create: `tests/tools/test_feishu_tools.py`

### Step 1: Write tests

```python
# tests/tools/test_feishu_tools.py
import json
import pytest
from marneo.tools.core.feishu_tools import (
    _build_mention_text, feishu_send_mention, feishu_search_user, feishu_create_doc
)


# ── _build_mention_text ──────────────────────────────────────────────────────

def test_build_mention_text_single_user():
    result = _build_mention_text(
        [{"open_id": "ou_123", "name": "张三"}],
        "你好"
    )
    assert '<at user_id="ou_123">张三</at>' in result
    assert "你好" in result


def test_build_mention_text_multiple_users():
    result = _build_mention_text([
        {"open_id": "ou_1", "name": "A"},
        {"open_id": "ou_2", "name": "B"},
    ], "开会")
    assert '<at user_id="ou_1">A</at>' in result
    assert '<at user_id="ou_2">B</at>' in result
    assert "开会" in result


def test_build_mention_text_at_all():
    result = _build_mention_text([{"open_id": "all", "name": ""}], "注意")
    assert '<at user_id="all">所有人</at>' in result


def test_build_mention_text_empty():
    result = _build_mention_text([], "hello")
    assert result == "hello"


def test_build_mention_text_no_text():
    result = _build_mention_text([{"open_id": "ou_1", "name": "X"}])
    assert '<at user_id="ou_1">X</at>' in result


# ── feishu_send_mention validation ───────────────────────────────────────────

def test_send_mention_missing_chat_id():
    result = json.loads(feishu_send_mention({}))
    assert "error" in result


def test_send_mention_no_credentials():
    """When no Feishu credentials configured, returns error."""
    from unittest.mock import patch
    with patch("marneo.tools.core.feishu_tools.list_configured_employees", return_value=[]):
        result = json.loads(feishu_send_mention({
            "chat_id": "oc_test",
            "mentions": [{"open_id": "ou_1", "name": "Test"}],
            "text": "hello",
        }))
    assert "error" in result


# ── feishu_search_user validation ────────────────────────────────────────────

def test_search_user_missing_query():
    result = json.loads(feishu_search_user({}))
    assert "error" in result


def test_search_user_no_lark_cli():
    """When lark-cli not found, returns error."""
    from unittest.mock import patch
    with patch("shutil.which", return_value=None):
        result = json.loads(feishu_search_user({"query": "test"}))
    assert "error" in result


# ── feishu_create_doc validation ─────────────────────────────────────────────

def test_create_doc_missing_content():
    result = json.loads(feishu_create_doc({}))
    assert "error" in result


def test_create_doc_delegates_to_lark_cli():
    """Verify it calls lark_cli with the right command."""
    from unittest.mock import patch
    with patch("marneo.tools.core.feishu_tools.lark_cli", return_value='{"ok": true}') as mock:
        result = feishu_create_doc({"title": "Test Doc", "content": "# Hello"})
        mock.assert_called_once()
        call_args = mock.call_args[0][0]
        assert "docs +create" in call_args["command"]
        assert "Test Doc" in call_args["command"]
```

### Step 2: Run tests

```bash
pytest tests/tools/test_feishu_tools.py -v
```
Expected: 12 passed

### Step 3: Commit

```bash
git add tests/tools/test_feishu_tools.py
git commit -m "test: add 12 tests for feishu_tools (mention, search, create_doc)"
```

---

## Task 4: Tests for lark_cli.py

**Files:**
- Create: `tests/tools/test_lark_cli.py`

### Step 1: Write tests

```python
# tests/tools/test_lark_cli.py
import json
import pytest
from unittest.mock import patch, MagicMock
from marneo.tools.core.lark_cli import (
    lark_cli, _get_feishu_credentials, _ensure_lark_cli_configured
)


def test_lark_cli_missing_command():
    result = json.loads(lark_cli({}))
    assert "error" in result


def test_lark_cli_no_lark_binary():
    with patch("shutil.which", return_value=None):
        result = json.loads(lark_cli({"command": "calendar +agenda"}))
    assert "error" in result
    assert "not installed" in result["error"]


def test_lark_cli_no_credentials():
    with patch("marneo.tools.core.lark_cli._get_feishu_credentials", return_value=("", "", "feishu")):
        result = json.loads(lark_cli({"command": "calendar +agenda"}))
    assert "error" in result


def test_get_feishu_credentials_returns_tuple():
    """Should return (app_id, app_secret, domain) tuple."""
    result = _get_feishu_credentials()
    assert isinstance(result, tuple)
    assert len(result) == 3


def test_ensure_configured_returns_none_on_success():
    """Returns None when already configured."""
    mock_proc = MagicMock()
    mock_proc.stdout = "app_id: cli_test123"
    mock_proc.stderr = ""
    mock_proc.returncode = 0
    with patch("subprocess.run", return_value=mock_proc):
        result = _ensure_lark_cli_configured("cli_test123", "secret", "feishu")
    assert result is None  # None = success


def test_lark_cli_appends_as_bot():
    """Verify --as bot is appended to commands."""
    mock_proc = MagicMock()
    mock_proc.stdout = '{"ok": true}'
    mock_proc.stderr = ""
    mock_proc.returncode = 0
    with patch("shutil.which", return_value="/usr/bin/lark-cli"), \
         patch("marneo.tools.core.lark_cli._get_feishu_credentials", return_value=("aid", "asec", "feishu")), \
         patch("marneo.tools.core.lark_cli._ensure_lark_cli_configured", return_value=None), \
         patch("subprocess.run", return_value=mock_proc) as mock_run:
        lark_cli({"command": "calendar +agenda"})
        call_args = mock_run.call_args[0][0]
        assert "--as" in call_args
        assert "bot" in call_args
```

### Step 2: Run tests

```bash
pytest tests/tools/test_lark_cli.py -v
```
Expected: 6 passed

### Step 3: Commit

```bash
git add tests/tools/test_lark_cli.py
git commit -m "test: add 6 tests for lark_cli (validation, credentials, --as bot)"
```

---

## Task 5: Fix critical exception swallowing (top 10)

**Files:**
- Modify: `marneo/tools/core/lark_cli.py`
- Modify: `marneo/memory/session_memory.py`
- Modify: `marneo/gateway/session.py`
- Modify: `marneo/gateway/adapters/feishu.py`

### Step 1: Fix the worst offenders

Target the 10 most impactful `except Exception: pass` locations and add logging:

**Pattern to apply everywhere:**
```python
# BAD
except Exception:
    pass

# GOOD
except Exception as exc:
    log.warning("[Module] operation failed: %s", exc)
```

Key files to fix:
1. `lark_cli.py:24` — credential loading silent fail
2. `session_memory.py:36` — config loading silent fail
3. `session_memory.py:70` — retriever init silent fail
4. `session.py:81` — SessionMemory init silent fail (already has logging ✓)
5. `feishu.py` — multiple reaction/card error handlers

### Step 2: Run tests

```bash
pytest tests/ -q --tb=short
```
Expected: all pass (adding logging doesn't change behavior)

### Step 3: Commit

```bash
git add marneo/tools/core/lark_cli.py marneo/memory/session_memory.py marneo/gateway/adapters/feishu.py
git commit -m "fix: replace bare except:pass with logged warnings in critical paths"
```

---

## Summary

| Task | What | Tests added |
|------|------|-------------|
| 1 | Employee identity (display name in prompt) | 0 (manual verify) |
| 2 | Clean debug logs | 0 (log level change) |
| 3 | feishu_tools.py tests | 12 |
| 4 | lark_cli.py tests | 6 |
| 5 | Exception handling fix | 0 (behavior unchanged) |

Expected final: ~158 tests passing (140 current + 18 new)
