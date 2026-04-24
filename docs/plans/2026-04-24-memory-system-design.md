# Marneo Memory System Design

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:writing-plans to implement this design task-by-task.

**Goal:** 设计并实现 marneo 的分层记忆系统，在保证员工身份和关键约束不丢失的前提下，将 system prompt 体积控制在可配置的固定上限内，解决 openclaw/hermes 随使用时间增长导致的 token 消耗过大和响应变慢问题。

---

## 核心原则

1. **System prompt 固定上限** — 不管加多少 skill、经验、项目，system prompt 体积不变
2. **按需检索** — 所有 skill 和经验通过 BM25 + 向量混合检索动态注入，用完即清
3. **分级记忆** — Core Memory（永远加载）vs Episodic（按需） vs Working（任务级）
4. **Skills 完全动态** — `~/.marneo/skills/` 里的 skill 不预加载任何内容，检索后按需读取完整内容

---

## 记忆架构

### 三层记忆

```
┌─────────────────────────────────────────────────────┐
│  Core Memory（核心记忆）                              │
│  永远在 system prompt 里，体积可控（≤1000 chars）      │
│  写入：人工 + LLM 自动提炼 + 经验晋升                 │
└─────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────┐
│  Episodic Memory（经验记忆）                          │
│  不在 system prompt，通过混合检索按需注入              │
│  包含：Skills + 工作经验 + 项目知识                   │
│  写入：LLM 对话后自动提炼 + 外部 skill 导入           │
└─────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────┐
│  Working Memory（工作记忆）                           │
│  当前对话历史，有轮次上限，任务完成后提炼并清空         │
└─────────────────────────────────────────────────────┘
```

### System Prompt 组成（固定）

```
SOUL.md            ≤ 2,000 chars  （员工身份，不变）
Core Memory        ≤ 1,000 chars  （关键约束，人工+自动写入）
─────────────────────────────────
固定总计           ≤ 3,000 chars

+ 动态注入（按需，用完即清）
检索到的 skill/经验 ≤ 1,500 chars  （最多 3 条）
─────────────────────────────────
单轮最大            ≤ 4,500 chars
```

---

## 存储结构

```
~/.marneo/employees/<name>/
├── memory/
│   ├── core.md              # 核心记忆（YAML frontmatter + 内容）
│   └── episodes/
│       ├── index.db         # SQLite：BM25 全文 + 元数据
│       └── vectors.bin      # fastembed 本地向量
│
~/.marneo/skills/            # 现有路径保持不变
│   ├── pandas-encoding.md   # skill 文件（name + description + 完整内容）
│   ├── git-safety.md
│   └── ...
```

### Core Memory 格式（`core.md`）

```markdown
---
updated_at: 2026-04-24
---

## 关键约束
- API key 不能提交到 git（来源：用户设定）
- v1 接口不能改动（来源：2026-04-10 对话，客户要求）

## 工作偏好
- 代码用 Python，不用 JavaScript（来源：自动提炼）
```

### Episodic Memory 每条记录

```python
{
  "id": "ep_1714012800",
  "content": "用 pandas 处理飞书导出数据时遇到 UTF-8 编码问题，解决方案：pd.read_csv(path, encoding='utf-8-sig')",
  "source": "episode",          # "episode" | "skill"
  "skill_id": None,             # 如果是 skill，存 skill 文件 id
  "type": "discovery",          # decision/preference/discovery/problem/advice
  "tags": ["pandas", "encoding", "feishu"],
  "project": "data-ops",
  "importance": 0.85,
  "access_count": 3,            # 被召回次数（用于晋升判断）
  "created_at": "2026-04-24",
  "promoted_to_core": False,
}
```

---

## 检索机制（混合检索）

### 检索流程

```
用户消息
    ↓
① 预检索（每轮自动，<50ms）
   BM25(message) ∪ fastembed(message)
   搜索范围：episodes.db + skills/ 索引
   → top-3 相关结果（score > threshold）
   → 注入本轮 context（不写入 messages 历史）
    ↓
② LLM 处理（含工具列表）
    ↓
③ LLM 主动召回（按需）
   LLM 调用 recall_memory(query, type?) 工具
   → 返回更多相关片段 → 注入当前轮
    ↓
④ LLM 调用 get_skill(skill_id) 工具
   → 读取 ~/.marneo/skills/<id>.md 完整内容
   → 注入当前轮
    ↓
⑤ 对话结束后
   heuristic 提取 → 写入 episodes.db
   高频/重要经验 → 晋升为 Core Memory
```

### Skills 检索方式

Skills 在 index.db 里只存 `name` + `description` 作为检索索引，完整内容按需从文件读取：

```python
# 检索时：只用 name + description 做向量/BM25
skill_index = {"id": "pandas-encoding", "name": "pandas 编码", "description": "处理飞书导出 UTF-8 问题"}

# 命中后：读完整内容
get_skill("pandas-encoding") → open("~/.marneo/skills/pandas-encoding.md").read()
```

### 混合检索算法（参考 mempalace）

```python
def retrieve(query, n=3, threshold=0.6):
    # Floor: 向量检索（fastembed）
    vec_results = vector_search(query, n * 3)

    # Signal: BM25 re-rank
    candidates = bm25_rerank(vec_results, query)

    # 过滤 + 取 top-n
    return [r for r in candidates if r.score > threshold][:n]
```

---

## Core Memory 写入机制

### 三条写入路径

| 方式 | 触发 | 操作 |
|---|---|---|
| 人工设定 | `marneo employees memory add --core "..."` | 直接追加到 core.md |
| LLM 自动提炼 | 对话中检测到关键约束/决策 | LLM 调用 `add_core_memory(content)` 工具 |
| 经验晋升 | `access_count >= 5` 或用户标记重要 | 自动从 episodes 提升到 core.md |

### LLM 可用的记忆工具

```python
# 主动召回更多记忆
recall_memory(query: str, type?: "skill"|"episode") -> list[MemoryItem]

# 读取完整 skill 内容
get_skill(skill_id: str) -> str

# 写入核心记忆（LLM 判断重要时调用）
add_core_memory(content: str, reason: str) -> bool

# 写入经验记忆（对话结束后系统自动调用，LLM 也可主动）
add_episode(content: str, type: str, tags: list[str]) -> bool
```

---

## Working Memory 管理

```python
# 可配置上限（~/.marneo/config.yaml）
context_budget:
  system_prompt_max: 4000      # system prompt 上限（chars）
  working_memory_turns: 20     # 保留最近 N 轮
  episodic_inject_max: 1500    # 动态注入上限（chars）
  tool_result_max: 50000       # 单次工具结果上限（chars）
  core_memory_max: 1000        # core.md 上限（chars）

# 超出 working_memory_turns → 移除最早轮次
# 任务完成信号 → 提炼经验 → 清空 working memory
```

---

## 对比现有方案

| 指标 | 现在 | 新设计 |
|---|---|---|
| System prompt 体积 | 无限增长（随 skill 积累）| 固定 ≤ 4,500 chars |
| 100 个 skill 的影响 | +50,000 chars | 0（不预加载）|
| OpenClaw 对比 | — | OpenClaw: 39,759 chars 固定 |
| Skill 加载失败 | 超出 context 后失效 | 不存在（按需加载）|
| 响应速度随时间 | 越来越慢 | 稳定（context 固定）|

---

## 依赖

```toml
# pyproject.toml 新增
fastembed = ">=0.4.0"    # 本地向量，~50MB 模型，无 GPU
rank-bm25 = ">=0.2.2"   # BM25 算法
# SQLite 内置，无需额外依赖
```

---

## 迁移

现有 `~/.marneo/skills/*.md` 文件无需改动，首次启动时自动建索引：

```bash
marneo memory index rebuild   # 重建 skill 索引 + 经验向量
marneo memory stats           # 查看记忆库统计
```
