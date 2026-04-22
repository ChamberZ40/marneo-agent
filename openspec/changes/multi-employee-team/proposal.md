# Change: 多员工并行团队协作

## Why

单一员工无法完成复杂的多面向任务。需要支持同一项目的多个员工在飞书群里互相协作：协调者员工接收用户消息，@mention 专员员工处理子任务，最终汇总回复。

## What Changes

- 项目可配置 team：员工列表 + 角色 + 协调者
- `marneo team` 命令：setup/add/remove/list
- 协调者员工在团队飞书群中 @mention 其他员工
- 专员员工响应 @mention，处理子任务，回复到群
- 协调者等待专员回复后汇总

## Impact

- Affected specs: team（新建）
- Affected code:
  - `marneo/collaboration/team.py`（新建）
  - `marneo/collaboration/coordinator.py`（新建）
  - `marneo/cli/team_cmd.py`（新建）
  - `marneo/project/workspace.py`（添加 team 配置）
  - `marneo/gateway/adapters/feishu.py`（支持团队群 @mention 路由）
