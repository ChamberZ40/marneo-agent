# Marneo Supervised Gateway Runtime v1 Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task after user review.

**Goal:** Upgrade Marneo Gateway from a best-effort platform bot process into a supervised, observable, recoverable runtime foundation for Feishu, local CLI, web/API, and future channels.

**Architecture:** Gateway becomes Marneo's long-running runtime boundary. Platform adapters own only connectivity, event normalization, and send capability; Gateway Runtime owns process state, locks, health/status, lifecycle, dispatch, activity tracking, and graceful shutdown. Feishu remains the first production channel proving the runtime, but Feishu must not be the runtime itself.

**Tech Stack:** Python 3.11+, Typer CLI, asyncio, systemd user service, macOS launchd LaunchAgent, pytest, JSON runtime state under `~/.marneo/`.

---

## Current Repository State

Inspected on 2026-05-07 at `/Users/chamber/code/marneo-agent`.

Current local WIP exists:

```text
M marneo/gateway/adapters/feishu.py
M tests/gateway/test_feishu_watchdog.py
```

Do not overwrite or revert this WIP while implementing this plan unless explicitly requested.

Relevant current files:

```text
marneo/cli/gateway_cmd.py
marneo/gateway/manager.py
marneo/gateway/base.py
marneo/gateway/adapters/feishu.py
deploy/marneo-gateway.service
deploy/com.marneo.gateway.plist
tests/gateway/
```

Current limitations observed:

1. `marneo/cli/gateway_cmd.py` owns too much runtime behavior.
   - PID helpers live in CLI.
   - `_gateway_runner()` is inside CLI command file.
   - `start` uses `subprocess.Popen(... start_new_session=True)` as a lightweight daemon.
   - `install-service` only copies static templates and prints follow-up commands.

2. Runtime state is minimal.
   - Only `~/.marneo/gateway.pid` exists.
   - No structured `gateway_state.json`.
   - `status` mostly checks PID and last log line.

3. Service templates are not production-safe enough.
   - `deploy/marneo-gateway.service` uses `/usr/bin/python3 -m marneo gateway start --fg`.
   - For a console script package, preferred command should resolve the installed `marneo` executable or generated absolute command.
   - macOS plist logs to `/tmp/marneo-gateway*.log` instead of `~/.marneo/logs/`.

4. `GatewayManager` is a partial runtime but not a full supervised runtime.
   - It registers adapters, starts channels, exposes `/health`, dispatches messages.
   - It has health payload logic, but runtime status writing and lifecycle semantics are absent.
   - Health server binds `0.0.0.0` by default at line area `manager.py:260`; v1 should prefer loopback unless explicitly configured.

5. `BaseChannelAdapter` is too small for runtime status.
   - Current interface: `connect`, `disconnect`, `send_reply`, `is_running`.
   - Missing `channel_id`, `employee`, `status_snapshot`, structured state, error/restart counters.

6. Inbound reliability is partially implemented inside `GatewayManager`.
   - Dedup TTL is only 60 seconds.
   - Per-session lock exists through `SessionStore`.
   - No standalone inbound pipeline modules yet.
   - No active agent heartbeat/status.

---

## Product Principle

Use this as the guiding sentence in code review and docs:

```text
The gateway is not a Feishu bot loop. It is Marneo's supervised runtime boundary.

All external channels are lifecycle-managed adapters. The runtime owns process
supervision, status, locks, health, dispatch, activity tracking, and graceful
shutdown. Platform adapters own connectivity and normalization only.
```

Chinese wording:

```text
Gateway 不是飞书机器人的循环脚本，而是 Marneo 的长期运行边界。
所有外部通道都作为生命周期受管理的 Adapter 接入 Gateway Runtime。
Runtime 负责进程守护、状态、锁、健康检查、消息分发、活动追踪和优雅关闭；
平台 Adapter 只负责连接、事件标准化和发送。
```

---

## Non-Goals for v1

Do not include these in v1:

- More Feishu event types unless needed by status/lifecycle tests.
- New card/ask_user UX.
- Web frontend UI.
- New LLM/provider behavior.
- Full Hermes parity.
- Actual service installation during tests.
- Exposing raw config YAML or raw logs through HTTP.
- Binding health/status to `0.0.0.0` by default.

---

## Target Runtime Layout

Add or evolve toward:

```text
marneo/gateway/
  runtime.py              # GatewayRuntime orchestration; may wrap/replace GatewayManager gradually
  status.py               # PID, gateway_state.json, runtime records
  locks.py                # gateway single-instance and platform identity locks
  health.py               # Health/status dataclasses and payload builders
  supervisor.py           # systemd/launchd install/start/stop/restart/status helpers
  lifecycle.py            # signal handling, planned vs unexpected shutdown
  activity.py             # active agent run tracking and heartbeat
  inbound/
    __init__.py
    dedup.py
    queue.py
    locks.py
    batching.py
    policy.py
  adapters/
    base.py               # optional future split from gateway/base.py
    feishu.py
```

The v1 can be incremental. It does not need to rename `GatewayManager` immediately. Prefer adding focused modules and then letting `GatewayManager` call them.

---

## Runtime State Schema

Write state under `~/.marneo/gateway_state.json`.

Example:

```json
{
  "kind": "marneo-gateway",
  "pid": 12345,
  "start_time": "2026-05-07T15:00:00Z",
  "updated_at": "2026-05-07T15:10:00Z",
  "gateway_state": "running",
  "exit_reason": null,
  "restart_requested": false,
  "active_agents": 1,
  "channels": {
    "feishu:xiaoa2hao": {
      "channel_id": "feishu:xiaoa2hao",
      "platform": "feishu",
      "employee": "xiaoa2hao",
      "state": "connected",
      "connected": true,
      "started_at": "2026-05-07T15:00:03Z",
      "updated_at": "2026-05-07T15:10:00Z",
      "last_event_at": "2026-05-07T15:09:31Z",
      "last_event_age_seconds": 29,
      "restart_count": 0,
      "last_restart_reason": null,
      "last_error_code": null,
      "last_error_message": null,
      "retryable": true
    }
  }
}
```

Required redaction rule: state must never contain Feishu `app_secret`, access tokens, WebSocket tickets, provider API keys, Authorization headers, or raw secret config.

---

## PR Breakdown

### PR 1: Gateway Status, PID, Runtime State, and Locks

**Objective:** Establish the runtime ground truth: process identity, structured state, and duplicate-run protection.

**Files:**

- Create: `marneo/gateway/status.py`
- Create: `marneo/gateway/locks.py`
- Create: `marneo/gateway/health.py`
- Modify: `marneo/cli/gateway_cmd.py`
- Modify: `marneo/gateway/manager.py`
- Test: `tests/gateway/test_gateway_status.py`
- Test: `tests/gateway/test_gateway_locks.py`
- Test: update `tests/gateway/test_health.py` if needed

#### Task 1.1: Move PID path logic out of CLI

Create `marneo/gateway/status.py` with path helpers:

```python
from __future__ import annotations

from pathlib import Path
from marneo.core.paths import get_marneo_dir

GATEWAY_KIND = "marneo-gateway"
RUNTIME_STATUS_FILE = "gateway_state.json"
PID_FILE = "gateway.pid"


def get_pid_path() -> Path:
    return get_marneo_dir() / PID_FILE


def get_runtime_status_path() -> Path:
    return get_marneo_dir() / RUNTIME_STATUS_FILE


def get_logs_dir() -> Path:
    path = get_marneo_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_gateway_log_path() -> Path:
    return get_logs_dir() / "gateway.log"
```

Move CLI `_pid_file()` and `_log_file()` callers to this module. Keep backward compatibility by optionally reading old `~/.marneo/gateway.log` in `logs` command if new log does not exist.

Test:

```bash
python3 -m pytest tests/gateway/test_gateway_status.py -q
```

Expected: path helpers use a monkeypatched HOME and create paths under that temp `.marneo`.

#### Task 1.2: Write structured runtime status

Add these functions to `marneo/gateway/status.py`:

```python
def write_pid_file(pid: int | None = None) -> None: ...
def read_pid_file() -> int | None: ...
def is_process_alive(pid: int) -> bool: ...
def remove_pid_file() -> None: ...
def write_runtime_status(**fields: object) -> None: ...
def read_runtime_status() -> dict[str, object] | None: ...
def update_channel_status(channel_id: str, status: dict[str, object]) -> None: ...
```

Behavior:

- `write_runtime_status()` merges fields into existing JSON.
- Always updates `pid` and `updated_at`.
- Initializes defaults: `kind`, `gateway_state`, `channels`, `active_agents`, `restart_requested`, `exit_reason`.
- Writes atomically using temp file + replace.
- If JSON is corrupt, rewrite a valid state instead of crashing status command.

Tests:

```bash
python3 -m pytest tests/gateway/test_gateway_status.py -q
```

Cases:

- writes default record
- merges state
- updates channel status without removing other channels
- corrupt JSON is recovered
- secrets are not present in output when passed through redaction helper

#### Task 1.3: Add gateway runtime lock

Create `marneo/gateway/locks.py`.

Minimum API:

```python
@dataclass
class LockHandle:
    path: Path
    fd: object
    metadata: dict[str, object]


def acquire_gateway_lock() -> LockHandle:
    ...


def release_lock(handle: LockHandle) -> None:
    ...


def acquire_scoped_lock(scope: str, identity: str, metadata: dict[str, object] | None = None) -> LockHandle:
    ...
```

Implementation requirements:

- Use `fcntl.flock` on POSIX.
- Put gateway lock at `~/.marneo/gateway.lock`.
- Put scoped locks under `~/.marneo/gateway-locks/<scope>/<sha256(identity)>.lock`.
- Lock file JSON must include pid, scope, identity_hash, metadata, updated_at.
- Never write raw identity if it may be an app_id or token; use hash.

Tests:

```bash
python3 -m pytest tests/gateway/test_gateway_locks.py -q
```

Cases:

- first gateway lock succeeds
- second lock in same process or subprocess fails cleanly
- scoped lock hashes identity
- lock release allows reacquire

#### Task 1.4: Use status and lock in gateway runner

Modify `marneo/cli/gateway_cmd.py` and/or add `marneo/gateway/runtime.py`.

Desired runner behavior:

```text
acquire gateway lock
write pid file
write runtime status: starting
load tools
start GatewayManager
write runtime status: running
on graceful stop: stopping -> stopped, remove pid
on exception: failed with redacted error, exit non-zero
release lock
```

Important: avoid burying runtime runner inside CLI long-term. If low-risk, create:

```text
marneo/gateway/runtime.py
```

with:

```python
def run_gateway_foreground() -> int:
    ...
```

Then CLI calls it.

Tests:

- Unit-test status functions rather than starting a real long-running gateway.
- Existing gateway tests must still pass.

Verification:

```bash
python3 -m pytest tests/gateway/test_gateway_status.py tests/gateway/test_gateway_locks.py tests/gateway/test_health.py -q
python3 -m pytest tests -q
```

---

### PR 2: Service Supervisor Install/Start/Stop/Restart/Status

**Objective:** Replace ad-hoc backgrounding with service-manager-aware lifecycle commands.

**Files:**

- Create: `marneo/gateway/supervisor.py`
- Modify: `marneo/cli/gateway_cmd.py`
- Modify: `deploy/marneo-gateway.service`
- Modify: `deploy/com.marneo.gateway.plist`
- Test: `tests/gateway/test_supervisor.py`

#### Task 2.1: Add supervisor abstraction

Create `marneo/gateway/supervisor.py`:

```python
class SupervisorKind(str, Enum):
    SYSTEMD_USER = "systemd_user"
    LAUNCHD_USER = "launchd_user"
    POPEN_FALLBACK = "popen_fallback"


def detect_supervisor() -> SupervisorKind: ...
def render_systemd_service(marneo_cmd: str, home: Path) -> str: ...
def render_launchd_plist(marneo_cmd: str, home: Path) -> str: ...
def install_service() -> Path: ...
def start_service() -> None: ...
def stop_service() -> None: ...
def restart_service() -> None: ...
def service_status() -> dict[str, object]: ...
```

Use dynamic rendering instead of copying templates blindly. Static templates may remain as reference but generated output must include the actual current executable path.

#### Task 2.2: Update CLI command names

Preferred CLI:

```bash
marneo gateway run       # foreground
marneo gateway start     # service start if installed, else fallback/background with warning
marneo gateway stop
marneo gateway restart
marneo gateway status
marneo gateway install   # preferred name
marneo gateway install-service  # keep as alias for compatibility
marneo gateway logs
```

`start --fg` can remain temporarily but should point users to `run`.

#### Task 2.3: Fix service templates

Linux user service should be user-service safe:

```ini
[Unit]
Description=Marneo Gateway
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/absolute/path/to/marneo gateway run
Restart=on-failure
RestartSec=5
WorkingDirectory=%h
Environment=HOME=%h
StandardOutput=append:%h/.marneo/logs/gateway.log
StandardError=append:%h/.marneo/logs/gateway.log

[Install]
WantedBy=default.target
```

Do not include `User=%i` in a user service.

macOS plist should use:

```text
ProgramArguments: /absolute/path/to/marneo gateway run
RunAtLoad: true
KeepAlive: true
StandardOutPath: ~/.marneo/logs/gateway.log
StandardErrorPath: ~/.marneo/logs/gateway.log
WorkingDirectory: $HOME
```

Tests should assert rendered content only; never call real `systemctl` or `launchctl`.

Verification:

```bash
python3 -m pytest tests/gateway/test_supervisor.py -q
python3 -m pytest tests -q
```

---

### PR 3: Runtime and Adapter Status Interface

**Objective:** Introduce structured channel status so Feishu/local/web/API can be managed consistently.

**Files:**

- Modify: `marneo/gateway/base.py`
- Create or modify: `marneo/gateway/health.py`
- Modify: `marneo/gateway/manager.py`
- Modify: `marneo/gateway/adapters/feishu.py`
- Test: `tests/gateway/test_runtime.py`
- Test: `tests/gateway/test_health.py`

#### Task 3.1: Add `ChannelStatus`

Add to `marneo/gateway/base.py` or `marneo/gateway/health.py`:

```python
@dataclass
class ChannelStatus:
    channel_id: str
    platform: str
    employee: str = ""
    state: str = "stopped"
    connected: bool = False
    started_at: float | None = None
    last_event_at: float | None = None
    restart_count: int = 0
    last_restart_reason: str | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None
    retryable: bool = True

    def to_dict(self, now: float | None = None) -> dict[str, object]: ...
```

`to_dict()` should include `last_event_age_seconds` when `last_event_at` exists.

#### Task 3.2: Extend adapter base interface

Add defaults to `BaseChannelAdapter`:

```python
@property
def channel_id(self) -> str:
    return self.platform

@property
def employee(self) -> str:
    return ""

def status_snapshot(self) -> ChannelStatus:
    return ChannelStatus(
        channel_id=self.channel_id,
        platform=self.platform,
        employee=self.employee,
        state="connected" if self.is_running else "stopped",
        connected=self.is_running,
    )
```

No adapter should be forced to implement everything immediately.

#### Task 3.3: Make health payload use `status_snapshot()`

Modify `GatewayManager.health_payload()` so `channels_detail` comes primarily from adapter `status_snapshot()`, while preserving Feishu-specific nested debug fields only under a redacted `debug` key if needed.

Target endpoints:

```text
/healthz  -> {"ok": true}
/readyz   -> {"ready": bool, "connected_channels": [...]}
/status   -> full redacted status
/health   -> backward-compatible alias to /status for now
```

Tests:

```bash
python3 -m pytest tests/gateway/test_health.py tests/gateway/test_runtime.py -q
```

---

### PR 4: Inbound Reliability Pipeline

**Objective:** Move message reliability concerns out of ad-hoc manager logic and into testable modules.

**Files:**

- Create: `marneo/gateway/inbound/__init__.py`
- Create: `marneo/gateway/inbound/dedup.py`
- Create: `marneo/gateway/inbound/locks.py`
- Create: `marneo/gateway/inbound/queue.py`
- Create: `marneo/gateway/inbound/batching.py`
- Modify: `marneo/gateway/manager.py`
- Test: `tests/gateway/test_inbound_dedup.py`
- Test: `tests/gateway/test_inbound_pipeline.py`

#### Task 4.1: Extract dedup with production TTL

Current `DEDUP_TTL = 60` in `manager.py` is too short for long-running gateway semantics.

Create `MessageDedupCache`:

```python
class MessageDedupCache:
    def __init__(self, ttl_seconds: int = 24 * 60 * 60, max_size: int = 5000): ...
    def seen(self, msg_id: str, now: float | None = None) -> bool: ...
    def prune(self, now: float | None = None) -> None: ...
```

Keep default TTL 24h.

#### Task 4.2: Extract per-chat locks

Create `ChatLockRegistry` keyed by `(platform/channel_id, chat_id)`:

```python
class ChatLockRegistry:
    def get(self, channel_id: str, chat_id: str) -> asyncio.Lock: ...
    def prune(self) -> None: ...
```

Reuse current `SessionStore` lock if easier, but expose the concept clearly for runtime.

#### Task 4.3: Add bounded pending queue primitive

Create `PendingInboundQueue`:

```python
class PendingInboundQueue:
    def __init__(self, max_depth: int = 1000): ...
    def push(self, item: ChannelMessage) -> None: ...
    def drain(self) -> list[ChannelMessage]: ...
    def __len__(self) -> int: ...
```

Drop oldest beyond max depth and count drops.

#### Task 4.4: Keep text batching platform-local for now

Feishu already has text batching. Do not force generic batching in v1 unless tests prove it is safe. Instead document the generic interface and move later.

Verification:

```bash
python3 -m pytest tests/gateway/test_inbound_dedup.py tests/gateway/test_inbound_pipeline.py tests/gateway/test_manager.py -q
python3 -m pytest tests -q
```

---

### PR 5: Feishu Adapter as Runtime Channel

**Objective:** Make Feishu report and obey runtime lifecycle without becoming the runtime.

**Files:**

- Modify: `marneo/gateway/adapters/feishu.py`
- Modify: `marneo/gateway/manager.py`
- Test: `tests/gateway/test_feishu_watchdog.py`
- Test: `tests/gateway/test_feishu_adapter_runtime.py`

#### Task 5.1: Add Feishu `channel_id`

For per-employee Feishu adapters:

```text
feishu:<employee_name>
```

For legacy/global config:

```text
feishu
```

Do not key all adapters only by `platform="feishu"`, otherwise multi-employee status overwrites channels. If `GatewayManager._adapters` currently uses platform key, migrate carefully:

```python
self._adapters[adapter.channel_id] = adapter
```

Then dispatch lookup must use `msg.platform` or a new `msg.channel_id` field. To avoid breaking everything in one PR, add `channel_id` to `ChannelMessage` with default `platform`.

#### Task 5.2: Implement `status_snapshot()` in Feishu

Feishu status should expose:

```text
state
connected
last_event_at / age
pending_inbound
pending_text_batches
ws.future_done
ws.client_present
ws.conn_present
ws.conn_closed
ws.conn_close_code
ws.connection_lost
ws_restart.restart_count
ws_restart.last_reason
card_action metrics if available
pending_questions if available
```

All values must be redacted.

#### Task 5.3: Use scoped Feishu app lock

When connecting Feishu adapter:

```python
acquire_scoped_lock("feishu-app", app_id, {"employee": employee_name, "channel_id": channel_id})
```

Do not write raw app_id into lock file; only hash.

Release on disconnect.

#### Task 5.4: Keep idle as observation only

Regression requirement:

- No restart just because no message arrived for 5 minutes.
- Restart only on structural death signals like future done, conn closed, conn missing outside startup grace, close_code set, or explicit SDK failure.

This matches the current watchdog WIP direction and must stay true.

Verification:

```bash
python3 -m pytest tests/gateway/test_feishu_watchdog.py tests/gateway/test_feishu_adapter_runtime.py -q
python3 -m pytest tests -q
```

---

### PR 6: Activity Heartbeat, Doctor, Docs, and Soak Checklist

**Objective:** Make long agent runs visible and make support diagnosis first-class.

**Files:**

- Create: `marneo/gateway/activity.py`
- Modify: agent execution path used by `GatewayManager._process()`
- Create or modify: `marneo/cli/doctor_cmd.py`
- Modify: `marneo/cli/app.py`
- Modify: `README.md`
- Modify: `README_CN.md`
- Test: `tests/gateway/test_activity.py`
- Test: `tests/cli/test_doctor.py`

#### Task 6.1: Add active run tracker

Create:

```python
@dataclass
class ActiveRun:
    run_id: str
    channel_id: str
    chat_id: str
    employee: str
    started_at: float
    last_activity_at: float
    phase: str
    tool_name: str | None = None
    message_id: str | None = None

class ActivityTracker:
    def start_run(...): ...
    def heartbeat(run_id: str, phase: str, tool_name: str | None = None): ...
    def finish_run(run_id: str): ...
    def snapshot(self) -> dict[str, object]: ...
```

Integrate at least around `GatewayManager._process()`:

- start when processing begins
- heartbeat before/after tool events if accessible
- finish in `finally`
- include active run count in runtime state/status

#### Task 6.2: Add `marneo doctor`

Doctor should check:

- Python version
- Marneo version
- `~/.marneo` exists/writable
- config path exists
- provider configured yes/no with redacted hint only
- employee count
- Feishu configured employee count
- gateway pid/status
- gateway state file
- health endpoint `127.0.0.1:8765/status` if running
- recent logs with redaction

Never print secrets.

#### Task 6.3: Add soak test checklist

Add docs section to README/README_CN or a dedicated doc:

```text
2h quiet-idle test
12h overnight test
24h production soak
manual send-after-idle test
restart storm check
memory growth check
card/ask_user separate validation
```

Verification:

```bash
python3 -m pytest tests/gateway/test_activity.py tests/cli/test_doctor.py -q
python3 -m pytest tests -q
git diff --check
```

---

## Acceptance Criteria for v1

The v1 should be considered done only when:

1. `marneo gateway run` starts foreground runtime and writes:
   - `~/.marneo/gateway.pid`
   - `~/.marneo/gateway_state.json`
   - `~/.marneo/logs/gateway.log`

2. `marneo gateway status` shows:
   - running/stopped
   - pid
   - gateway state
   - connected channels
   - per-channel state
   - last error/restart reason if present

3. A second gateway in the same Marneo home fails fast with a clear lock error.

4. A duplicate Feishu app identity fails fast or refuses second connection.

5. Service install renders correct systemd/launchd files with absolute command paths.

6. `/healthz`, `/readyz`, and `/status` exist and are redacted.

7. Feishu adapter reports channel status without leaking secrets.

8. Idle Feishu channels do not restart merely due to silence.

9. Long agent processing is visible as active activity in status.

10. Full deterministic tests pass:

```bash
python3 -m pytest tests -q
git diff --check
```

Before commit/push also run the user's preferred secret scan over staged/HEAD files.

---

## Risk Notes

1. Multi-employee adapter keying is risky.
   - Current manager stores `_adapters` by `adapter.platform`.
   - If multiple Feishu employees all have `platform="feishu"`, later registrations can overwrite earlier ones.
   - Migrate to `channel_id` carefully and keep backward compatibility for legacy tests.

2. Service commands can be platform-specific.
   - Tests must not call real `systemctl`/`launchctl`.
   - Render and command-building should be unit-tested.

3. PID files can go stale.
   - Always validate PID liveness.
   - Only remove PID file if it belongs to the current process or is stale.

4. State files can corrupt on crash.
   - Use atomic writes.
   - Make `read_runtime_status()` tolerate corrupt JSON.

5. Secrets can leak through exception strings.
   - Centralize redaction.
   - Apply redaction before writing status/log snippets/doctor output.

6. Do not let SDK reconnect and gateway reconnect fight.
   - Feishu lifecycle should have one owner: gateway/adapter watchdog.
   - Idle time is observability, not death.

---

## Implementation Order Recommendation

Recommended order for actual execution:

```text
1. status.py path + JSON state helpers
2. locks.py gateway + scoped locks
3. CLI status/start/run integration with new status helpers
4. health.py ChannelStatus dataclass and status payload
5. supervisor.py render-only tests, then CLI install/start/stop wiring
6. adapter channel_id/status_snapshot migration
7. Feishu scoped app lock and status snapshot
8. inbound dedup extraction
9. activity tracker
10. doctor/docs/soak checklist
```

Keep PRs small. Avoid mixing service supervisor, Feishu state machine, and inbound pipeline in one commit.

---

## Design Summary for PR Description

```text
This change begins Marneo's Gateway-first architecture by treating the gateway as
a supervised runtime boundary instead of a Feishu-specific bot loop. The runtime
will own process state, locks, health/status, service supervision, dispatch,
activity tracking, and graceful shutdown. Channel adapters will own only platform
connectivity, event normalization, and send behavior.

The v1 plan introduces structured runtime state, PID and scoped locks, service
manager integration, channel status snapshots, reliable inbound primitives,
agent activity heartbeat, and redacted doctor/status output. Feishu remains the
first production channel, but it becomes a lifecycle-managed adapter rather than
an implicit gateway runtime.
```
