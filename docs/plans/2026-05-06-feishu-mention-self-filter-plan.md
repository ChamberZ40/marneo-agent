# Feishu Group Mention and Self-Filter Precision Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task after user review.

**Goal:** Make Marneo's Feishu group-message routing precise and safe: group `at_only` mode should only respond when this specific bot is mentioned, self-sent events from this bot must be dropped by both open_id and user_id, and other bots' messages should remain allowed for multi-agent collaboration.

**Architecture:** Keep Marneo Feishu-first and per-employee. Store optional bot identity and message policies in each employee's `~/.marneo/employees/<employee>/feishu.yaml`, pass those fields through `GatewayManager` into `FeishuChannelAdapter`, then centralize mention/self-filter checks inside small testable helper methods in `marneo/gateway/adapters/feishu.py`. Do not copy Hermes' full group_rules/admin system yet; only port the high-value ID-first matching behavior.

**Tech Stack:** Python 3.11+, Typer CLI, lark-oapi, pytest, YAML employee config.

---

## Current WIP State

This plan is being written while a small WIP diff already exists locally:

```text
M marneo/employee/feishu_config.py
M marneo/gateway/adapters/feishu.py
M marneo/gateway/manager.py
```

Current WIP already added:

- `EmployeeFeishuConfig.bot_user_id`
- `EmployeeFeishuConfig.bot_name`
- `EmployeeFeishuConfig.dm_policy`
- `EmployeeFeishuConfig.group_policy`
- `GatewayManager.start_all()` now passes those fields into `FeishuChannelAdapter.connect()`
- `FeishuChannelAdapter.__init__()` now has `_bot_user_id` and `_bot_name`
- `FeishuChannelAdapter.connect()` now pre-populates `_bot_open_id`, `_bot_user_id`, and `_bot_name` from config

Important review note: this WIP was started before the full TDD plan was written. If we want strict TDD purity, stash/revert WIP before implementation and re-apply via the RED/GREEN cycles below. If we accept the WIP as already-started exploratory work, then the next implementation step must add regression tests before changing behavior further.

Recommended command if strict reset is desired:

```bash
cd /Users/chamber/code/marneo-agent
git diff -- marneo/employee/feishu_config.py marneo/gateway/manager.py marneo/gateway/adapters/feishu.py > /tmp/marneo-feishu-mention-wip.patch
git checkout -- marneo/employee/feishu_config.py marneo/gateway/manager.py marneo/gateway/adapters/feishu.py
```

Recommended command if keeping WIP:

```bash
cd /Users/chamber/code/marneo-agent
git diff --stat
python3 -m pytest tests -q
```

---

## Problem Summary

Current high-risk behavior in `marneo/gateway/adapters/feishu.py`:

1. Group `at_only` false positive when bot identity is missing
   - Current line area: `marneo/gateway/adapters/feishu.py:831-848`
   - Current logic: if `_bot_open_id` exists, match mention `id.open_id`; otherwise `bool(mentions)` means any @mention can wake the bot.
   - Risk: if hydration fails, a group message mentioning any user/bot may trigger this bot.

2. Self-filter only checks open_id
   - Current line area: `marneo/gateway/adapters/feishu.py:981-995`
   - Current logic: drops self-sent message only when sender is bot/app and sender `open_id == _bot_open_id`.
   - Risk: if only `user_id` is present or configured, self messages are not dropped; potential loops.

3. Bot identity hydration only fills `_bot_open_id`, not `_bot_user_id`/`_bot_name`
   - Current line area: `marneo/gateway/adapters/feishu.py:564-588`
   - Current logic: `/bot/v3/info` stores open_id and logs app_name but does not persist name into adapter field.
   - Risk: no reliable name fallback when mention payload lacks IDs.

4. Per-employee Feishu config did not previously carry policy/identity fields
   - Current file: `marneo/employee/feishu_config.py`
   - WIP already started adding these fields.

---

## Desired Behavior

### Group policy

Supported `group_policy` values for now:

```text
open      => accept all group messages after allowlist/self-filter gates
at_only   => accept group messages only when this bot is explicitly mentioned
all_only  => accept group messages only when Feishu @_all is present
disabled  => drop all group messages
```

Default remains:

```text
group_policy = at_only
```

Do not add Hermes-style `group_rules`, `admins`, `allowlist`, `blacklist`, `admin_only` in this phase. That belongs to a later P1/P2 task.

### Mention matching

For `at_only`, ID matching must be strict:

1. If mention `id.open_id` and adapter `_bot_open_id` both exist:
   - match only if equal
   - if not equal, do not fall back to name for that mention

2. If mention `id.user_id` and adapter `_bot_user_id` both exist:
   - match only if equal
   - if not equal, do not fall back to name for that mention

3. Name fallback is only allowed when the mention lacks both comparable IDs:
   - `mention.name == _bot_name`
   - `_bot_name` must be non-empty

4. If adapter has no bot identity at all:
   - do not treat `bool(mentions)` as a match
   - log a warning/debug line and drop group `at_only` messages safely

### @_all handling

Policy should be explicit:

- `group_policy=open`: accept `@_all` because all group messages are accepted.
- `group_policy=at_only`: do NOT automatically treat `@_all` as this bot unless we explicitly decide to support that. Recommended for Marneo multi-bot groups: do not route `@_all` by default, because every employee bot would wake up.
- `group_policy=all_only`: accept only if raw content contains `@_all`.
- `group_policy=disabled`: drop.

This differs from Hermes, where `_should_accept_group_message()` currently treats `@_all` as route-to-bot. Marneo has more multi-bot group risk, so the safer default is `at_only` without all-mention routing.

### Self-sent filtering

Drop only messages emitted by this bot:

- `sender.sender_type in {"bot", "app"}` is required.
- If `_bot_open_id` and sender `open_id` match: drop.
- Else if `_bot_user_id` and sender `user_id` match: drop.
- Else do not drop, so other bots can collaborate in group chats.

Do not use name fallback for self-filter unless we later prove Feishu self events lack IDs; name-only self-filter can accidentally drop another bot with the same display name.

---

## Files to Modify

### Production files

1. `marneo/employee/feishu_config.py`
   - Add/preserve fields:
     - `bot_user_id: str = ""`
     - `bot_name: str = ""`
     - `dm_policy: str = "open"`
     - `group_policy: str = "at_only"`
   - Ensure `load_feishu_config()` reads them with safe defaults.
   - Ensure `save_feishu_config()` writes them.
   - Optional: normalize policy strings on load/save.

2. `marneo/gateway/manager.py`
   - In `GatewayManager.start_all()`, pass fields from `EmployeeFeishuConfig` into adapter config:
     - `bot_open_id`
     - `bot_user_id`
     - `bot_name`
     - `dm_policy`
     - `group_policy`

3. `marneo/gateway/adapters/feishu.py`
   - Add `_bot_user_id` and `_bot_name` fields.
   - Pre-populate identity fields from config.
   - Update `_hydrate_bot_identity()` to fill missing `_bot_open_id`, `_bot_user_id`, and `_bot_name` independently.
   - Add helper `_message_mentions_this_bot(mentions: list[Any]) -> bool`.
   - Add helper `_mention_to_ref(mention: Any) -> dict[str, str]` or inline safe getters.
   - Update group-policy block in `_handle_message_event_data()`.
   - Update `_is_self_sent_bot_message()` to check user_id.
   - Reduce mention debug logging from `log.info` to `log.debug` and redact IDs to prefixes.

### Test files

Create:

1. `tests/gateway/test_feishu_mention_filter.py`

Modify or create if needed:

2. `tests/employee/test_feishu_config.py`
3. `tests/gateway/test_manager_employee_feishu_config.py`

---

## Task 1: Add Feishu mention/self-filter test helpers

**Objective:** Create small test helper classes that mimic lark-oapi sender/mention objects without requiring real network or lark-oapi objects.

**Files:**
- Create: `tests/gateway/test_feishu_mention_filter.py`

**Step 1: Write helper classes**

```python
from types import SimpleNamespace

from marneo.gateway.adapters.feishu import FeishuChannelAdapter


def mention(*, open_id="", user_id="", name="", key=""):
    return SimpleNamespace(
        id=SimpleNamespace(open_id=open_id, user_id=user_id),
        name=name,
        key=key,
    )


def sender(*, sender_type="bot", open_id="", user_id=""):
    return SimpleNamespace(
        sender_type=sender_type,
        sender_id=SimpleNamespace(open_id=open_id, user_id=user_id),
    )


def adapter_with_identity(*, open_id="", user_id="", name=""):
    adapter = FeishuChannelAdapter(manager=None, employee_name="laoqi")
    adapter._bot_open_id = open_id
    adapter._bot_user_id = user_id
    adapter._bot_name = name
    return adapter
```

**Step 2: Run current file to verify import works**

```bash
cd /Users/chamber/code/marneo-agent
python3 -m pytest tests/gateway/test_feishu_mention_filter.py -q
```

Expected initially: PASS with no tests or collection OK after helper-only creation. If pytest reports "no tests ran" with exit code 5, add the first test in Task 2 before running.

---

## Task 2: RED — mention open_id positive and negative tests

**Objective:** Ensure mention matching is ID-first and refuses wrong open_id.

**Files:**
- Modify: `tests/gateway/test_feishu_mention_filter.py`
- Modify later: `marneo/gateway/adapters/feishu.py`

**Step 1: Write failing tests**

```python
def test_message_mentions_this_bot_by_open_id():
    adapter = adapter_with_identity(open_id="ou_bot", name="Bot")

    assert adapter._message_mentions_this_bot([
        mention(open_id="ou_bot", name="Someone Else Label")
    ]) is True


def test_message_does_not_mention_this_bot_when_open_id_differs_even_if_name_matches():
    adapter = adapter_with_identity(open_id="ou_bot", name="Bot")

    assert adapter._message_mentions_this_bot([
        mention(open_id="ou_other", name="Bot")
    ]) is False
```

**Step 2: Run to verify RED**

```bash
python3 -m pytest tests/gateway/test_feishu_mention_filter.py::test_message_mentions_this_bot_by_open_id tests/gateway/test_feishu_mention_filter.py::test_message_does_not_mention_this_bot_when_open_id_differs_even_if_name_matches -q
```

Expected: FAIL with `AttributeError: 'FeishuChannelAdapter' object has no attribute '_message_mentions_this_bot'` if WIP has not implemented helper yet.

**Step 3: Implement minimal helper**

Add to `marneo/gateway/adapters/feishu.py` near `_is_self_sent_bot_message()`:

```python
    def _message_mentions_this_bot(self, mentions: list[Any]) -> bool:
        """Return True when a Feishu mention explicitly targets this bot.

        IDs are authoritative. Name fallback is only used when no comparable ID
        is present in the mention payload.
        """
        for mention in mentions or []:
            mention_id = getattr(mention, "id", None)
            mention_open_id = str(getattr(mention_id, "open_id", "") or "").strip()
            mention_user_id = str(getattr(mention_id, "user_id", "") or "").strip()
            mention_name = str(getattr(mention, "name", "") or "").strip()

            if mention_open_id and self._bot_open_id:
                if mention_open_id == self._bot_open_id:
                    return True
                continue
            if mention_user_id and self._bot_user_id:
                if mention_user_id == self._bot_user_id:
                    return True
                continue
            if self._bot_name and mention_name == self._bot_name:
                return True
        return False
```

**Step 4: Run to verify GREEN**

```bash
python3 -m pytest tests/gateway/test_feishu_mention_filter.py -q
```

Expected: PASS for new tests.

---

## Task 3: Add user_id and name fallback mention tests

**Objective:** Cover user_id fallback and safe name fallback rules.

**Files:**
- Modify: `tests/gateway/test_feishu_mention_filter.py`
- Modify: `marneo/gateway/adapters/feishu.py` only if tests fail

**Step 1: Write tests**

```python
def test_message_mentions_this_bot_by_user_id_when_open_id_missing():
    adapter = adapter_with_identity(user_id="u_bot", name="Bot")

    assert adapter._message_mentions_this_bot([
        mention(user_id="u_bot", name="Wrong Label")
    ]) is True


def test_message_does_not_mention_this_bot_when_user_id_differs_even_if_name_matches():
    adapter = adapter_with_identity(user_id="u_bot", name="Bot")

    assert adapter._message_mentions_this_bot([
        mention(user_id="u_other", name="Bot")
    ]) is False


def test_message_mentions_this_bot_by_name_only_when_ids_unavailable():
    adapter = adapter_with_identity(open_id="ou_bot", user_id="u_bot", name="Bot")

    assert adapter._message_mentions_this_bot([
        mention(name="Bot")
    ]) is True


def test_any_mention_does_not_match_when_bot_identity_missing():
    adapter = adapter_with_identity()

    assert adapter._message_mentions_this_bot([
        mention(open_id="ou_someone", user_id="u_someone", name="Someone")
    ]) is False
```

**Step 2: Run tests**

```bash
python3 -m pytest tests/gateway/test_feishu_mention_filter.py -q
```

Expected: PASS if Task 2 helper is correct.

---

## Task 4: RED/GREEN — self-filter checks user_id as well as open_id

**Objective:** Prevent self-loop when Feishu sender contains user_id but not open_id.

**Files:**
- Modify: `tests/gateway/test_feishu_mention_filter.py`
- Modify: `marneo/gateway/adapters/feishu.py:981-995`

**Step 1: Write tests**

```python
def test_self_sent_bot_message_drops_by_open_id():
    adapter = adapter_with_identity(open_id="ou_bot", user_id="u_bot")

    assert adapter._is_self_sent_bot_message(
        sender(sender_type="bot", open_id="ou_bot", user_id="u_other")
    ) is True


def test_self_sent_bot_message_drops_by_user_id_when_open_id_missing():
    adapter = adapter_with_identity(open_id="ou_bot", user_id="u_bot")

    assert adapter._is_self_sent_bot_message(
        sender(sender_type="bot", user_id="u_bot")
    ) is True


def test_self_sent_filter_allows_other_bots():
    adapter = adapter_with_identity(open_id="ou_bot", user_id="u_bot")

    assert adapter._is_self_sent_bot_message(
        sender(sender_type="bot", open_id="ou_other", user_id="u_other")
    ) is False


def test_self_sent_filter_ignores_human_sender_even_if_id_matches():
    adapter = adapter_with_identity(open_id="ou_bot", user_id="u_bot")

    assert adapter._is_self_sent_bot_message(
        sender(sender_type="user", open_id="ou_bot", user_id="u_bot")
    ) is False
```

**Step 2: Run to verify RED**

```bash
python3 -m pytest tests/gateway/test_feishu_mention_filter.py::test_self_sent_bot_message_drops_by_user_id_when_open_id_missing -q
```

Expected before code update: FAIL because `_is_self_sent_bot_message()` only checks open_id.

**Step 3: Implement minimal code**

Update `_is_self_sent_bot_message()`:

```python
    def _is_self_sent_bot_message(self, sender: Any) -> bool:
        """Return True only for events emitted by THIS bot.

        Drop self-sent messages to prevent infinite loops, but allow other
        bots' messages through so multi-agent @mention collaboration works.
        """
        sender_type = str(getattr(sender, "sender_type", "") or "").strip().lower()
        if sender_type not in {"bot", "app"}:
            return False
        sender_id_obj = getattr(sender, "sender_id", None)
        sender_open_id = str(getattr(sender_id_obj, "open_id", "") or "").strip()
        sender_user_id = str(getattr(sender_id_obj, "user_id", "") or "").strip()
        if self._bot_open_id and sender_open_id == self._bot_open_id:
            return True
        if self._bot_user_id and sender_user_id == self._bot_user_id:
            return True
        return False
```

**Step 4: Run tests**

```bash
python3 -m pytest tests/gateway/test_feishu_mention_filter.py -q
```

Expected: PASS.

---

## Task 5: RED/GREEN — group policy helper and @_all behavior

**Objective:** Move group acceptance decisions into a testable helper and make `@_all` behavior explicit.

**Files:**
- Modify: `tests/gateway/test_feishu_mention_filter.py`
- Modify: `marneo/gateway/adapters/feishu.py:831-864`

**Step 1: Write tests**

```python
def test_group_policy_disabled_rejects_group_message():
    adapter = adapter_with_identity(open_id="ou_bot")
    adapter._group_policy = "disabled"

    assert adapter._should_accept_group_message(
        raw_content="@_user_1 hello",
        mentions=[mention(open_id="ou_bot")],
    ) is False


def test_group_policy_open_accepts_without_mention():
    adapter = adapter_with_identity(open_id="ou_bot")
    adapter._group_policy = "open"

    assert adapter._should_accept_group_message(raw_content="hello", mentions=[]) is True


def test_group_policy_at_only_accepts_explicit_bot_mention():
    adapter = adapter_with_identity(open_id="ou_bot")
    adapter._group_policy = "at_only"

    assert adapter._should_accept_group_message(
        raw_content="@_user_1 hello",
        mentions=[mention(open_id="ou_bot")],
    ) is True


def test_group_policy_at_only_rejects_any_other_mention():
    adapter = adapter_with_identity(open_id="ou_bot")
    adapter._group_policy = "at_only"

    assert adapter._should_accept_group_message(
        raw_content="@_user_1 hello",
        mentions=[mention(open_id="ou_other")],
    ) is False


def test_group_policy_at_only_does_not_accept_at_all_by_default():
    adapter = adapter_with_identity(open_id="ou_bot")
    adapter._group_policy = "at_only"

    assert adapter._should_accept_group_message(raw_content="@_all hello", mentions=[]) is False


def test_group_policy_all_only_accepts_at_all():
    adapter = adapter_with_identity(open_id="ou_bot")
    adapter._group_policy = "all_only"

    assert adapter._should_accept_group_message(raw_content="@_all hello", mentions=[]) is True
```

**Step 2: Implement helper**

Add near mention helper:

```python
    def _should_accept_group_message(self, raw_content: str, mentions: list[Any]) -> bool:
        """Apply Marneo's group policy before dispatching a group message."""
        policy = (self._group_policy or "at_only").strip().lower()
        if policy == "disabled":
            return False
        if policy == "open":
            return True
        if policy == "all_only":
            return "@_all" in (raw_content or "")
        if policy == "at_only":
            return self._message_mentions_this_bot(mentions)
        log.warning("[Feishu] Unknown group_policy=%r; falling back to at_only", self._group_policy)
        return self._message_mentions_this_bot(mentions)
```

**Step 3: Replace inline group policy block**

In `_handle_message_event_data()`, replace current lines around `831-864` with:

```python
        mentioned_others: list[dict] = []
        if chat_type == "group":
            mentions = getattr(msg_body, "mentions", []) or []
            if not self._should_accept_group_message(content_str, mentions):
                log.debug(
                    "[Feishu] Group msg dropped: policy=%s chat=%s bot_open_id=%s bot_user_id=%s mentions=%d",
                    self._group_policy,
                    chat_id[:12],
                    self._bot_open_id[:12] if self._bot_open_id else "none",
                    self._bot_user_id[:12] if self._bot_user_id else "none",
                    len(mentions),
                )
                return
            mentioned_others = self._collect_non_self_mentions(mentions)
            text = self._strip_feishu_mentions(text, mentions)
```

Add helpers:

```python
    def _collect_non_self_mentions(self, mentions: list[Any]) -> list[dict[str, str]]:
        others: list[dict[str, str]] = []
        for mention in mentions or []:
            mention_id = getattr(mention, "id", None)
            open_id = str(getattr(mention_id, "open_id", "") or "").strip()
            user_id = str(getattr(mention_id, "user_id", "") or "").strip()
            name = str(getattr(mention, "name", "") or "").strip()
            if self._bot_open_id and open_id == self._bot_open_id:
                continue
            if self._bot_user_id and user_id == self._bot_user_id:
                continue
            if open_id or user_id or name:
                item = {"name": name}
                if open_id:
                    item["open_id"] = open_id
                if user_id:
                    item["user_id"] = user_id
                others.append(item)
        return others

    @staticmethod
    def _strip_feishu_mentions(text: str, mentions: list[Any]) -> str:
        cleaned = text or ""
        for mention in mentions or []:
            name = str(getattr(mention, "name", "") or "").strip()
            if name:
                cleaned = cleaned.replace(f"@{name}", "").strip()
        cleaned = re.sub(r"@_user_\d+", "", cleaned).strip()
        cleaned = cleaned.replace("@_all", "").strip()
        return cleaned
```

**Step 4: Run tests**

```bash
python3 -m pytest tests/gateway/test_feishu_mention_filter.py -q
```

Expected: PASS.

---

## Task 6: RED/GREEN — employee Feishu config round-trip preserves identity and policies

**Objective:** Ensure new employee config fields load/save safely and remain backward-compatible.

**Files:**
- Create or modify: `tests/employee/test_feishu_config.py`
- Modify: `marneo/employee/feishu_config.py`

**Step 1: Write tests**

Use `tmp_path` and monkeypatch `get_employees_dir` at module import location.

```python
from marneo.employee import feishu_config as fc


def test_feishu_config_round_trip_preserves_identity_and_policies(tmp_path, monkeypatch):
    monkeypatch.setattr(fc, "get_employees_dir", lambda: tmp_path / "employees")

    cfg = fc.EmployeeFeishuConfig(
        employee_name="laoqi",
        app_id="cli_xxx",
        app_secret="dummy",
        domain="feishu",
        bot_open_id="ou_bot",
        bot_user_id="u_bot",
        bot_name="老齐",
        dm_policy="open",
        group_policy="at_only",
        team_chat_id="oc_team",
    )

    fc.save_feishu_config(cfg)
    loaded = fc.load_feishu_config("laoqi")

    assert loaded is not None
    assert loaded.bot_open_id == "ou_bot"
    assert loaded.bot_user_id == "u_bot"
    assert loaded.bot_name == "老齐"
    assert loaded.dm_policy == "open"
    assert loaded.group_policy == "at_only"


def test_feishu_config_loads_old_files_with_safe_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(fc, "get_employees_dir", lambda: tmp_path / "employees")
    path = tmp_path / "employees" / "laoqi" / "feishu.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(
        "app_id: cli_xxx\napp_secret: dummy\ndomain: feishu\nbot_open_id: ou_bot\n",
        encoding="utf-8",
    )

    loaded = fc.load_feishu_config("laoqi")

    assert loaded is not None
    assert loaded.bot_open_id == "ou_bot"
    assert loaded.bot_user_id == ""
    assert loaded.bot_name == ""
    assert loaded.dm_policy == "open"
    assert loaded.group_policy == "at_only"
```

**Step 2: Run test**

```bash
python3 -m pytest tests/employee/test_feishu_config.py -q
```

Expected: PASS after config fields are implemented.

---

## Task 7: RED/GREEN — GatewayManager passes per-employee identity/policy into adapter config

**Objective:** Verify `GatewayManager.start_all()` actually wires new config fields from employee YAML into `FeishuChannelAdapter.connect()`.

**Files:**
- Create or modify: `tests/gateway/test_manager_employee_feishu_config.py`
- Modify: `marneo/gateway/manager.py`

**Testing strategy:** Avoid real Feishu connection. Monkeypatch:

- `marneo.employee.feishu_config.list_configured_employees`
- `marneo.employee.feishu_config.load_feishu_config`
- `marneo.gateway.adapters.feishu.FeishuChannelAdapter`
- `marneo.gateway.config.load_channel_configs`

**Step 1: Write test**

```python
import pytest

from marneo.employee.feishu_config import EmployeeFeishuConfig
from marneo.gateway.manager import GatewayManager


@pytest.mark.asyncio
async def test_gateway_manager_passes_employee_feishu_identity_and_policies(monkeypatch):
    captured = {}

    class FakeAdapter:
        platform = "feishu:laoqi"

        def __init__(self, manager, employee_name=None):
            self.manager = manager
            self.employee_name = employee_name

        async def connect(self, config):
            captured.update(config)
            return True

    def fake_load_config(employee_name):
        return EmployeeFeishuConfig(
            employee_name=employee_name,
            app_id="cli_xxx",
            app_secret="dummy",
            domain="feishu",
            bot_open_id="ou_bot",
            bot_user_id="u_bot",
            bot_name="老齐",
            dm_policy="open",
            group_policy="at_only",
        )

    monkeypatch.setattr("marneo.employee.feishu_config.list_configured_employees", lambda: ["laoqi"])
    monkeypatch.setattr("marneo.employee.feishu_config.load_feishu_config", fake_load_config)
    monkeypatch.setattr("marneo.gateway.adapters.feishu.FeishuChannelAdapter", FakeAdapter)
    monkeypatch.setattr("marneo.gateway.config.load_channel_configs", lambda: {})

    manager = GatewayManager()
    await manager.start_all()

    assert captured["bot_open_id"] == "ou_bot"
    assert captured["bot_user_id"] == "u_bot"
    assert captured["bot_name"] == "老齐"
    assert captured["dm_policy"] == "open"
    assert captured["group_policy"] == "at_only"
```

**Step 2: Run test**

```bash
python3 -m pytest tests/gateway/test_manager_employee_feishu_config.py -q
```

Expected: PASS after manager wiring exists.

---

## Task 8: Update bot identity hydration

**Objective:** Hydrate all identity fields independently without clobbering configured values.

**Files:**
- Modify: `tests/gateway/test_feishu_mention_filter.py`
- Modify: `marneo/gateway/adapters/feishu.py:564-588`

**Implementation requirement:**

Current hydration should change from:

```python
if self._bot_open_id:
    return
```

to:

```python
if self._bot_open_id and self._bot_user_id and self._bot_name:
    return
```

When `/bot/v3/info` returns data:

```python
bot = r2.json().get("bot", {})
self._bot_open_id = self._bot_open_id or bot.get("open_id", "")
self._bot_user_id = self._bot_user_id or bot.get("user_id", "")
self._bot_name = self._bot_name or bot.get("app_name", "") or bot.get("name", "")
```

Log with redacted IDs:

```python
log.info(
    "[Feishu] Bot identity: open_id=%s user_id=%s name=%s",
    self._bot_open_id[:12] if self._bot_open_id else "none",
    self._bot_user_id[:12] if self._bot_user_id else "none",
    self._bot_name or "none",
)
```

**Optional test:** mock `httpx.AsyncClient` is more brittle; for this phase, acceptable to cover hydration via a small isolated fake if existing test style supports it. Otherwise verify by code review and runtime gateway logs, then add integration tests later.

---

## Task 9: Focused and full verification

**Objective:** Prove changes do not regress Feishu gateway behavior.

**Commands:**

```bash
cd /Users/chamber/code/marneo-agent
python3 -m pytest tests/gateway/test_feishu_mention_filter.py -q
python3 -m pytest tests/employee/test_feishu_config.py tests/gateway/test_manager_employee_feishu_config.py -q
python3 -m pytest \
  tests/gateway/test_feishu_download.py \
  tests/gateway/test_feishu_streaming.py \
  tests/gateway/test_feishu_watchdog.py \
  tests/tools/test_feishu_send_file.py \
  -q
python3 -m pytest tests -q
git diff --check
```

Expected result after implementation:

```text
all tests pass
no whitespace errors
```

Current known baseline before this plan:

```text
334 passed, 8 warnings
```

---

## Task 10: Secret scan, changelog, commit

**Objective:** Commit only after tests and secret scan pass.

**Secret scan command:**

```bash
git diff --cached -- '*.py' '*.md' '*.yaml' '*.yml' '*.json' | python3 - <<'PY'
import sys, re
patterns = [
    r'[\"](sk-[A-Za-z0-9]{20,})[\" ]',
    r'api[_-]?key\s*[:=]\s*[\x22]\S{10,}',
    r'app[_-]?secret\s*[:=]\s*[\x22]\S{10,}',
    r'access[_-]?token\s*[:=]\s*[\x22]\S{10,}',
    r'refresh[_-]?token\s*[:=]\s*[\x22]\S{10,}',
    r'-----' + r'BEGIN .* PRIVATE KEY' + r'-----',
    r'Authorization:\s*Bearer\s+\S{20,}',
]
diff = sys.stdin.read()
found = []
for p in patterns:
    found.extend(re.findall(p, diff, re.IGNORECASE))
if found:
    print(f'ALERT: potential secrets found: {found}')
    sys.exit(1)
print('OK: no secrets detected')
PY
```

Commit command after review and tests:

```bash
git add \
  marneo/employee/feishu_config.py \
  marneo/gateway/manager.py \
  marneo/gateway/adapters/feishu.py \
  tests/gateway/test_feishu_mention_filter.py \
  tests/employee/test_feishu_config.py \
  tests/gateway/test_manager_employee_feishu_config.py \
  docs/plans/2026-05-06-feishu-mention-self-filter-plan.md

git commit -m "fix: tighten Feishu group mention and self-message filtering"
```

Push only after user approval:

```bash
git push origin main
```

---

## Risk Points

1. `@_all` semantics
   - Hermes routes `@_all` to the bot.
   - Marneo multi-bot groups make this risky.
   - Recommendation: keep `at_only` strict and add explicit `all_only` if needed.

2. Name fallback collision
   - Two bots can share a display name.
   - Recommendation: only use name fallback when mention payload lacks comparable IDs.

3. Hydration failure
   - Startup must not make group `at_only` permissive.
   - Recommendation: missing bot identity should drop group `at_only` messages safely rather than respond to any mention.

4. Multi-agent collaboration
   - Self-filter must not drop all bot messages.
   - Recommendation: drop only this bot's open_id/user_id; allow other bot IDs.

5. Backward compatibility
   - Existing `feishu.yaml` files only have `app_id`, `app_secret`, `domain`, `bot_open_id`, `team_chat_id`.
   - Recommendation: default new fields on load; do not require users to re-run setup.

---

## Acceptance Criteria

- `group_policy=at_only` responds only to explicit mention of this bot by open_id/user_id/name fallback rules.
- `group_policy=at_only` does not respond to any random @mention when bot identity is missing.
- `group_policy=disabled` drops group messages.
- `group_policy=open` accepts group messages.
- `group_policy=all_only` accepts `@_all` and rejects normal messages.
- Self-sent messages are dropped by open_id or user_id.
- Other bots' messages are not dropped.
- Employee Feishu config round-trips new identity and policy fields.
- Old employee Feishu config files load with safe defaults.
- GatewayManager passes per-employee identity/policy fields into adapter config.
- Full test suite passes.
- No secrets in staged diff.

---

## Deferred Work

Do not include these in this P0-1 change:

- Hermes-style `group_rules`, `admins`, `allowlist`, `blacklist`, `admin_only`.
- Inbound text batching/debounce.
- Per-employee health metrics.
- Runtime config migration CLI.
- Persisting hydrated bot identity back into `feishu.yaml` automatically.
- Webhook hardening.

These belong to later P0/P1/P2 tasks.
