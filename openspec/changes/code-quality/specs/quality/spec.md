## ADDED Requirements

### Requirement: 核心模块单元测试覆盖率
系统核心模块 SHALL 达到 80% 单元测试覆盖率，使用 pytest + pytest-cov 验证，并在 CI 中强制执行。

#### Scenario: 测试套件通过
- **WHEN** 执行 `pytest tests/ --cov=marneo --cov-fail-under=80`
- **THEN** 所有测试通过，覆盖率报告显示 ≥ 80%

#### Scenario: 覆盖率不足阻断
- **WHEN** 新代码导致覆盖率低于 80%
- **THEN** pytest 以非零退出码退出，CI 流水线阻断合并

---

### Requirement: 结构化日志上下文
系统 SHALL 在所有日志条目中携带业务上下文字段，便于生产环境追踪和告警。

#### Scenario: Gateway 处理消息日志
- **WHEN** `GatewayManager` 处理一条消息
- **THEN** 日志条目包含 `platform`、`chat_id`、`employee_name` 字段

#### Scenario: Employee 面试日志
- **WHEN** `interview.py` 记录面试进度
- **THEN** 日志条目包含 `employee_name`、`question_index` 字段

---

### Requirement: 公开函数类型注解
系统所有公开函数 SHALL 具备完整的参数和返回值类型注解，通过 Pyright basic 静态检查。

#### Scenario: Pyright 检查通过
- **WHEN** 运行 `pyright marneo/` （basic 模式）
- **THEN** 输出零错误，零 "unknown return type" 警告

---

### Requirement: 配置加载输入验证
系统 SHALL 在启动时校验配置文件，缺失或格式错误的字段 SHALL 输出具体字段名并以非零退出码退出。

#### Scenario: 缺失必填字段
- **WHEN** 配置文件缺少 `provider.api_key`
- **THEN** 输出 "配置错误: 缺少字段 provider.api_key" 并退出，而非 KeyError 堆栈
