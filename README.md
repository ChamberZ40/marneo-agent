# Marneo Agent

<div align="center">

> **Mare**（马）+ **Neo**（新）= **新马** 🐴
>
> *Work-focused digital employees — not a personal assistant*

[![Python](https://img.shields.io/badge/Python-3.11+-blue)](https://python.org)
[![License](https://img.shields.io/badge/License-Apache%202.0-green)](LICENSE)

[🇨🇳 中文文档](#中文文档) · [🇺🇸 English](#english-documentation)

</div>

---

## 中文文档

### 设计理念

Marneo 是**专注工作的数字员工系统**，不是个人助理。

**与 OpenClaw / Hermes 的核心区别：**

| 维度 | OpenClaw / Hermes | Marneo |
|------|-------------------|--------|
| 定位 | 个人助理，记住一切 | 数字员工，专注执行 |
| System Prompt | 随使用积累无限增长（OpenClaw ~40KB） | 固定上限（默认 ≤4,500 chars） |
| 技能/记忆 | 全部预加载进 context | 按需检索注入，用完即清 |
| 响应速度 | 越用越慢 | 稳定，不随时间退化 |
| 记忆设计 | 无分级，堆积 | 三层分级：Core / Episodic / Working |

**核心理念：**
- 🧑‍💼 **员工中心**：有名字、性格、成长轨迹的数字员工，不是通用助手
- 📁 **项目绑定**：员工被分配到具体项目，携带最小必要上下文
- 🧠 **分层记忆**：核心约束永不遗忘，工作经验按需召回
- 🛠️ **工具能力**：文件读写、Shell、Web、飞书全套工具
- 📱 **多渠道在线**：飞书/微信/Telegram/Discord 随时响应
- 🤝 **团队协作**：多员工并行，协调者汇总结果

---

### 快速开始

```bash
# 安装
pip install -e .

# 1. 配置 LLM Provider
marneo setup

# 2. 招聘第一位数字员工（AI 面试生成身份档案）
marneo hire

# 3. 开始对话
marneo work
```

---

### 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                        用户 / IM 渠道                         │
│              飞书 · 微信 · Telegram · Discord                 │
└──────────────────────────┬──────────────────────────────────┘
                           │ 消息
┌──────────────────────────▼──────────────────────────────────┐
│                     Gateway 层                               │
│  FeishuAdapter · WeChatAdapter · TelegramAdapter             │
│  - WebSocket 长连接 / Webhook                                │
│  - 消息解析（text/image/file/post）                          │
│  - 附件下载（多模态：图片/PDF → bytes）                       │
│  - Reaction 生命周期（收到→处理中→完成/失败）                 │
│  - 飞书 Markdown 渲染（post type + md tag）                   │
└──────────────────────────┬──────────────────────────────────┘
                           │ ChannelMessage（text + attachments）
┌──────────────────────────▼──────────────────────────────────┐
│                   GatewayManager                             │
│  - 消息去重（disk-persistent，24h TTL）                      │
│  - 按 chat_id 串行锁（openclaw createChatQueue 模式）        │
│  - 分发到 ChatSession                                        │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                  Engine 层（ChatSession）                     │
│                                                              │
│  send_with_tools()  ←── Agentic Loop                        │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  LLM 调用 → tool_call? → 执行工具 → 注入结果 → 循环  │    │
│  │  直到 LLM 返回纯文本为止（最多 max_iterations 轮）    │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
│  多模态 content blocks 构建：                                │
│  - OpenAI 协议：image_url block / text block                │
│  - Anthropic 协议：image source / document block            │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                   Tools 层                                   │
│                                                              │
│  Tool Registry（hermes-agent 模式）                          │
│  - 自注册：每个工具模块 import 时自动注册                     │
│  - check_fn：工具不可用时自动从 LLM 工具列表排除             │
│  - 描述极简：每个工具 ≤ 2 行描述，不预加载使用文档           │
│                                                              │
│  核心工具：                                                  │
│  bash · read_file · write_file · edit_file · glob · grep    │
│  web_fetch · web_search · lark_cli                          │
│                                                              │
│  lark_cli：封装官方 lark-cli，自动注入 app_id/app_secret     │
│  覆盖：文档/日历/多维表/任务/日程/群聊/日历/审批等 200+ 命令  │
└──────────────────────────────────────────────────────────────┘
```

---

### 模块详解

#### 1. Engine 层 (`marneo/engine/`)

**职责：** LLM 调用、流式输出、Agentic Loop

**`chat.py` — ChatSession**

```python
# 单次流式对话（无工具）
async for event in session.send(text, attachments=None):
    # event.type: "text" | "thinking" | "error" | "done"

# Agentic loop（带工具调用）
async for event in session.send_with_tools(text, registry=registry,
                                           attachments=None, max_iterations=20):
    # event.type: "text" | "tool_call" | "tool_result" | "error" | "done"
```

**Agentic Loop 流程：**
```
用户消息
    → LLM（携带工具定义）
    → 返回 tool_call？
        → 是：执行工具 → 结果注入 messages → 继续
        → 否：yield 文本 → 结束
```

**`_build_content_blocks()` — 多模态构建：**
- `text/plain`, `application/json` → 内容直接注入为文本（≤200KB）
- `image/*` → OpenAI `image_url` block / Anthropic `image` source block
- `application/pdf` → Anthropic `document` block / OpenAI 文本提示
- 超过 20MB 的附件 → 提示文件过大，不编码

**`provider.py` — Provider 解析：**
支持所有 OpenAI-compatible 和 Anthropic-compatible 端点，从 `~/.marneo/config.yaml` 读取配置。

---

#### 2. Tools 层 (`marneo/tools/`)

**职责：** 工具注册、调度、执行

**设计原则：工具描述极简化**

工具 description 只描述功能（≤2行），不包含详细用法文档。详细用法以 skill 形式存入 `~/.marneo/skills/`，通过记忆系统按需检索加载（避免 OpenClaw 式的 40KB system prompt）。

**`registry.py` — Tool Registry（hermes-agent 模式）**

```python
registry.register(
    name="bash",
    description="Execute a bash command.",
    schema={...},          # OpenAI function calling 格式
    handler=bash_fn,
    check_fn=lambda: bool(shutil.which("bash")),  # 可用性检查
    is_async=False,
)
```

调度：`registry.dispatch(name, args)` → 捕获所有异常 → 返回 JSON 字符串

**核心工具：**

| 工具 | 功能 | 安全限制 |
|------|------|---------|
| `bash` | Shell 命令执行 | 危险命令正则拦截（rm -rf /、fork bomb、mkfs等） |
| `read_file` | 读文件（带行号分页） | 100KB 上限，自动截断 |
| `write_file` | 写文件（自动建目录） | 无 |
| `edit_file` | 精确字符串替换 | old_string 必须唯一 |
| `glob` | 按 pattern 查找文件 | 结果上限 200 条 |
| `grep` | 正则搜索文件内容 | 文件上限 100 个，结果 500 条 |
| `web_fetch` | 抓取 URL 为纯文本 | 仅 http/https，50KB 上限 |
| `web_search` | DuckDuckGo 搜索 | 结果上限 10 条 |
| `lark_cli` | 飞书 CLI 全套操作 | 自动注入 app_id/app_secret，--as bot |

**`lark_cli` 工作原理：**
1. 从 `EmployeeFeishuConfig` 读取 `app_id` / `app_secret`
2. 自动运行 `lark-cli config init --app-id ... --app-secret-stdin ...`（首次/凭证变更时）
3. 执行命令时自动追加 `--as bot --format json`
4. 返回 JSON 结构化输出

---

#### 3. Gateway 层 (`marneo/gateway/`)

**职责：** IM 渠道接入、消息路由、Reaction 管理

**`base.py` — ChannelMessage**

```python
@dataclass
class ChannelMessage:
    platform: str          # "feishu:老七"、"telegram" 等
    chat_id: str
    text: str = ""
    msg_id: str = ""       # 用于去重
    attachments: list[dict] = field(default_factory=list)
    # attachment: {"data": bytes, "media_type": str, "filename": str}
```

**`manager.py` — GatewayManager**

```
ChannelMessage
    → 去重检查（disk-persistent MessageDeduplicator）
    → SessionStore.get_or_create()（按 platform:chat_id 获取 ChatSession）
    → 串行锁（per-chat Lock，对应 openclaw createChatQueue）
    → _process()
        → engine.send_with_tools(text, registry, attachments)
        → 收集 "text" events → 分段发送回 IM
```

**`adapters/feishu.py` — Feishu 适配器**

关键设计（参考 hermes-agent）：

- **WS 连接**：`lark_oapi.ws.Client` 在 executor 线程中运行，patch `ws_client_module.loop = loop` 解决主 event loop 冲突问题
- **Pending 队列**：启动窗口期收到的消息入队，loop ready 后重放（不丢消息）
- **Per-chat 串行锁**：`_get_chat_lock(chat_id)` 保证同一聊天的消息顺序处理
- **Reaction 生命周期**：
  ```
  收到消息 → add_reaction("SaluteFace")  # 致敬，表示处理中
  处理成功 → delete_reaction(reaction_id)  # 移除
  处理失败 → add_reaction("CrossMark")   # 标记失败
  ```
- **附件下载**：`_download_feishu_resource(message_id, file_key, type)` 使用 `client.im.v1.message_resource.get`（hermes-agent 模式），支持 image/file/audio
- **Markdown 渲染**：检测到 markdown 特征 → 发送 `post` 类型（`{"tag": "md", "text": content}`），否则发 `text` 类型
- **Reply Fallback**：reply 目标被撤回时（error code 230011/231003）自动降级为 create

---

#### 4. Employee 层 (`marneo/employee/`)

**职责：** 员工身份、成长、技能、报告

**数据文件：**
```
~/.marneo/employees/<name>/
├── profile.yaml      # 等级、对话统计、成就
├── SOUL.md           # 身份自述（hire 面试生成）
├── feishu.yaml       # 专属飞书 Bot 凭证
├── push.yaml         # 报告推送配置
└── reports/          # 日报/周报
```

**`profile.py` — 员工档案**

等级体系：实习生 → 初级员工 → 中级员工 → 高级员工

升级条件通过 `growth.py` 中的 `should_level_up()` 检查，满足条件时员工在对话中发起升级请求，用户输入 `y` 确认。

**`interview.py` — AI 面试**

多轮动态面试（多选题 + 自由补充）→ `synthesize_soul()` 生成 SOUL.md。
相同逻辑也用于项目面试（`project/interview.py`）。

**`skill_learner.py` — 技能自动提炼**

每次对话结束后，对实习生/初级员工：
```
对话内容 → LLM 判断是否有可提炼技能 → 非 SKIP → 写入 ~/.marneo/skills/
```

> ⚠️ **即将重构**：技能系统将迁移至分层记忆系统（BM25+向量混合检索），不再预加载所有技能到 system prompt。

---

#### 5. Project 层 (`marneo/project/`)

**职责：** 项目管理、技能管理

**数据文件：**
```
~/.marneo/projects/<name>/
├── project.yaml      # 描述、目标、成员、团队配置
├── AGENT.md          # 工作档案（项目面试生成）
└── skills/           # 项目专属技能
```

`workspace.py` 提供 CRUD 操作：`create_project`, `load_project`, `assign_employee`, `get_employee_projects`

**`skills.py` — 技能管理**

技能以 `.md` 文件存储（YAML frontmatter + 内容正文）：
```markdown
---
name: pandas 编码处理
description: 处理飞书导出数据的 UTF-8 编码问题
scope: global
enabled: true
---

pd.read_csv(path, encoding='utf-8-sig')
```

> ⚠️ **即将重构**：`get_skills_context()` 将被 `retrieve_relevant_skills(query)` 替代。

---

#### 6. Collaboration 层 (`marneo/collaboration/`)

**职责：** 多员工团队协作

**`team.py` — TeamConfig**

```python
TeamConfig(
    project_name="ops",
    coordinator="老七",      # 协调者
    members=[
        TeamMember("老七", "协调者"),
        TeamMember("ARIA", "数据分析"),
    ]
)
```

**`coordinator.py` — run_team_session()**

```
用户消息（复杂任务）
    → split_task_for_specialists()   # 协调者拆分子任务
    → asyncio.gather(*specialist_sessions)  # 并行执行各专员 ChatSession
    → aggregate_results()            # 协调者汇总
    → 返回最终回复
```

触发条件：消息 > 100 字 或含「分析/计划/报告」等关键词（`should_use_team()` 检查）。

---

#### 7. Memory 层（设计中）

**职责：** 分层记忆、混合检索、context 体积管理

**三层架构：**

```
Core Memory（永远加载，≤1000 chars）
    写入：人工设定 + LLM 自动提炼 + 经验晋升
    存储：~/.marneo/employees/<name>/memory/core.md

Episodic Memory（按需检索注入）
    包含：工作经验 + Skills（~/.marneo/skills/）
    检索：BM25（rank-bm25）+ 向量（fastembed，本地~50MB）
    存储：~/.marneo/employees/<name>/memory/episodes/

Working Memory（当前对话，有上限）
    默认：最近 20 轮，超出移除最早轮次
    任务完成 → 提炼经验 → 清空
```

**System prompt 固定上限（可配置）：**
```yaml
context_budget:
  system_prompt_max: 4000     # SOUL + Core Memory，不含 skills
  working_memory_turns: 20
  episodic_inject_max: 1500   # 每轮动态注入上限
  tool_result_max: 50000      # 单次工具结果上限
```

详细设计见：`docs/plans/2026-04-24-memory-system-design.md`

---

### 数据流闭环

```
① 招聘（hire）
   AI 面试 → SOUL.md（身份）→ profile.yaml（等级）

② 配置飞书（employees feishu setup）
   app_id/app_secret → feishu.yaml → probe_bot() 验证

③ 创建项目（projects new）
   AI 面试 → AGENT.md（工作档案）→ project.yaml（目标/成员）

④ 分配员工（assign）
   employee ↔ project 绑定

⑤ 启动网关（gateway start）
   load_all_tools()          # 注册所有工具
   → FeishuAdapter.connect() # WS 连接 + Bot 身份获取
   → GatewayManager.run_forever()

⑥ 接收消息（飞书 → Gateway → Engine）
   消息到达 → 去重 → 下载附件
   → 预检索记忆/技能（BM25+向量）
   → 构建 system prompt（SOUL + Core Memory + 检索到的经验）
   → send_with_tools()  Agentic Loop
   → 工具调用（bash/文件/lark_cli/...）
   → LLM 生成回复 → Markdown 渲染 → 飞书 post 消息

⑦ 对话后处理
   技能提炼 → ~/.marneo/skills/
   对话记录 → reports/（日报/周报）
   经验晋升检查 → core.md（如达到阈值）
   对话计数 → profile.yaml → 成长检查

⑧ 成长（work 对话中）
   对话 N 次 + 在职天数 → 满足条件 → 员工申请升级
   用户输入 y → promote() → profile.yaml 更新
```

---

### 命令参考

#### 员工管理
```bash
marneo hire                          # 招聘（AI 面试 → SOUL.md）
marneo work                          # 与员工对话（自动携带项目/记忆上下文）
marneo work --employee 老七           # 指定员工

marneo employees list                # 列出所有员工
marneo employees show <name>         # 查看详情（等级/成就/SOUL.md）
marneo employees fire <name>         # 解雇员工
marneo employees feishu setup <name> # 配置专属飞书 Bot
```

#### 项目管理
```bash
marneo projects new <name>           # 创建项目（AI 面试 → AGENT.md）
marneo projects list / show <name>
marneo assign <project>              # 分配员工到项目
```

#### 技能管理
```bash
marneo skills list                   # 列出所有技能（global + 项目）
marneo skills add <id>               # 手动创建技能
marneo skills show <id>              # 查看技能内容
marneo skills enable/disable <id>
```

#### 报告
```bash
marneo report daily                  # 今日日报
marneo report daily --push           # 推送到 IM 渠道
marneo report weekly                 # 周报
marneo report history [-n 7]
```

#### IM 网关
```bash
marneo gateway start / stop / restart / status / logs
marneo gateway channels list/add/test/enable/disable <platform>
marneo gateway install-service       # 安装系统服务（开机自启）
```

---

### 支持的 LLM Provider

所有 OpenAI-compatible 和 Anthropic-compatible 端点均支持：

| Provider | 协议 | 多模态 |
|----------|------|--------|
| Anthropic Claude | anthropic-compatible | ✅ 图片 + PDF |
| OpenAI GPT-4o | openai-compatible | ✅ 图片 |
| MiniMax M2.7 | openai-compatible | ✅ 图片 |
| DeepSeek | openai-compatible | — |
| 阿里云百炼（Qwen） | openai-compatible | ✅ |
| 月之暗面（Kimi） | openai-compatible | ✅ |
| Ollama（本地） | openai-compatible | 取决于模型 |
| 自定义端点 | 自动推断 | — |

---

### 支持的 IM 渠道

| 渠道 | 接入方式 | 特性 |
|------|---------|------|
| 飞书 / Feishu | WebSocket（lark-oapi） | Markdown 渲染、附件下载、Reaction、per-employee Bot |
| 微信 / WeChat | Tencent iLink Bot | 长轮询、断线重连 |
| Telegram | Bot API | 群组/私聊 |
| Discord | Bot API | 服务器/DM |

---

### 员工成长体系

| 等级 | 条件 | 行为 |
|------|------|------|
| 实习生 | 入职即有 | 自动提炼技能，多学多问 |
| 初级员工 | 7天 + 20对话 | 完成任务，主动汇报 |
| 中级员工 | 14天 + 50对话 + 3技能 | 主动沟通，提出优化 |
| 高级员工 | 30天 + 100对话 + 8技能 | 全局视野，战略建议 |

---

### 数据目录结构

```
~/.marneo/
├── config.yaml              # LLM Provider + 渠道配置
├── gateway.pid / gateway.log
├── skills/                  # 全局技能（~/.marneo/skills/*.md）
├── feishu/                  # 飞书去重缓存
├── employees/
│   └── 老七/
│       ├── profile.yaml     # 等级、统计
│       ├── SOUL.md          # 身份自述
│       ├── feishu.yaml      # 专属 Bot 凭证
│       ├── push.yaml        # 报告推送配置
│       ├── memory/          # 分层记忆（设计中）
│       │   ├── core.md      # 核心约束，永远加载
│       │   └── episodes/    # 经验记忆，BM25+向量检索
│       └── reports/
└── projects/
    └── <name>/
        ├── project.yaml     # 配置、目标、团队
        ├── AGENT.md         # 工作档案
        └── skills/          # 项目专属技能
```

---

### 路线图

- ✅ Phase 1 — CLI + Provider + Chat TUI
- ✅ Phase 2 — 员工体系（hire / work / report / growth）
- ✅ Phase 3 — 项目体系（projects / assign / skills）
- ✅ Phase 4 — Gateway（Feishu / WeChat / Telegram / Discord）
- ✅ Phase 5 — 飞书完整化（per-employee Bot / Markdown / 多模态附件）
- ✅ Phase 6 — 工具能力（Agentic Loop / bash / file / web / lark_cli）
- 🔄 Phase 7 — 分层记忆系统（Core / Episodic / BM25+向量混合检索）
- 📋 Phase 8 — 可靠性（熔断器 / 断线重连 / 消息队列持久化）

---

## English Documentation

### Design Philosophy

Marneo is a **work-focused digital employee system**, not a personal assistant.

**Key differentiator from OpenClaw / Hermes:**

The core problem with existing systems: system prompt grows unbounded as skills and history accumulate, causing increasingly slow and expensive responses. OpenClaw's system prompt alone exceeds 40KB.

Marneo's approach:
- **Fixed system prompt size** — default ≤4,500 chars regardless of how many skills are added
- **Layered memory** — Core (always loaded) / Episodic (retrieved on-demand) / Working (capped window)
- **Skills never pre-loaded** — retrieved via BM25+vector hybrid search, injected per-turn, then discarded
- **Tool descriptions are minimal** — 1-2 lines max; detailed docs live as retrievable skills

### Quick Start

```bash
pip install -e .
marneo setup          # Configure LLM Provider
marneo hire           # Hire your first digital employee (AI interview)
marneo work           # Start chatting
```

### Architecture

```
User / IM Channel (Feishu · WeChat · Telegram · Discord)
         ↓ message
Gateway Layer (adapter per platform)
  - WebSocket / Webhook connection
  - Message parsing (text / image / file / rich-text)
  - Attachment download (image/PDF → bytes for multimodal)
  - Reaction lifecycle (processing → done / failed)
  - Markdown rendering (Feishu post type with md tag)
         ↓ ChannelMessage(text, attachments)
GatewayManager
  - Dedup (disk-persistent, 24h TTL)
  - Per-chat serial lock (like openclaw createChatQueue)
         ↓
Engine Layer (ChatSession)
  send_with_tools() — Agentic Loop
  LLM → tool_call? → execute → inject result → repeat until text
  Multimodal content blocks (OpenAI image_url / Anthropic document)
         ↓
Tools Layer (Registry)
  bash · read_file · write_file · edit_file · glob · grep
  web_fetch · web_search · lark_cli
  lark_cli: wraps official lark-cli with auto-injected app credentials
  200+ Feishu commands: docs / calendar / base / tasks / wiki / drive
```

### Data Flow (Closed Loop)

```
hire → SOUL.md (identity) + profile.yaml (level)
     ↓
feishu setup → feishu.yaml (bot credentials)
     ↓
projects new → AGENT.md (work profile) + project.yaml
     ↓
assign → employee ↔ project binding
     ↓
gateway start → tools loaded → WS connected → ready
     ↓
message arrives → dedup → download attachments
  → memory retrieval (BM25+vector: skills + episodes)
  → build system prompt (SOUL + Core Memory + retrieved context)
  → send_with_tools() agentic loop
  → tool calls (bash / files / lark_cli / ...)
  → LLM response → markdown render → reply to IM
     ↓
post-turn: skill extraction → reports → growth check
```

### Module Reference

| Module | Responsibility |
|--------|---------------|
| `engine/chat.py` | ChatSession, streaming, agentic loop, multimodal blocks |
| `engine/provider.py` | LLM provider resolution from config |
| `tools/registry.py` | Tool registration, dispatch, availability checks |
| `tools/core/` | bash, files, web, lark_cli implementations |
| `gateway/manager.py` | Message routing, dedup, session management |
| `gateway/adapters/feishu.py` | Feishu WS adapter (hermes-agent + openclaw patterns) |
| `employee/` | Profile, SOUL.md, growth, skill extraction, reports |
| `project/` | Project workspace, AGENT.md, skills |
| `collaboration/` | Multi-employee team sessions, coordinator logic |
| `memory/` | *(planned)* Layered memory: Core + Episodic + Working |

### Supported LLM Providers

Any OpenAI-compatible or Anthropic-compatible endpoint. Tested with Anthropic Claude, OpenAI GPT-4o, MiniMax M2.7, DeepSeek, Qwen, Kimi, Ollama.

### Supported IM Channels

Feishu/Lark (WebSocket, per-employee bot, Markdown, multimodal), WeChat (iLink), Telegram, Discord.
