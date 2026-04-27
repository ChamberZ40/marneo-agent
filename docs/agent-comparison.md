# Marneo vs 开源 Agent 项目对比分析

> 生成时间：2026-04-27
> 对比项目：cc-haha (Claude Code 源码)、hermes-agent (Nous Research)、openclaw (OpenClaw)
> 目标：识别 marneo 可借鉴的特性

## 项目概览

| 维度 | cc-haha | hermes-agent | openclaw | marneo |
|------|---------|--------------|----------|--------|
| 语言 | TypeScript + React | Python 3.11+ | TypeScript | Python 3.11+ |
| 规模 | 1,910 files / 57 modules | ~770 tests / ~11k LOC core | 1.5M+ LOC / 115+ plugins | ~9,100 LOC |
| Agent 模型 | 5 种 subagent 类型 | 单 agent + delegate | 嵌入式 PI runner + subagent | ChatSession + coordinator |
| 插件系统 | Skill + Plugin + Hook | Registry + MCP + Memory Provider | Manifest-first + SDK boundary | Self-registering tools |
| Memory | Auto-extract + AutoDream | SessionDB FTS5 + MemoryProvider | Dreaming 三阶段 | Core/Episodic/Working 三层 |
| Channel | MCP-based IM 集成 | 15+ 平台 Gateway | 25+ 平台 + PWA + 原生 App | 飞书(成熟) + Telegram/WeChat/Discord(初步) |

---

## 一、立即可抄的高价值特性 (Quick Wins)

### 1.1 JSON 参数自动修复 — 来源：hermes

**现状**：marneo 直接 `json.loads()`，LLM 输出畸形 JSON 时工具调用失败。

**方案**：处理尾逗号、未闭合括号、Python `None` → `{}`。

**参考**：`hermes-agent/tools/model_tools.py` 中的 JSON repair pass，约 50 行代码。

### 1.2 Tool Loop Detection — 来源：openclaw

**现状**：marneo 无循环检测，agent 可能陷入无限工具调用循环。

**方案**：追踪连续重复的 tool call（同名+同参数），超过阈值（如 3 次）自动中断并返回错误。

**参考**：`openclaw/src/agents/tools/` 中的 `tools.loopDetection` 配置项。

### 1.3 Hermetic 测试隔离 — 来源：hermes

**现状**：conftest.py 基础，未完全隔离环境变量和临时目录。

**方案**：
```python
# conftest.py
@pytest.fixture(autouse=True)
def hermetic_env(tmp_path, monkeypatch):
    # 清除所有凭据环境变量
    for key in list(os.environ):
        if any(s in key for s in ['_API_KEY', '_TOKEN', '_SECRET']):
            monkeypatch.delenv(key, raising=False)
    # 隔离 MARNEO_HOME
    monkeypatch.setenv('MARNEO_HOME', str(tmp_path / '.marneo'))
    # 确定性运行
    monkeypatch.setenv('TZ', 'UTC')
    monkeypatch.setenv('LANG', 'C.UTF-8')
    monkeypatch.setenv('PYTHONHASHSEED', '0')
```

### 1.4 模型自动降级 Failover — 来源：hermes

**现状**：单 provider 无 fallback，API 报错直接失败。

**方案**：按错误类型分类（rate_limit → 等待重试、auth → 切换 provider、server_error → 降级到更便宜模型），hermes 的 `auxiliary_client` 模式。

### 1.5 Platform-Specific Hints — 来源：hermes

**现状**：所有 channel 用相同 system prompt，agent 不知道当前平台的格式能力。

**方案**：system prompt 注入平台特性（飞书支持卡片+表格、Telegram 支持 markdown、Discord 有 embed），让 agent 输出格式适配渠道。

### 1.6 FTS5 跨 Session 搜索 — 来源：hermes

**现状**：SQLite 存 episode 但无全文搜索。

**方案**：加 FTS5 虚拟表，支持跨 session 关键词搜索 + LLM 摘要。改动量小（SQLite 已有）。

---

## 二、架构级借鉴

### 2.1 Memory 系统增强

#### AutoDream 记忆整合（cc-haha + openclaw）

cc-haha 模式（适合 marneo）：
- **触发条件**：24h 或 5 session
- **四阶段**：orient（定向）→ collect（收集）→ consolidate（整合）→ prune（修剪）
- 自动合并重复、更新过期、压缩索引
- 输出通知："Improved N memories"

openclaw 模式（更精细）：
- **三阶段**：Light Sleep（摄取）→ Deep Sleep（加权评分晋升）→ REM Sleep（反思）
- **评分公式**：相关性 30% / 频率 24% / 时效性 15% / 查询多样性 15% / 整合度 10% / 概念丰富度 6%
- 可直接借鉴评分公式用于 episode → core 的 promotion

**推荐**：采用 cc-haha 的触发+阶段模型 + openclaw 的评分公式，实现 marneo 的 episode promotion 闭环。

#### Memory 智能召回（cc-haha）

当前 marneo 用 BM25 + vector hybrid retrieval，可增加一层：
- LLM reranking（Sonnet 做 relevance selection，最多 5 条）
- Session 内去重（避免重复浮现同一条 memory）
- Freshness warning（标注记忆的时效性）

### 2.2 插件/扩展系统

#### Manifest-First 插件（openclaw）

```json
{
  "id": "my-plugin",
  "enabledByDefault": false,
  "tools": ["custom_search"],
  "configSchema": { ... },
  "hooks": ["beforeAgentStart", "toolResultMiddleware"]
}
```

好处：
- 不执行代码就能发现插件能力
- Lazy load 运行时代码（启动快）
- 第三方插件安全隔离

#### MCP Tool Adapter（hermes）

动态发现 MCP server → 注册 tool schema → 运行时调用。接入后可用：
- Context7（库文档查询）
- Playwright（浏览器自动化）
- GitHub（代码搜索/PR 管理）
- Memory（知识图谱）

#### Skill 条件激活（cc-haha）

```yaml
# skill frontmatter
paths: ["src/**/*.py"]  # 只在编辑 Python 文件时激活
when_to_use: "For Python code review"
```

marneo 当前 skill 全量注入，可按项目/文件类型过滤。

### 2.3 多 Agent 协作

#### 5 种 Agent 类型（cc-haha）

| 类型 | 执行方式 | 上下文 | 适用场景 |
|------|---------|--------|---------|
| Subagent (sync) | 内联阻塞 | 隔离 | 直接任务 |
| Fork Subagent | 并行分叉 | **Cache 共享** | 并行任务（省钱） |
| Teammate | 进程/tmux | 独立 | 团队协作 |
| Remote | 远程沙箱 | 隔离 | 安全执行 |
| Async | 后台 | 分离 | 长任务（>120s 自动后台化） |

**marneo 可增加**：Fork（cache 共享降本）和 Async（后台长任务）。

#### Agent 邮箱通信（cc-haha）

文件锁 + mailbox 文件实现 agent 间异步通信：
- Lead agent 轮询 mailbox
- Agent 间可发消息、请求权限、共享发现
- 比 marneo 的 `asyncio.gather` 更灵活（支持异步、非阻塞）

### 2.4 Provider 集成

#### Credential Pool（hermes）

```python
class CredentialPool:
    sources = [env_vars, config_file, claude_code_creds, system_keyring]
    # 多 provider 凭据管理
    # 日志自动脱敏（只保留前缀）
    # Scoped to MARNEO_HOME
```

#### Model Metadata 表（hermes）

100+ 模型的 context length 查找表 + 动态推断：
- 精确 token 计数（而非 len(str)/4 估算）
- 自动检测 API 错误中的 context limit 信息
- 配合 marneo 的 context_budget 做精确管理

#### Prompt Caching Layout（hermes）

Anthropic 原生 cache layout vs OpenRouter wrapper layout 自动适配，降低 API 成本。

### 2.5 可观测性

#### OTEL 链路追踪（openclaw）

每个关键操作创建 span：
- agent_attempt → tool_execution → provider_call → channel_send
- 导出到 Jaeger/Datadog/Prometheus
- 请求 correlation ID 贯穿全链路

#### Token 用量追踪（hermes）

每轮记录到 SessionDB：
- input_tokens, output_tokens, cache_read, cache_write
- 按 session/provider/model 聚合成本
- 支持 budget 上限告警

#### Trajectory Export（openclaw）

JSON/Markdown 格式导出完整 agent session：
- 消息 + 工具调用 + 决策 + 时间戳
- 用于调试、审计、demo 录制

### 2.6 安全增强

#### 6 层权限系统（cc-haha）

```
1. Deny rules（显式黑名单）
2. Remote Skill auto-allow（规范前缀自动放行）
3. Allow rules（白名单）
4. Safe properties auto-allow（无 hook、无 tool 修改的安全属性）
5. Default: ask user（默认询问）
6. Permission feedback loop（反馈闭环）
```

比 marneo 当前的正则黑名单更完善，可逐步引入。

---

## 三、Marneo 独有优势（保持不变）

| 特性 | 说明 | 竞争力 |
|------|------|--------|
| **固定 System Prompt ≤4KB** | 三个开源项目都有 prompt 膨胀问题（cc-haha ~40KB+） | 核心差异化 |
| **Employee 成长系统** | 实习→初级→中级→高级，级别决定行为指令 | 独创 |
| **SOUL.md 身份叙事** | AI 面试生成持久人格 | 独创 |
| **Hybrid Retrieval** | BM25 + fastembed 混合检索 | 生产就绪 |
| **飞书流式卡片** | Card Kit v6 + 反应生命周期 | 最完善的飞书集成 |
| **Team Collaboration** | 原生 coordinator + specialist 模式 | 其他项目无内置团队协作 |

---

## 四、实施优先级

### P0 — 本周（1-3 天）
1. JSON 参数自动修复（~50 LOC）
2. Tool Loop Detection（~80 LOC）
3. Hermetic 测试隔离（~30 LOC conftest）

### P1 — 两周内
4. FTS5 跨 session 搜索
5. 模型 Failover + Credential Pool
6. Token 用量追踪
7. Episode → Core 自动 Promotion 闭环（借鉴 openclaw 评分公式）
8. Platform-Specific Hints

### P2 — 一个月内
9. MCP Tool Adapter
10. AutoDream 记忆整合
11. Manifest-First 插件系统
12. Fork Subagent（cache 共享）

### P3 — 长期规划
13. OTEL 链路追踪
14. 跨平台会话连续性
15. 6 层权限系统
16. Device Pairing
17. Trajectory Export

---

## 附录：关键参考文件

| 特性 | 项目 | 文件路径 |
|------|------|---------|
| Fork Cache 优化 | cc-haha | `src/utils/forkedAgent.ts` |
| AutoDream | cc-haha | `src/memdir/autoDream.ts` |
| JSON Repair | hermes | `tools/model_tools.py` |
| FTS5 Session | hermes | `hermes_state.py` (SessionDB) |
| Hermetic Tests | hermes | `tests/conftest.py` |
| Failover | hermes | `agent/run_agent.py` (fallback chain) |
| Dreaming 评分 | openclaw | `extensions/memory-core/src/short-term-promotion.ts` |
| Loop Detection | openclaw | `src/agents/tools/` |
| Manifest Plugin | openclaw | `extensions/*/openclaw.plugin.json` |
| OTEL Tracing | openclaw | `extensions/diagnostics-otel/` |
| Prompt Caching | hermes | `agent/anthropic_adapter.py` |
| 6 层权限 | cc-haha | `src/tools/permissions/` |
| MCP Adapter | hermes | `tools/mcp_tool.py` |
