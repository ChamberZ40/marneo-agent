# Marneo local web console plan

## Goal

Add a local-first web console for users who do not configure Feishu/Lark or who want to keep Marneo entirely on their machine.

The console should make Marneo usable without IM setup while preserving the current Feishu-first direction:

- Feishu remains the primary external channel.
- Local web becomes the built-in fallback / desktop console.
- CLI remains fully supported.
- All user data stays under `~/.marneo/` by default.

## Current context

Repo: `/Users/chamber/code/marneo-agent`

Relevant current implementation:

- CLI entry: `marneo/cli/app.py`
- Local terminal chat: `marneo/cli/work.py`
- Gateway manager and current health server: `marneo/gateway/manager.py`
  - existing `/health` endpoint on port `8765`
- Employee data: `~/.marneo/employees/<employee>/`
- Project data: `~/.marneo/projects/<project>/`
- Config: `~/.marneo/config.yaml`
- There is no frontend app yet; no `package.json` found.
- Existing HTTP server is health-only and should not become the full product API without structure.

## Product decision

Yes: add a local web console.

But do not position it as another external channel equivalent to Feishu. Position it as:

1. Marneo Local Console
   - local dashboard
   - chat with employees
   - setup/config management
   - project/employee browser
   - logs/status

2. Feishu Gateway
   - external workplace channel
   - multi-bot per employee
   - `feishu:<employee>` channels

This gives two clean usage modes:

```text
Local-only user:
  marneo setup
  marneo hire
  marneo web
  open http://127.0.0.1:8787

Feishu user:
  marneo setup
  marneo hire
  marneo setup feishu --employee laoqi
  marneo gateway start
```

## Proposed architecture

### Backend

Add a dedicated local web server module, separate from the IM gateway:

```text
marneo/web/
├── __init__.py
├── app.py              # aiohttp or FastAPI app factory
├── api.py              # REST endpoints
├── chat.py             # local chat session bridge
├── schemas.py          # request/response models if needed
└── static/             # built frontend bundle or simple static app
```

Add CLI command:

```text
marneo web
marneo web --host 127.0.0.1 --port 8787
marneo web --open
```

Recommended default:

- bind only to `127.0.0.1`
- no external network exposure by default
- port `8787`, to avoid conflict with gateway health port `8765`

### Frontend

Start with a small, maintainable frontend. Avoid overbuilding.

Recommended MVP stack:

- Vite + React + TypeScript
- Tailwind or plain CSS
- Build output copied/served from `marneo/web/static/`

Alternative if we want zero Node dependency at first:

- server-rendered HTML + vanilla JS
- easier packaging
- less polished but faster

Given the goal is GitHub/product polish, Vite + React is better, but only after backend API is stable.

## MVP scope

### Page 1: Home / Setup checklist

Show whether the local system is ready:

- Provider configured: yes/no
- Employee count
- Feishu configured employees
- Gateway running: yes/no
- Local web server running
- Data directory path

Actions:

- open setup instructions
- create employee shortcut
- configure Feishu shortcut
- start/restart gateway guidance

### Page 2: Employee list

Show employees from `~/.marneo/employees/`:

- name
- level
- projects count
- Feishu status
- channel id if configured, e.g. `feishu:laoqi`

### Page 3: Local chat

A browser version of `marneo work`:

- select employee
- send text message
- stream model output
- show tool calls and tool results in collapsible blocks
- support clear session

This should reuse the same core path as CLI:

- `SessionMemory(employee_name, soul=...)`
- `ChatSession(system_prompt=...)`
- existing tool registry
- `send_with_tools(...)`

Do not fork the agent logic into frontend-specific code.

### Page 4: Projects

Basic project browser:

- list projects
- show assigned employees
- show `AGENT.md` / project profile
- create project can wait until phase 2

### Page 5: Logs / status

Show:

- gateway health from `http://127.0.0.1:8765/health` if running
- connected channels
- recent gateway logs with secret redaction
- local web server status

## API design

Initial REST endpoints:

```text
GET  /api/status
GET  /api/employees
GET  /api/employees/{name}
GET  /api/projects
GET  /api/gateway/health
GET  /api/logs/gateway?lines=200
POST /api/chat/sessions
POST /api/chat/sessions/{id}/messages
GET  /api/chat/sessions/{id}/events
POST /api/chat/sessions/{id}/clear
```

For streaming, use Server-Sent Events first:

```text
GET /api/chat/sessions/{id}/events
```

SSE is simpler than WebSocket for one-way model streaming and easier to debug.

## Security rules

Local console must be safe by default:

1. Bind to `127.0.0.1` only.
2. If host is not loopback, require explicit `--host 0.0.0.0 --allow-lan` or similar.
3. Never return raw Provider API key or Feishu app secret via API.
4. Redact logs before returning them.
5. Do not expose arbitrary file browsing in MVP.
6. Add CORS disabled by default or same-origin only.
7. Add optional local token later if LAN mode is needed.

## Implementation phases

### Phase 1: Local Web MVP backend

Files likely to add/change:

- `marneo/cli/app.py`
- `marneo/cli/web_cmd.py`
- `marneo/web/__init__.py`
- `marneo/web/app.py`
- `marneo/web/api.py`
- `marneo/web/chat.py`
- `tests/web/test_web_api.py`

Deliverables:

- `marneo web` starts local server on `127.0.0.1:8787`
- `GET /api/status`
- `GET /api/employees`
- `GET /api/projects`
- `GET /api/gateway/health`
- tests pass

### Phase 2: Browser chat

Files likely to add/change:

- `marneo/web/chat.py`
- `marneo/web/api.py`
- `tests/web/test_web_chat.py`

Deliverables:

- create local chat session for employee
- send message
- stream response events via SSE
- reuse `ChatSession.send_with_tools`
- show tool events in API stream

### Phase 3: Frontend UI

Files likely to add:

```text
frontend/
├── package.json
├── index.html
├── src/
│   ├── App.tsx
│   ├── api.ts
│   ├── pages/Home.tsx
│   ├── pages/Employees.tsx
│   ├── pages/Chat.tsx
│   ├── pages/Projects.tsx
│   └── pages/Logs.tsx
└── vite.config.ts
```

Build target:

```text
marneo/web/static/
```

Add docs:

- README local-only quickstart
- `marneo web` usage

### Phase 4: Setup integration

Update `marneo setup` so after Provider setup it offers:

```text
下一步你想怎么使用 Marneo？
1. 本地浏览器使用：启动 marneo web
2. 飞书中使用：配置 marneo setup feishu
3. 两者都要
```

This is the product convergence point:

- local-only path is first-class
- Feishu path remains first-class
- user is not forced into Feishu

## Tests / validation

Run:

```bash
python3 -m pytest tests -q
python3 -m marneo.cli.app web --help
python3 -m marneo.cli.app web --port 8787
curl http://127.0.0.1:8787/api/status
curl http://127.0.0.1:8787/api/employees
```

Before commit/push:

```bash
git status --short
git diff --check
python3 -m pytest tests -q
# secret scan for api_key/app_secret/token/ticket/access_key/Bearer/private key
```

## Risks and tradeoffs

### Risk: Frontend becomes a second product too early

Mitigation:

- keep MVP focused: dashboard + employee chat + status
- do not add all admin features immediately
- do not duplicate CLI setup logic in frontend yet

### Risk: Local web exposes secrets

Mitigation:

- loopback-only default
- redact all config/log output
- no raw YAML config endpoint

### Risk: Duplicate session logic

Mitigation:

- factor common local chat runner from `marneo/cli/work.py`
- both CLI and web should share ChatSession construction

### Risk: Packaging complexity from Node frontend

Mitigation:

- Phase 1 backend can serve simple static HTML
- add Vite only when backend API is stable

## Recommendation

Build this, but call it `marneo web` or `Marneo Local Console`, not another channel.

The converged product should have two official entry points:

```text
marneo web          # local/private/browser usage
marneo gateway      # Feishu workplace usage
```

This solves the no-Feishu user path without weakening the Feishu-first strategy.
