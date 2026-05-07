# Agent Loop 压测设计

## 目标

用真实 LLM API（当前配置的 MiniMax-M2.7）对 `ChatSession.send_with_tools()` 进行综合压测，覆盖：

1. **Token 消耗曲线** — 多轮对话中 token 用量随消息历史膨胀的趋势
2. **循环检测可靠性** — `_LOOP_DETECT_THRESHOLD` 能否及时中断重复调用
3. **长对话内存稳定性** — 多轮后进程 RSS 和消息列表是否合理
4. **飞书网关端到端** — 通过 `GatewayManager.dispatch()` 验证完整链路

## 执行顺序

阶段一：CLI 引擎直接测试 → 阶段二：飞书网关测试

## 文件结构

```
tests/stress/
├── __init__.py
├── conftest.py               # 共享 fixtures（registry、工具、reporter）
├── test_engine_stress.py     # 阶段一：引擎直接测试
├── test_feishu_stress.py     # 阶段二：飞书网关测试
└── results/                  # 输出目录（gitignored）
```

## 阶段一：CLI 引擎测试

### 工具注册

3 个轻量测试工具：

| 工具 | 参数 | 行为 |
|------|------|------|
| `get_current_time` | 无 | 返回当前时间戳 |
| `calculate` | `expression: str` | 安全数学运算 |
| `search_knowledge` | `query: str` | 返回 3 条固定假数据 |

### 测试场景

| 场景 | 轮次 | 采集指标 |
|------|------|----------|
| `test_token_curve` | 15 | 每轮 input/output tokens、消息历史条数、工具调用次数 |
| `test_loop_detection` | N/A | 中断轮次、error event 触发 |
| `test_memory_growth` | 20 | 每轮 RSS、messages 列表总字符数 |

### 多轮递进

每轮对话后，脚本基于上一轮回答的前 100 字 + 递进提示自动生成下一轮问题。

## 阶段二：飞书网关测试

不连真实 WebSocket，直接构造 `ChannelMessage` 调用 `GatewayManager.dispatch()`。

### Mock 层

- Mock `BaseChannelAdapter.send_reply` 捕获输出
- Mock Feishu-like `process_streaming`，确保 `GatewayManager._process()` 进入 streaming 分支但不创建真实 CardKit 卡片
- 使用真实 `SessionStore`、`ChatSession`、`ToolRegistry`

### 验证项

- Session 创建/复用
- 工具调用链完整性
- 多轮 session 内消息累积曲线
- 多 session 创建和复用表现

## 输出报告

### JSON 格式

每个场景输出一份 JSON 到 `tests/stress/results/`：

```json
{
  "test": "token_curve",
  "provider": "MiniMax-M2.7",
  "started_at": "2026-05-06T14:00:00",
  "rounds": [
    {"round": 1, "input_tokens": 320, "output_tokens": 150, "messages_count": 5, "tool_calls": 2}
  ],
  "total_input_tokens": 12000,
  "total_output_tokens": 3500,
  "peak_messages_count": 65
}
```

### JSON 报告

每个场景输出一份 JSON 到 `tests/stress/results/`。当前实现不生成聚合 `summary.txt`，如需要可后续补 report 汇总脚本。

## 运行方式

```bash
# 默认测试套件不会运行 stress（由 pytest.ini 排除）
pytest -q

# 阶段一
MARNEO_RUN_STRESS=1 pytest tests/stress/test_engine_stress.py -m stress -v -s

# 阶段二
MARNEO_RUN_STRESS=1 pytest tests/stress/test_feishu_stress.py -m stress -v -s

# 全部 stress
MARNEO_RUN_STRESS=1 pytest -m stress -v -s
```

## 注意事项

- 真实 API 调用会产生费用，预估 15 轮 × 3 场景 ≈ 50-100K tokens
- 循环检测测试可能被 rate limit 影响，加指数退避重试
- `tests/stress/results/` 应加入 `.gitignore`
