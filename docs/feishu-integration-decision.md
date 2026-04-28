# Marneo 飞书集成架构决策：lark_cli vs MCP Bridge

> 生成时间：2026-04-28
> 基于 OpenClaw / Hermes / Marneo 三项目对比分析

## 背景

Marneo 目前有两条路径接入飞书能力：

1. **lark_cli.py** — 直接 subprocess 调用 lark-cli（已实现）
2. **mcp_bridge.py** — 通过 MCP 协议桥接 lark-cli MCP server（已实现）

本文档记录架构决策及依据。

---

## 三种飞书集成模式对比

### 1. OpenClaw 模式：原生 SDK 导入

```
TypeScript 项目 → import @larksuiteoapi/node-sdk → 直接函数调用
```

- **优点**：零序列化开销，类型安全，IDE 补全
- **缺点**：仅限同语言（TypeScript），42,000 行代码，171 个文件
- **不适用于 Marneo**：Python 项目无法 import Node.js SDK

### 2. Hermes 模式：MCP Bridge

```
Python → MCP JSON-RPC over stdio → Node.js lark-cli 子进程
```

- **优点**：每个 API 独立 tool schema，Agent 无需记命令语法
- **缺点**：N 个工具 × 200 token/工具，需后台进程常驻，需 include/exclude 过滤
- **Hermes 选择此方案**：因为 Hermes 没有 lark-cli 直接调用的 wrapper

### 3. Marneo 模式：单 Tool CLI Wrapper

```
Python → subprocess.run("lark-cli ...") → 即开即走
```

- **优点**：1 个 tool schema ≈ 200 token 覆盖 190+ 能力，无后台进程
- **缺点**：Agent 需要构造 CLI 命令字符串
- **Marneo 选择此方案**：因为已有 `lark_cli.py` 且 LLM 对 CLI 语法掌握良好

---

## 定量对比

| 维度 | lark_cli.py | mcp_bridge.py |
|------|-------------|---------------|
| **Token / 轮** | ~200 tok（1 个 tool） | ~6,000 tok（30 个 tool） |
| **后台进程** | 无 | Node.js 常驻 |
| **启动时间** | 0（按需 subprocess） | 3-5s（MCP 握手） |
| **覆盖范围** | lark-cli 全部 190+ 命令 | 取决于 MCP server + include 过滤 |
| **额外依赖** | 无 | `pip install mcp` |
| **凭据管理** | 自动注入 app_id/secret | 需配置 env 传递 |
| **错误处理** | stdout/stderr 原始输出 | MCP 结构化 error |
| **Agent 易用性** | 需构造命令字符串 | 每个 tool 有独立 schema |

---

## 功能覆盖矩阵

### OpenClaw Feishu 插件 vs lark-cli

| 领域 | OpenClaw 原生 | lark-cli | Marneo 原生 |
|------|--------------|----------|-------------|
| **实时消息收发** | WebSocket/Webhook 事件驱动 | `im +messages-send/reply` | feishu.py（WebSocket） |
| **流式卡片** | CardKit Streaming API | 无 | feishu_streaming.py |
| **交互卡片回调** | 事件驱动 card-action | 无 | feishu.py |
| **打字指示器** | emoji reaction 模拟 | 无 | feishu.py（reaction lifecycle） |
| **消息去重** | event_id 3h TTL | 无 | gateway dedup |
| **文档 CRUD** | docx SDK 直接调用 | `docs +create/fetch/update` | via lark_cli |
| **Wiki** | wiki SDK 直接调用 | `wiki spaces/nodes` | via lark_cli |
| **多维表格** | 基础 CRUD | **50+ 命令** | via lark_cli |
| **电子表格** | 无 | **35+ 命令** | via lark_cli |
| **日历** | 无 | **7 命令** | via lark_cli |
| **任务** | 无 | **13 命令** | via lark_cli |
| **邮件** | 无 | **14 命令** | via lark_cli |
| **Drive 上传/下载** | 无 | 完整 | via lark_cli |
| **VC/妙记** | 无 | 查询/下载 | via lark_cli |
| **OKR** | 无 | 完整 | via lark_cli |
| **审批** | 原生审批卡片 | 实例查询/催办 | via lark_cli |
| **通讯录** | user/chat 查询 | `contact +get-user/search-user` | via lark_cli |
| **权限管理** | permission SDK | `drive permission.members` | via lark_cli |
| **通用 API** | 无 | `lark-cli api GET /open-apis/...` | via lark_cli |

### Marneo 实际覆盖总结

```
Marneo 原生实现（feishu.py + feishu_streaming.py）:
  ✅ 实时消息收发（WebSocket）
  ✅ 流式卡片（CardKit v6）
  ✅ 交互卡片回调
  ✅ 打字指示器（reaction lifecycle）
  ✅ 消息去重
  ✅ 图片/文件/PDF 附件处理
  ✅ 多模态支持

Marneo via lark_cli.py（1 个 tool 覆盖）:
  ✅ 文档（创建/读取/更新/搜索/媒体）
  ✅ Wiki（空间/节点/创建/移动）
  ✅ 多维表格（50+ 操作）
  ✅ 电子表格（35+ 操作）
  ✅ 日历（日程/创建/RSVP/空闲查询）
  ✅ 任务（创建/分配/清单/子任务）
  ✅ 邮件（发送/回复/搜索/监听）
  ✅ Drive（上传/下载/导入导出）
  ✅ 通讯录（查询/搜索）
  ✅ 权限（协作者 CRUD）
  ✅ VC/妙记/OKR/审批/考勤
  ✅ 任意飞书 API（通用调用）
```

**Marneo 原生 + lark_cli.py = OpenClaw Feishu 插件的超集。**

---

## 决策

### 飞书集成：继续使用 lark_cli.py

**理由：**

1. **Token 效率**：1 个 tool schema 覆盖 190+ 能力，比 MCP Bridge 的 N 个 tool 省 95%+ token
2. **零运维**：无后台进程，无连接管理，无重连逻辑
3. **完整覆盖**：lark-cli 的 190+ 命令已超过 OpenClaw 原生插件的能力范围
4. **已验证**：LLM 对 CLI 命令构造能力成熟，且 `lark_cli.py` 已自动注入凭据和默认参数

### MCP Bridge：保留作为通用基础设施

**mcp_bridge.py 的价值不在飞书，而在接入其他生态：**

| MCP Server | 用途 | 适合 Bridge? |
|------------|------|-------------|
| GitHub MCP | 代码搜索/PR 管理 | 适合（Marneo 无原生 GitHub 工具） |
| Playwright MCP | 浏览器自动化 | 适合（Marneo 无浏览器能力） |
| Context7 MCP | 库文档查询 | 适合 |
| Slack MCP | Slack 消息 | 适合 |
| Memory MCP | 知识图谱 | 视需求 |
| **Feishu/Lark CLI** | **飞书 API** | **不需要 — lark_cli.py 更优** |

### 后续行动

- [ ] `lark_cli.py` 保持不变，作为飞书主力工具
- [ ] `mcp_bridge.py` 保留，但不用于飞书
- [ ] 未来接入 GitHub/Playwright 等非飞书 MCP server 时启用 bridge
- [ ] 考虑给 `lark_cli.py` 补充常用命令示例到 skill 中，帮助 Agent 更快构造正确命令

---

## 附录：为什么 MCP Bridge 对飞书反而是劣势

### Token 膨胀示例

假设通过 MCP Bridge 注册 30 个飞书工具（已经过 include 过滤）：

```
每轮 API 请求:
  system prompt          1,000 tok
  30 个 tool schemas     6,000 tok  ← MCP Bridge
  对话历史              2,000 tok
  ─────────────────────────────────
  总计                   9,000 tok

vs lark_cli.py:
  system prompt          1,000 tok
  1 个 tool schema         200 tok  ← lark_cli
  对话历史              2,000 tok
  ─────────────────────────────────
  总计                   3,200 tok
```

5 轮工具调用循环，差异：
- MCP Bridge: 9,000 × 5 = 45,000 input tok ≈ $0.135
- lark_cli.py: 3,200 × 5 = 16,000 input tok ≈ $0.048

**每次对话节省 ~65% input token 成本。**

### 唯一例外

如果未来需要 **lark-cli 不支持的飞书能力**（目前未发现），可通过以下方式补充：

1. `lark-cli api <METHOD> <PATH>` 通用 API 调用（已覆盖任意端点）
2. `feishu_tools.py` 直接 HTTP 调用（已有雏形）
3. MCP Bridge 作为最后 fallback

当前无此需求。
