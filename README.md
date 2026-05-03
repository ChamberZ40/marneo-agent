# Marneo Agent

<div align="center">

**Feishu-first digital employees for real work.**

Marneo turns AI agents into named, project-aware digital employees that can work in Feishu/Lark, run locally from your terminal, use tools, remember context, collaborate in teams, and stay under your control.

[![Python](https://img.shields.io/badge/Python-3.11+-blue)](https://python.org)
[![Status](https://img.shields.io/badge/status-active-FF6611)](#)
[![Local First](https://img.shields.io/badge/local--first-supported-00cc99)](#local-onlyprivate-mode)

[English](README.md) · [中文](README_CN.md)

</div>

---


### One-line pitch

Marneo is a Feishu-first digital employee system for real work: hire named AI employees, assign them to projects, connect each employee to a dedicated Feishu/Lark bot, run them locally from your terminal or browser, and keep sensitive work under your control.

### What makes Marneo different

Marneo is built around digital employees, not one generic assistant.

| Area | Generic assistant | Marneo |
|---|---|---|
| Identity | One assistant | Multiple named employees with roles and growth records |
| Work model | Conversation-centric | Project-, employee-, team-, report-, and tool-centric |
| Context | Prompt keeps growing | Fixed budget + retrieval + layered memory |
| Feishu/Lark | Usually one bot | Per-employee bot, channel is `feishu:<employee>` |
| Local use | Often secondary | `marneo work` and `marneo web` are first-class |
| Privacy | Provider defaults | local-only/private mode with external-tool gating |

### Product model

Marneo intentionally keeps the official surface small:

```text
marneo work      # local CLI channel, no Feishu required
marneo web       # local loopback browser console over local Marneo data
marneo gateway   # Feishu/Lark workplace gateway
```

`marneo web` is a local console over the same employee/project/status data used by `marneo work`; it is not a new external messaging channel.

### Quick start

Install with the one-line installer:

```bash
curl -fsSL https://raw.githubusercontent.com/ChamberZ40/marneo-agent/main/scripts/install.sh | bash
```

Install only, without launching setup:

```bash
curl -fsSL https://raw.githubusercontent.com/ChamberZ40/marneo-agent/main/scripts/install.sh | bash -s -- --skip-setup
```

Common environment variables:

```bash
MARNEO_HOME=~/.marneo
MARNEO_INSTALL_DIR=~/.marneo/marneo-agent
MARNEO_INSTALL_DRY_RUN=1
```

Then run:

```bash
marneo setup
marneo hire
```

Local CLI:

```bash
marneo work
marneo work --employee laoqi
```

Local browser console:

```bash
marneo web
# http://127.0.0.1:8787 by default
```

Feishu/Lark gateway:

```bash
marneo setup feishu --employee laoqi
marneo gateway start
marneo gateway status
```

Expected channel:

```text
feishu:laoqi
```

### Local-only/private mode

Use a local OpenAI-compatible provider such as Ollama and disable external network tools:

```bash
marneo setup local --model llama3.3
marneo setup local --base-url http://127.0.0.1:11434/v1 --model qwen2.5-coder:7b
```

This writes:

```yaml
privacy:
  local_only: true
```

In local-only/private mode, the provider must be localhost/loopback. Runtime gating disables external network tools such as web_fetch / web_search, lark_cli, Feishu, ask_user, and MCP while keeping local file and bash tools available. The local `marneo web` console itself remains usable because it binds to loopback by default.

### Multiple Feishu/Lark bots

Marneo's recommended mapping is:

```text
one employee = one employee identity = one Feishu/Lark bot config = one channel
```

Example:

```text
~/.marneo/employees/laoqi/feishu.yaml  -> feishu:laoqi
~/.marneo/employees/aria/feishu.yaml   -> feishu:aria
~/.marneo/employees/ops/feishu.yaml    -> feishu:ops
```

Workflow:

```bash
marneo hire
marneo setup feishu --employee laoqi

marneo hire
marneo setup feishu --employee aria

marneo gateway restart
marneo gateway status
```

### Feishu/Lark capabilities

| Capability | Status |
|---|---|
| WebSocket gateway | Supported |
| Text messages | Supported |
| Markdown / rich post replies | Supported |
| Image / file download | Supported |
| Per-chat serial processing | Supported |
| Disk-persistent dedup | Supported |
| Reaction lifecycle | Supported |
| ask_user interactive cards | Supported |
| CardKit updates | Uses PUT |
| CARD WebSocket monkey patch | Disabled by default, opt-in only |

### Architecture

```text
Feishu / Lark
    ↓ WebSocket events
FeishuChannelAdapter
    ↓ ChannelMessage(platform=feishu:<employee>)
GatewayManager
    ├─ dedup
    ├─ per-chat lock
    ├─ session routing
    ↓
ChatSession
    ├─ provider streaming
    ├─ multimodal blocks
    ├─ tool-calling loop
    ↓
Tool Registry
    ├─ bash / files / web_fetch
    ├─ lark_cli
    └─ ask_user
    ↓
Feishu reply / card / file / markdown
```

Local path:

```text
Terminal / Browser
    ├─ marneo work
    └─ marneo web 127.0.0.1:8787
          ↓
Local employee / project / status APIs
          ↓
~/.marneo data directory
```

### Data directory

```text
~/.marneo/
├── config.yaml
├── gateway.pid
├── gateway.log
├── employees/
│   └── <employee>/
│       ├── profile.yaml
│       ├── SOUL.md
│       ├── feishu.yaml
│       ├── memory/
│       └── reports/
├── projects/
│   └── <project>/
│       ├── project.yaml
│       ├── AGENT.md
│       └── skills/
└── skills/
```

Do not commit local runtime data, real credentials, gateway logs, customer files, or chat records.

### Development

```bash
git clone git@github.com:ChamberZ40/marneo-agent.git
cd marneo-agent
python3 -m pip install -e '.[dev]'
python3 -m pytest tests -q
```

Before committing or pushing:

```bash
git diff --check
python3 -m pytest tests -q
```

Also scan staged files for provider keys, Feishu secrets, access tokens, WebSocket tickets, authorization headers, and private key blocks.

---

## License

License information is defined by the repository owner. Add a `LICENSE` file before publishing a formal release.
