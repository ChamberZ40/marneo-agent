# Marneo Agent

<div align="center">

**Feishu-first digital employees for real work.**

Marneo turns AI agents into named, project-aware digital employees that can work in Feishu/Lark, run locally from your terminal, use tools, remember context, collaborate in teams, and stay under your control.

[![Python](https://img.shields.io/badge/Python-3.11+-blue)](https://python.org)
[![Status](https://img.shields.io/badge/status-active-FF6611)](#)
[![Local First](https://img.shields.io/badge/local--first-supported-00cc99)](#local-onlyprivate-模式)

[中文](#中文) · [English](#english)

</div>

---

## 中文

### 一句话说明

Marneo 是一个面向真实工作的「数字员工」系统：你可以招聘多个 AI 员工，把他们分配到项目，让他们通过飞书机器人在线工作，也可以在本地 CLI / Web Console 里直接协作。

它不是一个泛泛的聊天机器人，也不是一个把所有东西都塞进 system prompt 的个人助理。Marneo 的核心是：员工身份、项目上下文、工具执行、记忆、团队协作、Feishu-first 工作入口。

### 为什么做 Marneo

很多 Agent 系统默认从「一个助手」出发；Marneo 从「一个组织里的多个员工」出发。

| 维度 | 普通 AI 助手 | Marneo |
|---|---|---|
| 身份 | 一个通用助手 | 多个有名字、有职责、有成长记录的数字员工 |
| 工作方式 | 对话驱动 | 项目、员工、团队、日报、工具调用驱动 |
| 上下文 | 越聊越长，prompt 膨胀 | 固定预算 + 按需检索 + 分层记忆 |
| 飞书接入 | 一个机器人代理全部 | 每个员工可绑定自己的 Feishu/Lark Bot |
| 渠道路由 | 泛 channel 优先 | Feishu-first，channel 明确为 `feishu:<employee>` |
| 本地模式 | 往往是补充功能 | `marneo work` 和 `marneo web` 是一等入口 |
| 隐私 | 依赖外部服务默认值 | 支持 local-only/private 模式和外联工具禁用 |

### 核心能力

- Feishu/Lark WebSocket 网关
  - 普通文本消息收发
  - Markdown / post 富文本回复
  - 图片、文件等附件下载
  - 消息去重、per-chat 串行处理、session 路由
  - Reaction 生命周期提示
  - ask_user 交互卡片提交回调
  - watchdog 自动恢复

- 多员工 / 多飞书机器人
  - 一个员工可以有一个专属飞书 Bot 配置
  - 配置文件：`~/.marneo/employees/<employee>/feishu.yaml`
  - 网关 channel：`feishu:<employee>`
  - 多个 Bot 可以并行运行，例如 `feishu:laoqi`、`feishu:aria`

- 数字员工体系
  - `marneo hire` 招聘员工
  - 每个员工有 profile、SOUL、等级、成长记录、日报/周报
  - 员工可绑定项目、学习技能、参与团队协作

- 项目与团队协作
  - 创建项目、分配员工、维护项目上下文
  - 协调者可拆分任务，让多名员工并行执行并汇总
  - 项目技能、员工记忆、工作报告形成闭环

- 本地工作入口
  - `marneo work`：本地 CLI 对话
  - `marneo web`：本机 loopback Web Console
  - local-only/private 模式下可使用本地模型，例如 Ollama

- 工具执行
  - bash
  - read_file / write_file / edit_file
  - glob / grep
  - web_fetch / web_search
  - lark_cli / Feishu OpenAPI 封装
  - MCP bridge（可在 local-only 模式下禁用）

---

## 快速开始

### 1. 一键安装

推荐使用安装脚本。它会把代码安装到 `~/.marneo/marneo-agent`，创建独立 Python venv，并把 `marneo` 命令链接到本机命令路径。

```bash
curl -fsSL https://raw.githubusercontent.com/ChamberZ40/marneo-agent/main/scripts/install.sh | bash
```

只安装，不自动进入配置向导：

```bash
curl -fsSL https://raw.githubusercontent.com/ChamberZ40/marneo-agent/main/scripts/install.sh | bash -s -- --skip-setup
```

常用环境变量：

```bash
MARNEO_HOME=~/.marneo                       # 数据与配置目录
MARNEO_INSTALL_DIR=~/.marneo/marneo-agent   # 代码安装目录
MARNEO_INSTALL_DRY_RUN=1                    # 只打印动作，不修改机器
```

安装后继续：

```bash
marneo setup
marneo hire
```

### 2. 本地 CLI 工作

```bash
marneo work
marneo work --employee laoqi
```

`marneo work` 是无需飞书也能使用的一等入口，适合本机开发、调试、私有数据处理和日常命令行协作。

### 3. 本地 Web Console

```bash
marneo web
# 默认 http://127.0.0.1:8787
```

`marneo web` 是 `marneo work` 的本机浏览器界面：默认只绑定 `127.0.0.1`，读取同一套本地员工、项目和状态数据，不是新的外部消息 channel。只有明确传入 `--allow-lan` 时才允许监听局域网地址。

```bash
marneo web --host 127.0.0.1 --port 8787 --open
marneo web --allow-lan --host 0.0.0.0 --port 8787
```

### 4. Feishu/Lark 工作入口

```bash
marneo setup feishu
marneo gateway start
marneo gateway status
```

指定员工绑定飞书机器人：

```bash
marneo setup feishu --employee laoqi
# 或
marneo setup feishu -e laoqi
```

最终网关里会出现：

```text
feishu:laoqi
```

如果新增或修改了飞书机器人配置：

```bash
marneo gateway restart
```

健康检查：

```bash
curl http://127.0.0.1:8765/health
```

---

## Setup 流程

### Provider 配置

```bash
marneo setup
```

`marneo setup` 会引导配置 OpenAI-compatible 或 Anthropic-compatible Provider。已配置 Provider 时，它不会强迫你重配；你可以直接选择：

```text
跳过 Provider，继续新增/配置飞书机器人
```

这对新增第二个、第三个飞书机器人非常关键。

### 本地-only/private 模式

如果你希望数据不出本机，使用本地模型并禁用外联工具，可以运行：

```bash
marneo setup local --model llama3.3
# 或指定本地 OpenAI-compatible URL
marneo setup local --base-url http://127.0.0.1:11434/v1 --model qwen2.5-coder:7b
```

它会在 `~/.marneo/config.yaml` 写入 `privacy.local_only: true`：

```yaml
privacy:
  local_only: true
```

本地-only/private 模式要求 Provider 指向 localhost/loopback；运行时会禁用 web_fetch / web_search、lark_cli、Feishu、ask_user、MCP 等外联工具，只保留文件、bash 等本地工具。`marneo web` 本身仍可作为本机 loopback Console 使用。

推荐入口：

```bash
marneo hire
marneo work
marneo web
```

---

## 多员工 / 多飞书机器人模式

Marneo 推荐的不是“一个全局飞书机器人代理所有员工”，而是：

```text
一个员工 = 一个员工身份 = 一个飞书 Bot 配置 = 一个 channel
```

示例：

```text
~/.marneo/employees/laoqi/feishu.yaml  -> feishu:laoqi
~/.marneo/employees/aria/feishu.yaml   -> feishu:aria
~/.marneo/employees/ops/feishu.yaml    -> feishu:ops
```

典型流程：

```bash
marneo hire
marneo setup feishu --employee laoqi

marneo hire
marneo setup feishu --employee aria

marneo gateway restart
marneo gateway status
```

这样每个飞书机器人都可以使用不同的应用凭证、不同的团队群、不同的员工身份在线工作。

---

## Feishu/Lark 支持能力

| 能力 | 状态 |
|---|---|
| WebSocket 长连接 | 支持 |
| 文本消息收发 | 支持 |
| Markdown / post 渲染 | 支持 |
| 图片 / 文件下载 | 支持 |
| per-chat 串行处理 | 支持 |
| 消息去重 | 支持，磁盘持久化 |
| Reaction 生命周期 | 支持 |
| ask_user 交互卡片 | 支持 |
| CardKit 更新 | 使用 PUT |
| CARD WebSocket monkey patch | 默认关闭，需显式启用 |

### ask_user 卡片

Marneo 支持 LLM 在工作流里主动向用户提问，并通过飞书卡片收集答案。

关键点：

- 支持新版 Feishu form submit callback
- 支持从 `action.form_value` 读取用户输入
- 支持 submit button name 中携带 question id
- 支持 pending question 过期 / 重复提交保护
- 更新卡片时使用 CardKit `PUT /cardkit/v1/cards/{card_id}`

### CARD WebSocket patch

为了保证普通消息稳定，CARD WebSocket monkey patch 默认关闭：

```bash
# 默认：关闭
marneo gateway start

# 高风险调试时才开启
MARNEO_FEISHU_ENABLE_CARD_WS_PATCH=1 marneo gateway start
```

---

## 架构

```text
Feishu / Lark
    ↓ WebSocket events
FeishuChannelAdapter
    ↓ ChannelMessage(text, attachments, platform=feishu:<employee>)
GatewayManager
    ├─ disk-persistent dedup
    ├─ per-chat serial lock
    ├─ session routing
    ↓
ChatSession
    ├─ provider streaming
    ├─ multimodal content blocks
    ├─ tool calling loop
    ↓
Tool Registry
    ├─ bash / files / web_fetch
    ├─ lark_cli
    └─ ask_user
    ↓
Feishu reply / card / file / markdown
```

本地路径：

```text
Terminal / Browser
    ├─ marneo work
    └─ marneo web 127.0.0.1:8787
          ↓
Local employee / project / status APIs
          ↓
~/.marneo data directory
```

主要模块：

| 路径 | 作用 |
|---|---|
| `marneo/cli/app.py` | CLI 入口 |
| `marneo/cli/setup_cmd.py` | Provider、local-only、Feishu-first setup 向导 |
| `marneo/cli/work.py` | 本地 CLI 员工对话 |
| `marneo/cli/web_cmd.py` | 本地 Web Console 命令 |
| `marneo/web/app.py` | 零新增依赖的本地 HTTP server + 静态 UI |
| `marneo/web/api.py` | status / employees / projects / logs API 与脱敏 |
| `marneo/cli/employee_feishu_cmd.py` | 员工专属飞书 Bot 配置 |
| `marneo/employee/feishu_config.py` | `feishu.yaml` 读写模型 |
| `marneo/gateway/manager.py` | 网关生命周期、消息分发、session 管理 |
| `marneo/gateway/adapters/feishu.py` | Feishu/Lark WebSocket 适配器 |
| `marneo/gateway/pending_questions.py` | ask_user pending question 管理 |
| `marneo/tools/registry.py` | 工具注册与调度 |
| `marneo/tools/loader.py` | 工具加载与 local-only gating |
| `marneo/engine/chat.py` | LLM streaming + tool calling loop |

---

## 数据目录

```text
~/.marneo/
├── config.yaml                    # LLM Provider / privacy / channels
├── gateway.pid
├── gateway.log
├── employees/
│   └── <employee>/
│       ├── profile.yaml           # 员工档案
│       ├── SOUL.md                # 员工身份设定
│       ├── feishu.yaml            # 员工专属飞书 Bot 凭证
│       ├── push.yaml              # 推送配置
│       ├── memory/                # 分层记忆
│       └── reports/               # 日报 / 周报
├── projects/
│   └── <project>/
│       ├── project.yaml
│       ├── AGENT.md
│       └── skills/
└── skills/                        # 全局技能
```

不要把 `~/.marneo/config.yaml`、`~/.marneo/employees/*/feishu.yaml`、网关日志、真实客户文件或聊天记录提交到 Git。

---

## 常用命令

### 安装与配置

```bash
marneo setup                         # 配置 Provider；已配置时可跳过去配置飞书
marneo setup local                   # 本地-only/private 模式
marneo setup feishu                  # 选择员工并配置飞书 Bot
marneo setup feishu --employee NAME  # 为指定员工配置飞书 Bot
```

### 员工

```bash
marneo hire
marneo employees list
marneo employees show NAME
marneo employees feishu setup NAME
marneo employees feishu status NAME
```

### 本地工作

```bash
marneo work
marneo work --employee NAME
marneo web
marneo web --open
```

### 项目与团队

```bash
marneo projects new PROJECT
marneo projects list
marneo projects show PROJECT
marneo assign PROJECT
marneo team setup PROJECT
marneo team list PROJECT
```

### 网关

```bash
marneo gateway start
marneo gateway stop
marneo gateway restart
marneo gateway status
marneo gateway logs
marneo gateway channels list
```

### 开发测试

```bash
python3 -m pip install -e '.[dev]'
python3 -m pytest tests -q
```

---

## 安全与凭证

Marneo 会处理多类敏感信息：

- LLM Provider key
- Feishu App ID / App Secret
- Feishu WebSocket ticket / access key
- 飞书 chat id / open id
- 客户文件、邮件、聊天记录

安全原则：

1. 真实凭证只放在本机 `~/.marneo/` 或环境变量里。
2. 文档、日志、issue、截图提交前先脱敏。
3. Web Console 默认只监听 `127.0.0.1`。
4. local-only/private 模式下必须使用 loopback Provider，并禁用外联工具。
5. 提交前运行 secret scan 和测试。

提交前建议：

```bash
git diff --check
python3 -m pytest tests -q
```

并检查是否误提交以下类型内容：

```text
api_key
app_secret
access_token
refresh_token
Feishu ticket
Feishu access key
Authorization header
private key block
```

---

## 开发者工作流

```bash
git clone git@github.com:ChamberZ40/marneo-agent.git
cd marneo-agent
python3 -m pip install -e '.[dev]'
python3 -m pytest tests -q
```

推荐改动顺序：

1. 先写测试，确认失败。
2. 实现最小功能。
3. 跑相关测试和全量测试。
4. 跑 `git diff --check`。
5. 扫描 secrets。
6. 再 commit / push。

---

## English

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
