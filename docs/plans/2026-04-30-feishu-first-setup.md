# Feishu-first Setup Implementation Plan

> For Hermes: Use subagent-driven-development skill to implement this plan task-by-task.

Goal: Make `marneo setup` deeply support Feishu as the only first-class channel for now: from Feishu app creation guidance, credential capture, employee binding, multi-bot channel identity, gateway restart, health/log verification, and next-step instructions.

Architecture: Do not generalize all IM channels yet. Keep the existing per-employee Feishu model (`~/.marneo/employees/<name>/feishu.yaml`) as the source of truth for multi-bot Feishu. Add a Feishu-specific onboarding command under `marneo setup feishu` and make `marneo setup` point users there after provider setup. Treat each employee's Feishu bot as a concrete channel id `feishu:<employee_name>` in gateway health/status output.

Tech Stack: Python, Typer, Rich, prompt_toolkit, PyYAML, pytest, existing FeishuChannelAdapter.probe_bot.

---

## Current Findings

1. Current `marneo setup` only configures LLM Provider.
   - File: `marneo/cli/setup_cmd.py:66-145`
   - Gap: no Feishu app creation guidance, no employee binding, no gateway verification.

2. Current generic channel CLI still exposes multiple platforms.
   - File: `marneo/cli/gateway_cmd.py:195-300`
   - Gap: `KNOWN_PLATFORMS = ["feishu", "wechat", "telegram", "discord"]`, but current product goal is Feishu-only depth. Generic `channels add feishu` writes a single global `channels.feishu`, which conflicts conceptually with per-employee Feishu bots.

3. Multi-Feishu-bot runtime already mostly exists via employee configs.
   - File: `marneo/employee/feishu_config.py:25-85`
   - File: `marneo/gateway/manager.py:99-123`
   - Behavior: gateway loops through `list_configured_employees()`, creates a dedicated `FeishuChannelAdapter(self, employee_name=emp_name)`, and health shows connected adapters like `feishu:<employee>`.

4. CLI help via module invocation is broken/confusing.
   - `python3 -m marneo.cli.app --help` exits 0 with no output because `marneo/cli/app.py` registers commands but has no `if __name__ == "__main__": app()` guard.

5. Existing Feishu setup command captures employee bot credentials, but it is hidden under employee command, not discoverable from setup.
   - File: `marneo/cli/employee_feishu_cmd.py:145-254`
   - Gap: not framed as end-to-end onboarding; no one-command next steps; no gateway restart/health check path.

---

## Target User Experience

Primary path:

```bash
marneo setup
```

If provider not configured:
- configure provider as today;
- then print: `下一步: marneo setup feishu`.

Feishu path:

```bash
marneo setup feishu
```

Wizard flow:

1. Explain exact Feishu app console steps:
   - create custom app / bot;
   - enable bot capability;
   - enable event subscription via WebSocket;
   - subscribe to message receive and card action events;
   - publish / install app to tenant;
   - copy App ID and App Secret.

2. Select or create employee:
   - if no employee exists, prompt to run/offer `marneo hire` first;
   - otherwise choose employee from existing list.

3. Capture Feishu app credentials:
   - app_id;
   - app_secret (password prompt);
   - domain: `feishu` default, `lark` optional;
   - optional team_chat_id.

4. Probe credentials:
   - call `FeishuChannelAdapter(GatewayManager()).probe_bot(app_id, app_secret, domain)`;
   - save `bot_open_id` when returned.

5. Save per-employee config:
   - `~/.marneo/employees/<employee>/feishu.yaml`.

6. Print concrete channel identity:
   - `channel_id = feishu:<employee>`;
   - explain that multiple Feishu robots are added by repeating `marneo setup feishu --employee <another_employee>`.

7. Restart and verify gateway optionally:
   - `marneo gateway restart`;
   - check `http://127.0.0.1:8765/health`;
   - expect `connected_channels` contains `feishu:<employee>`.

8. Print test checklist:
   - send normal text to the bot;
   - trigger `ask_user` card;
   - check `marneo gateway logs -n 80`.

---

## Task 1: Fix CLI module entry point

Objective: Make `python3 -m marneo.cli.app --help` work, reducing first-run confusion.

Files:
- Modify: `marneo/cli/app.py`
- Test: `tests/cli/test_app_entrypoint.py`

Steps:
1. Add test using subprocess:
   - command: `python3 -m marneo.cli.app --help`
   - expected: exit 0 and output contains `Marneo` and `setup`.
2. Add to bottom of `marneo/cli/app.py`:

```python
if __name__ == "__main__":
    app()
```

3. Run:

```bash
python3 -m pytest tests/cli/test_app_entrypoint.py -q
```

---

## Task 2: Add Feishu setup service helpers

Objective: Extract testable non-interactive helpers for building and saving employee Feishu config.

Files:
- Create: `marneo/cli/feishu_setup.py`
- Test: `tests/cli/test_feishu_setup.py`

Functions:

```python
def build_employee_feishu_config(employee_name: str, app_id: str, app_secret: str, domain: str = "feishu", bot_open_id: str = "", team_chat_id: str = "") -> EmployeeFeishuConfig: ...

def channel_id_for_employee(employee_name: str) -> str:
    return f"feishu:{employee_name}"

def validate_feishu_required_fields(app_id: str, app_secret: str) -> list[str]: ...
```

Tests:
- missing app_id/app_secret returns validation errors;
- domain defaults to `feishu`;
- channel id is `feishu:<employee>`.

---

## Task 3: Add `marneo setup feishu` command

Objective: Make Feishu onboarding discoverable from setup.

Files:
- Modify: `marneo/cli/setup_cmd.py`
- Use existing: `marneo/cli/employee_feishu_cmd.py`
- Test: `tests/cli/test_setup_feishu_command.py`

Implementation:
- Add `@setup_app.command("feishu")`.
- Options:
  - `--employee/-e TEXT`
  - `--app-id TEXT`
  - `--app-secret TEXT`
  - `--domain TEXT = feishu`
  - `--team-chat-id TEXT = ""`
  - `--no-probe`
  - `--restart-gateway/--no-restart-gateway`
- If options are supplied, run non-interactively and save config.
- If missing, use interactive prompts.

Expected command:

```bash
marneo setup feishu --employee laoqi --app-id cli_xxx --app-secret '***' --no-probe --no-restart-gateway
```

Expected output:
- saved path: `~/.marneo/employees/laoqi/feishu.yaml`
- channel id: `feishu:laoqi`
- next command: `marneo gateway restart`.

---

## Task 4: Make setup summary Feishu-first

Objective: After provider setup, point users to Feishu instead of generic work/hire only.

Files:
- Modify: `marneo/cli/setup_cmd.py:142-145`

Change final output to:

```text
✓ Provider 配置已保存 → ~/.marneo/config.yaml
下一步：
  1. marneo hire                     # 创建数字员工
  2. marneo setup feishu             # 给员工绑定飞书机器人
  3. marneo gateway restart          # 启动/重启网关
  4. marneo gateway status           # 查看连接状态
```

---

## Task 5: Deprecate generic non-Feishu channel setup in UX, not runtime

Objective: Avoid product focus drift while preserving code compatibility.

Files:
- Modify: `marneo/cli/gateway_cmd.py:195-300`

Change:
- keep existing adapters untouched;
- change help text to mark wechat/telegram/discord as experimental/hidden or remove them from default display;
- make `gateway channels add` recommend `marneo setup feishu` when platform is `feishu`.

Do not delete runtime adapters yet.

---

## Task 6: Improve gateway status for multiple Feishu bots

Objective: Show per-employee channel identity clearly.

Files:
- Modify: `marneo/cli/gateway_cmd.py:166-179`
- Maybe modify: `marneo/gateway/manager.py:156-176`

Status output should show:

```text
网关运行中 PID=...
Feishu bots:
  ✓ laoqi     channel=feishu:laoqi
  ✓ xiaoa2hao channel=feishu:xiaoa2hao
Health: http://127.0.0.1:8765/health
```

Tests:
- unit test formatting helper without real gateway.

---

## Task 7: Add end-to-end verification command

Objective: Add `marneo setup doctor` or `marneo setup feishu --doctor` to validate the setup without exposing secrets.

Checks:
- provider configured;
- at least one employee exists;
- each configured employee has Feishu config;
- app_id present, app_secret redacted;
- gateway running;
- health endpoint reachable;
- connected_channels contains `feishu:<employee>`;
- latest logs include `[Gateway] employee <name> feishu: connected` or failure reason.

Files:
- Modify: `marneo/cli/setup_cmd.py`
- Test: `tests/cli/test_setup_doctor.py`

---

## Non-goals for this phase

- Do not build generic multi-channel onboarding.
- Do not require webhook support; Marneo Feishu mainline is WebSocket-first.
- Do not redesign all Hermes binding schema now.
- Do not store Feishu credentials in global `channels.feishu` for multi-bot; use per-employee config as source of truth.
- Do not expose app_secret or WebSocket URLs in status/log output.

---

## Verification Checklist

Run after implementation:

```bash
python3 -m pytest tests/cli/test_app_entrypoint.py tests/cli/test_feishu_setup.py tests/cli/test_setup_feishu_command.py -q
python3 -m pytest tests/gateway/test_feishu_watchdog.py tests/gateway/test_pending_questions.py tests/tools/test_ask_user.py -q
python3 -m pytest -q
git diff --check
python3 -m marneo.cli.app --help
python3 -c 'from marneo.cli.app import app; app()' setup --help
python3 -c 'from marneo.cli.app import app; app()' setup feishu --help
```

Runtime verification:

```bash
python3 -c 'from marneo.cli.app import app; app()' gateway restart
python3 - <<'PY'
import json, urllib.request
print(urllib.request.urlopen('http://127.0.0.1:8765/health', timeout=3).read().decode())
PY
```

Expected:
- `connected_channels` contains one entry per configured Feishu employee bot, e.g. `feishu:laoqi`, `feishu:xiaoa2hao`.
