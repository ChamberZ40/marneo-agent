# Marneo Agent

<div align="center">

> **Mare**（马）+ **Neo**（新）= **新马** 🐴
>
> *Project-focused digital employees — not a personal assistant*

[![Python](https://img.shields.io/badge/Python-3.11+-blue)](https://python.org)
[![License](https://img.shields.io/badge/License-Apache%202.0-green)](LICENSE)

[🇨🇳 中文文档](#中文文档) · [🇺🇸 English](#english-documentation)

</div>

---

## 中文文档

### 简介

Marneo 是**项目数字员工系统**。与个人助理不同，Marneo 的员工有独立身份、负责具体项目、向你汇报工作、并在飞书/微信/Telegram 等渠道中为你工作。

**核心理念：**
- 🧑‍💼 **员工中心**：你招聘员工，员工有名字、有性格、有成长轨迹
- 📁 **项目绑定**：员工被分配到具体项目，携带项目上下文对话
- 🤝 **团队协作**：多员工并行处理复杂任务，结果汇总回复
- 📱 **多渠道在线**：员工通过飞书/微信/Telegram/Discord 随时响应
- 📈 **持续成长**：实习生→初级→中级→高级，积累技能，定期汇报

---

### 快速开始

```bash
# 安装
pip install -e .

# 第一步：配置 LLM Provider
marneo setup

# 第二步：招聘第一位数字员工（LLM 面试）
marneo hire

# 第三步：开始工作
marneo work
```

---

### 完整命令参考

#### 🏠 仪表板

```bash
marneo              # 启动仪表板（员工/项目/网关状态）
marneo status       # 全局状态详情
```

#### 🧑‍💼 员工管理

```bash
marneo hire                          # 招聘员工（LLM 动态面试 → SOUL.md 身份档案）
marneo work                          # 与员工对话（自动携带项目/技能上下文）
marneo work --employee GAI           # 指定与某员工对话

marneo employees list                # 列出所有员工
marneo employees show <name>         # 查看员工详情（等级/成就/SOUL.md）
marneo employees fire <name>         # 解雇员工

marneo employees feishu setup <name> # 为员工配置专属飞书 Bot
marneo employees feishu status <name># 查看员工飞书配置
```

#### 📁 项目管理

```bash
marneo projects new <name>           # 创建项目（LLM 面试补充知识 → project.yaml + AGENT.md）
marneo projects list                 # 列出所有项目
marneo projects show <name>          # 查看项目详情

marneo assign <project>              # 将员工分配到项目
marneo assign <project> --employee GAI  # 指定员工分配
```

#### 🤝 团队协作

```bash
marneo team setup <project>          # 配置团队（选成员/角色/协调者/飞书群ID）
marneo team list <project>           # 查看团队配置
marneo team add <project> --employee ARIA --role 数据分析
marneo team remove <project> --employee ARIA
```

#### 🧩 技能管理

```bash
marneo skills list                   # 列出所有技能（global + 项目）
marneo skills add <id>               # 手动创建技能
marneo skills show <id>              # 查看技能内容
marneo skills enable/disable <id>    # 启用/禁用技能
```

#### 📋 工作报告

```bash
marneo report daily                  # 查看今日日报
marneo report daily --push           # 发送日报到 IM 渠道
marneo report weekly                 # 查看本周周报
marneo report history [-n 7]         # 查看最近 N 天记录
marneo report push-config            # 配置报告推送目标
```

#### 📡 IM 网关

```bash
# 网关进程管理
marneo gateway start                 # 后台启动网关（立即返回）
marneo gateway start --fg            # 前台运行（调试用）
marneo gateway stop                  # 停止网关
marneo gateway status                # 查看状态 + 最新日志
marneo gateway logs [-n 50]          # 查看完整日志
marneo gateway install-service       # 安装系统服务（开机自启）

# 渠道管理
marneo gateway channels list         # 查看所有渠道状态
marneo gateway channels add feishu   # 配置飞书（向导模式）
marneo gateway channels add wechat   # 配置微信（iLink Bot QR 扫码）
marneo gateway channels add telegram # 配置 Telegram
marneo gateway channels add discord  # 配置 Discord
marneo gateway channels test feishu  # 测试渠道连接
marneo gateway channels enable/disable <platform>
```

#### ⚙️ 配置

```bash
marneo setup                         # 配置 LLM Provider（交互向导）
marneo --version                     # 查看版本
```

---

### 多员工团队协作

当项目配置了多员工团队，`marneo work` 自动识别复杂任务并进入团队模式：

```
用户：帮我综合分析本月数据并制定下月营销计划

  ◆ 团队模式  GAI(协调者) + ARIA(数据分析)

  🔀 协调者正在拆分任务（2 位专员）...
  ⚡ ARIA（数据分析）开始处理...
  ✓ ARIA 完成
  🔗 协调者正在汇总结果...

  ◆  本月数据分析（ARIA）：GMV 缺口 15%，主要原因...
     下月营销计划（综合）：建议扩量策略...
```

**触发条件**：消息 > 100 字，或含「分析/计划/报告/详细/综合」等关键词。

---

### IM 支持的渠道

| 渠道 | 接入方式 | 特性 |
|------|---------|------|
| 飞书 / Feishu | WebSocket 长连接 (lark-oapi) | 富文本卡片、reaction反馈、媒体支持 |
| 微信 / WeChat | Tencent iLink Bot（QR扫码） | 长轮询、context_token、断线重连 |
| Telegram | Bot API (python-telegram-bot) | 群组/私聊 |
| Discord | Bot API (discord.py) | 服务器/DM |

---

### 员工成长体系

| 等级 | 条件 | 行为 |
|------|------|------|
| 实习生 | 入职即有 | 多问多学，自动提炼技能 |
| 初级员工 | 7天 + 20对话 | 把份内事做好，主动汇报 |
| 中级员工 | 14天 + 50对话 + 3技能 | 主动沟通，提出优化 |
| 高级员工 | 30天 + 100对话 + 8技能 | 全局视野，战略建议 |

员工通过 `y` 确认升级请求，成长历程存储在员工档案中。

---

### 数据目录结构

```
~/.marneo/
├── config.yaml              # LLM Provider + 渠道配置
├── gateway.pid              # 网关进程 PID
├── gateway.log              # 网关日志
├── skills/                  # 全局技能
├── feishu/                  # 飞书去重缓存
├── employees/
│   └── GAI/
│       ├── profile.yaml     # 等级、成就、对话统计
│       ├── SOUL.md          # 身份自述（hire 面试生成）
│       ├── feishu.yaml      # 专属飞书 Bot 凭证
│       ├── push.yaml        # 报告推送配置
│       └── reports/         # 日报/周报
└── projects/
    └── affiliate-ops/
        ├── project.yaml     # KPI、成员、团队配置
        ├── AGENT.md         # 工作档案（面试生成）
        └── skills/          # 项目专属技能
```

---

### 部署

#### Docker

```bash
# 复制配置模板
cp .env.example .env
# 编辑 .env 填写 API Key

# 启动
docker-compose up -d

# 查看状态
docker-compose ps
curl http://localhost:8765/health
```

#### 系统服务（开机自启）

```bash
# macOS
marneo gateway install-service
launchctl load ~/Library/LaunchAgents/com.marneo.gateway.plist

# Linux
marneo gateway install-service
systemctl --user enable marneo-gateway
systemctl --user start marneo-gateway
```

---

### 支持的 LLM Provider

| Provider | 协议 | 说明 |
|----------|------|------|
| Anthropic | anthropic-compatible | Claude Sonnet/Haiku |
| OpenAI | openai-compatible | GPT-4o |
| DeepSeek | openai-compatible | deepseek-chat |
| 阿里云百炼 | openai-compatible | qwen-plus/max |
| 月之暗面(Kimi) | openai-compatible | kimi-k2.5 |
| 智谱AI | openai-compatible | GLM-4 |
| MiniMax | openai-compatible | MiniMax-M2.7 |
| Groq | openai-compatible | llama-3.3 |
| OpenRouter | openai-compatible | 聚合路由 |
| Ollama | openai-compatible | 本地模型 |
| 自定义 | 自动推断 | 任意 OpenAI 兼容端点 |

---

---

## English Documentation

### Overview

Marneo is a **project-focused digital employee system**. Unlike personal assistants, Marneo employees have their own identity, are assigned to specific projects, report on their work, and respond to you through Feishu, WeChat, Telegram, and other channels.

**Core Concepts:**
- 🧑‍💼 **Employee-centric**: You hire employees with names, personalities, and career growth
- 📁 **Project-bound**: Employees are assigned to projects and carry full project context
- 🤝 **Team collaboration**: Multiple employees work in parallel on complex tasks
- 📱 **Always online**: Employees respond via Feishu/WeChat/Telegram/Discord
- 📈 **Continuous growth**: Intern → Junior → Mid-level → Senior, with skill accumulation

---

### Quick Start

```bash
# Install
pip install -e .

# Step 1: Configure LLM Provider
marneo setup

# Step 2: Hire your first digital employee (LLM interview)
marneo hire

# Step 3: Start working
marneo work
```

---

### Command Reference

#### 🏠 Dashboard

```bash
marneo              # Launch dashboard (employees / projects / gateway)
marneo status       # Global system status
```

#### 🧑‍💼 Employee Management

```bash
marneo hire                          # Hire employee (LLM interview → SOUL.md)
marneo work                          # Chat with employee (project context auto-loaded)
marneo work --employee GAI           # Chat with a specific employee

marneo employees list                # List all employees
marneo employees show <name>         # View employee details (level / achievements)
marneo employees fire <name>         # Dismiss employee

marneo employees feishu setup <name> # Configure dedicated Feishu Bot for employee
marneo employees feishu status <name># View employee Feishu config
```

#### 📁 Project Management

```bash
marneo projects new <name>           # Create project (LLM interview → project.yaml + AGENT.md)
marneo projects list                 # List all projects
marneo projects show <name>          # View project details

marneo assign <project>              # Assign employee to project
marneo assign <project> --employee GAI
```

#### 🤝 Team Collaboration

```bash
marneo team setup <project>          # Configure team (members / roles / coordinator / chat ID)
marneo team list <project>           # View team configuration
marneo team add <project> --employee ARIA --role "Data Analyst"
marneo team remove <project> --employee ARIA
```

#### 🧩 Skill Management

```bash
marneo skills list                   # List all skills (global + project-scoped)
marneo skills add <id>               # Create skill manually
marneo skills show <id>              # View skill content
marneo skills enable/disable <id>    # Toggle skill
```

#### 📋 Reports

```bash
marneo report daily                  # View today's work log
marneo report daily --push           # Push report to IM channel
marneo report weekly                 # View weekly summary
marneo report history [-n 7]         # Recent N days
marneo report push-config            # Configure push target
```

#### 📡 IM Gateway

```bash
# Process management
marneo gateway start                 # Start gateway (background, returns immediately)
marneo gateway start --fg            # Foreground mode (debugging)
marneo gateway stop                  # Stop gateway
marneo gateway status                # Status + latest log line
marneo gateway logs [-n 50]          # View full log
marneo gateway install-service       # Install system service (auto-start on boot)

# Channel management
marneo gateway channels list         # View all channel status
marneo gateway channels add feishu   # Configure Feishu (wizard)
marneo gateway channels add wechat   # Configure WeChat (iLink Bot QR scan)
marneo gateway channels add telegram # Configure Telegram
marneo gateway channels add discord  # Configure Discord
marneo gateway channels test feishu  # Test channel connection
marneo gateway channels enable/disable <platform>
```

#### ⚙️ Configuration

```bash
marneo setup                         # Configure LLM Provider (interactive wizard)
marneo --version                     # Show version
```

---

### Multi-Employee Team Collaboration

When a project has a configured team, `marneo work` automatically detects complex tasks and switches to team mode:

```
User: Please analyze this month's data and create a marketing plan for next month

  ◆ Team Mode  GAI(Coordinator) + ARIA(Data Analyst)

  🔀 Coordinator splitting task (2 specialists)...
  ⚡ ARIA (Data Analyst) working...
  ✓ ARIA done
  🔗 Coordinator aggregating results...

  ◆  This month's analysis (ARIA): GMV gap 15%, key driver...
     Next month's plan (aggregated): Recommended scaling strategy...
```

**Triggers**: Message > 100 chars, or contains analysis/planning keywords.

---

### Supported IM Channels

| Channel | Integration | Features |
|---------|-------------|---------|
| Feishu / Lark | WebSocket (lark-oapi) | Rich text cards, reaction feedback, media |
| WeChat | Tencent iLink Bot (QR login) | Long-poll, context_token, auto-reconnect |
| Telegram | Bot API (python-telegram-bot) | Groups / DMs |
| Discord | Bot API (discord.py) | Servers / DMs |

---

### Employee Growth System

| Level | Requirements | Behavior |
|-------|-------------|---------|
| Intern | On hire | Asks questions, auto-extracts skills |
| Junior | 7d + 20 conv | Completes tasks thoroughly, reports back |
| Mid-level | 14d + 50 conv + 3 skills | Proactively communicates, suggests improvements |
| Senior | 30d + 100 conv + 8 skills | Strategic thinking, global perspective |

Employees request level-up in conversation; confirm with `y`.

---

### Data Directory

```
~/.marneo/
├── config.yaml              # LLM Provider + channel config
├── gateway.pid / gateway.log
├── skills/                  # Global skills
├── employees/
│   └── GAI/
│       ├── profile.yaml     # Level, achievements, stats
│       ├── SOUL.md          # Identity (generated by hire interview)
│       ├── feishu.yaml      # Dedicated Feishu Bot credentials
│       ├── push.yaml        # Report push target
│       └── reports/         # Daily / weekly logs
└── projects/
    └── my-project/
        ├── project.yaml     # KPIs, members, team config
        ├── AGENT.md         # Work profile (interview-generated)
        └── skills/          # Project-scoped skills
```

---

### Deployment

#### Docker

```bash
cp .env.example .env      # Fill in API key
docker-compose up -d
curl http://localhost:8765/health
```

#### System Service (auto-start on boot)

```bash
# macOS
marneo gateway install-service
launchctl load ~/Library/LaunchAgents/com.marneo.gateway.plist

# Linux
marneo gateway install-service
systemctl --user enable marneo-gateway && systemctl --user start marneo-gateway
```

---

### Supported LLM Providers

| Provider | Protocol | Notes |
|----------|----------|-------|
| Anthropic | anthropic-compatible | Claude Sonnet/Haiku |
| OpenAI | openai-compatible | GPT-4o |
| DeepSeek | openai-compatible | deepseek-chat |
| Alibaba Qwen | openai-compatible | qwen-plus/max |
| Moonshot (Kimi) | openai-compatible | kimi-k2.5 |
| Zhipu AI | openai-compatible | GLM-4 |
| MiniMax | openai-compatible | MiniMax-M2.7 |
| Groq | openai-compatible | llama-3.3 |
| OpenRouter | openai-compatible | Aggregated routing |
| Ollama | openai-compatible | Local models |
| Custom | Auto-detected | Any OpenAI-compatible endpoint |

---

### Roadmap

- ✅ Phase 1 — CLI + Provider + Chat TUI
- ✅ Phase 2 — Employee system (hire / work / report / growth)
- ✅ Phase 3 — Project system (projects / assign / skills)
- ✅ Phase 4 — Gateway (Feishu / WeChat / Telegram / Discord)
- ✅ Phase 5 — Polish (dashboard / push / auto-learn)
- ✅ Phase 6 — Production (feishu-prod / tests / deploy / team collab)
- 🔄 Next — Reliability (circuit breaker / reconnect / message queue)
