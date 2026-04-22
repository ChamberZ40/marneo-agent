# Change: 代码质量生产级标准

## Why

当前代码缺少完整测试、类型注解不统一、日志无结构化上下文，不满足生产标准。核心模块（employee、project、gateway）无单元测试覆盖，任何重构都存在回归风险。

## What Changes

- **单元测试**：核心模块测试覆盖率 ≥ 80%（employee、project、gateway）
- **类型注解**：所有公开函数签名补全 type hints，Pyright basic 通过
- **结构化日志**：所有 log 语句携带 employee/project/session 上下文字段
- **输入验证**：CLI 参数和配置文件加 validation，失败时友好错误提示

## Impact

- Affected specs: quality（新建）
- Affected code: 全项目（`marneo/core/`、`marneo/employee/`、`marneo/project/`、`marneo/gateway/`）
- New files: `tests/` 目录、`marneo/core/logging.py`
