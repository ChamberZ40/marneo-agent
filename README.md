# Marneo Agent

<div align="center">

**Feishu-first digital employees for real work.**

Marneo turns AI agents into named, project-aware digital employees that can live inside Feishu/Lark, use tools, remember work context, and collaborate as a team.

[![Python](https://img.shields.io/badge/Python-3.11+-blue)](https://python.org)
[![License](https://img.shields.io/badge/License-Apache%202.0-green)](LICENSE)

[中文](#中文说明) · [English](#english)

</div>

---

## 中文说明

### Marneo 是什么

Marneo 是一个「数字员工」系统，不是普通聊天机器人，也不是只会回答问题的个人助理。

它的核心目标是：

- 给每个 AI 员工一个独立身份、能力边界和成长轨迹
- 把员工绑定到项目，而不是把所有上下文无限塞进一个超级 prompt
- 让员工通过飞书机器人在线工作，能读消息、回消息、处理文件、调用工具
- 支持多个飞书机器人，每个机器人对应不同员工和不同 channel
- 保持 system prompt 可控，避免越用越慢、越用越贵

Marneo 当前的产品重点是：先把 Feishu/Lark 这一个 channel 深耕打通。

### 和 Hermes / OpenClaw 的区别

| 维度 | Hermes / OpenClaw 风格 | Marneo |
|---|---|---|
| 产品定位 | 个人助理，偏全能 | 工作型数字员工，偏执行 |
| 上下文策略 | 容易把技能/记忆长期塞进 system prompt | 固定预算 + 按需检索 |
| 员工模型 | 一个主 agent 或多 agent 配置 | 每个员工有独立 profile / SOUL / Feishu Bot |
| 飞书接入 | 通常是一个机器人入口 | per-employee Bot，channel 为 `feishu:<employee>` |
| 工作组织 | 对话为中心 | 项目、员工、团队、报告为中心 |
| 当前优先级 | 多 channel 泛化 | Feishu-first 深度打磨 |

### 核心能力

- Feishu/Lark WebSocket 网关
  - 普通文本消息
  - Markdown / rich text 回复
  - 图片、文件等附件下载
  - Reaction 生命周期：收到、处理中、失败提示
  - ask_user 交互卡片提交回调
  - watchdog 自动恢复

- 多飞书机器人 / 多员工 channel
  - 每个员工单独保存飞书配置
  - 配置文件：`~/.marneo/employees/<employee>/feishu.yaml`
  - 网关 channel：`feishu:<employee>`
  - 例如：`feishu:laoqi`、`feishu:aria`

- 数字员工体系
  - `marneo hire` 创建员工
  - 员工拥有 `SOUL.md`、等级、成长记录、报告
  - 员工可绑定项目、学习技能、生成日报/周报

- 工具调用能力
  - bash
  - read_file / write_file / edit_file
  - glob / grep
  - web_fetch / web_search
  - lark_cli，封装飞书开放能力

- 项目与团队协作
  - 创建项目
  - 分配员工
  - 多员工团队协作
  - 协调者拆分任务并汇总结果

---

## 快速开始

### 1. 安装

推荐用一键安装脚本。它会仿照 Hermes Agent 的安装方式，把代码安装到 `~/.marneo/marneo-agent`，创建独立 Python venv，并把 `marneo` 命令链接到 `~/.local/bin/marneo`。

```bash
curl -fsSL https://raw.githubusercontent.com/ChamberZ40/marneo-agent/main/scripts/install.sh | bash
```

如果只想安装，不自动进入配置向导：

```bash
curl -fsSL https://raw.githubusercontent.com/ChamberZ40/marneo-agent/main/scripts/install.sh | bash -s -- --skip-setup
```

常用环境变量：

```bash
MARNEO_HOME=~/.marneo              # 数据与配置目录
MARNEO_INSTALL_DIR=~/.marneo/marneo-agent  # 代码安装目录
```

安装完成后，继续运行：

```bash
marneo setup
marneo hire
```

本地命令行使用：

```bash
marneo work
```

飞书使用：

```bash
marneo setup feishu
marneo gateway start
```

开发环境：

```bash
git clone git@github.com:ChamberZ40/marneo-agent.git
cd marneo-agent
python3 -m pip install -e '.[dev]'
```

### 2. 配置 LLM Provider

```bash
marneo setup
```

`marneo setup` 会引导你配置 OpenAI-compatible 或 Anthropic-compatible Provider。

如果 Provider 已经配置过，它不会再强迫你重新配置；你可以直接选择：

```text
跳过 Provider，继续新增/配置飞书机器人
```

这对于新增第二个、第三个飞书机器人很重要。

### 3. 创建第一个数字员工

```bash
marneo hire
```

员工数据会保存在：

```text
~/.marneo/employees/<employee>/
```

### 4. 为员工配置飞书机器人

推荐的新入口：

```bash
marneo setup feishu
```

指定员工：

```bash
marneo setup feishu --employee laoqi
# 或
marneo setup feishu -e laoqi
```

它会引导你创建或绑定飞书应用，保存为：

```text
~/.marneo/employees/laoqi/feishu.yaml
```

最终网关里会出现的 channel 是：

```text
feishu:laoqi
```

底层仍兼容旧命令：

```bash
marneo employees feishu setup laoqi
```

### 5. 启动网关

```bash
marneo gateway start
marneo gateway status
```

如果你新增或修改了飞书机器人配置：

```bash
marneo gateway restart
```

查看健康状态：

```bash
curl http://127.0.0.1:8765/health
```

期望看到：

```json
{
  "status": "ok",
  "connected_channels": ["feishu:laoqi"]
}
```

查看日志：

```bash
marneo gateway logs
# 或
cat ~/.marneo/gateway.log
```

注意：日志和配置中可能包含凭证，提交 issue 或截图前请先脱敏。

---

## 多飞书机器人模式

Marneo 的推荐模型不是“一个全局飞书机器人代理所有员工”，而是：

```text
一个员工 = 一个员工身份 = 一个飞书 Bot 配置 = 一个 channel
```

示例：

```text
~/.marneo/employees/laoqi/feishu.yaml  -> feishu:laoqi
~/.marneo/employees/aria/feishu.yaml   -> feishu:aria
~/.marneo/employees/ops/feishu.yaml    -> feishu:ops
```

配置流程：

```bash
marneo hire
marneo setup feishu --employee laoqi

marneo hire
marneo setup feishu --employee aria

marneo gateway restart
marneo gateway status
```

这样每个飞书机器人都可以用不同的应用凭证、不同的团队群、不同的员工身份在线工作。

---

## Feishu/Lark 接入细节

### 支持能力

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
- 支持 pending question 过期/重复提交保护
- 更新卡片时使用 CardKit `PUT /cardkit/v1/cards/{card_id}`

### CARD WebSocket patch

为了保证普通消息稳定，CARD WebSocket monkey patch 默认关闭：

```bash
# 默认：关闭
marneo gateway start

# 高风险调试时才开启
MARNEO_FEISHU_ENABLE_CARD_WS_PATCH=1 marneo gateway start
```

默认模式优先保证普通 Feishu text EVENT 正常进入网关。

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
    ├─ bash / files / web
    ├─ lark_cli
    └─ ask_user
    ↓
Feishu reply / card / file / markdown
```

### 主要模块

| 路径 | 作用 |
|---|---|
| `marneo/cli/app.py` | CLI 入口 |
| `marneo/cli/setup_cmd.py` | Provider 与 Feishu-first setup 向导 |
| `marneo/cli/employee_feishu_cmd.py` | 员工专属飞书 Bot 配置 |
| `marneo/employee/feishu_config.py` | `feishu.yaml` 读写模型 |
| `marneo/gateway/manager.py` | 网关生命周期、消息分发、session 管理 |
| `marneo/gateway/adapters/feishu.py` | Feishu/Lark WebSocket 适配器 |
| `marneo/gateway/pending_questions.py` | ask_user pending question 管理 |
| `marneo/tools/core/ask_user.py` | 交互式用户确认工具 |
| `marneo/engine/chat.py` | LLM streaming + tool calling loop |
| `marneo/tools/registry.py` | 工具注册与调度 |

---

## 数据目录

```text
~/.marneo/
├── config.yaml                    # LLM Provider 配置
├── gateway.pid
├── gateway.log
├── employees/
│   └── <employee>/
│       ├── profile.yaml           # 员工档案
│       ├── SOUL.md                # 员工身份设定
│       ├── feishu.yaml            # 员工专属飞书 Bot 凭证
│       ├── push.yaml              # 推送配置
│       ├── memory/                # 分层记忆
│       └── reports/               # 日报/周报
├── projects/
│   └── <project>/
│       ├── project.yaml
│       ├── AGENT.md
│       └── skills/
└── skills/                        # 全局技能
```

请不要把 `~/.marneo/config.yaml`、`~/.marneo/employees/*/feishu.yaml`、日志、真实邮件/客户数据提交到 Git。

---

## 常用命令

### Setup

```bash
marneo setup                         # 配置 Provider；已配置时可跳过去配置飞书
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

### 工作

```bash
marneo work
marneo work --employee NAME
```

### 项目

```bash
marneo projects new PROJECT
marneo projects list
marneo projects show PROJECT
marneo assign PROJECT
```

### 网关

```bash
marneo gateway start
marneo gateway stop
marneo gateway restart
marneo gateway status
marneo gateway logs
```

### 测试

```bash
python3 -m pytest tests -q
```

---

## 安全与凭证

Marneo 会处理多类敏感信息：

- LLM Provider API key
- Feishu App ID / App Secret
- Feishu WebSocket ticket / access key
- 飞书 chat id / open id
- 客户文件、邮件、聊天记录

提交代码前建议执行：

```bash
git diff --cached
python3 -m pytest tests -q
```

并检查是否误提交：

```text
api_key
app_secret
access_token
refresh_token
Feishu ticket
Feishu access key
Authorization: Bearer <token>
```

本仓库应该只提交示例配置和脱敏文档，不提交真实凭证。

---

## English

### What is Marneo?

Marneo is a work-focused digital employee system.

Instead of building one giant personal assistant, Marneo creates named AI employees that can be assigned to projects, connected to Feishu/Lark bots, equipped with tools, and organized into teams.

The current product focus is Feishu-first:

- one employee can have one dedicated Feishu/Lark bot
- each bot becomes a concrete gateway channel: `feishu:<employee>`
- multiple Feishu bots can run side by side
- setup is optimized for Feishu onboarding before broader channel generalization

### Quick Start

```bash
git clone git@github.com:ChamberZ40/marneo-agent.git
cd marneo-agent
python3 -m pip install -e '.[dev]'

marneo setup
marneo hire
marneo setup feishu --employee laoqi
marneo gateway start
marneo gateway status
```

Expected channel:

```text
feishu:laoqi
```

### Why Marneo?

| Area | Marneo approach |
|---|---|
| Identity | Named digital employees, not anonymous assistants |
| Context | Fixed prompt budget + retrieval, not unbounded prompt growth |
| Work model | Projects, employees, reports, tools |
| Feishu | Per-employee bot configuration |
| Gateway | WebSocket, dedup, per-chat locks, watchdog recovery |
| Tools | Minimal tool schemas, runtime dispatch, Feishu CLI integration |

### Multiple Feishu Bots

```bash
marneo hire
marneo setup feishu --employee laoqi

marneo hire
marneo setup feishu --employee aria

marneo gateway restart
```

Configuration layout:

```text
~/.marneo/employees/laoqi/feishu.yaml  -> feishu:laoqi
~/.marneo/employees/aria/feishu.yaml   -> feishu:aria
```

### Development

```bash
python3 -m pip install -e '.[dev]'
python3 -m pytest tests -q
```

Before committing or pushing, scan for secrets and avoid committing local runtime data from `~/.marneo/` or real user/customer data.

---

## License

Apache 2.0. See `LICENSE`.
