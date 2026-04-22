# Change: 员工专属飞书 Bot 配置

## Why

当前飞书 Bot 配置是全局的，无法支持多个员工各自有独立的飞书 Bot。需要为每个员工配置独立的飞书 App 凭证，使每个员工成为独立的飞书机器人。

## What Changes

- 每个员工有专属飞书配置：`~/.marneo/employees/<name>/feishu.yaml`
- 新增命令：`marneo employee feishu setup <name>` — 向导配置员工飞书 Bot
- 新增命令：`marneo employee feishu status <name>` — 查看员工飞书配置
- Gateway 启动时：读取所有员工的 feishu.yaml，为每个员工注册独立的 FeishuChannelAdapter
- 消息路由：适配器知道自己代表哪个员工，dispatch 时携带 employee 信息

## Impact

- Affected specs: employee（新增飞书配置相关）
- Affected code:
  - `marneo/employee/feishu_config.py`（新建）
  - `marneo/cli/employee_feishu_cmd.py`（新建）
  - `marneo/cli/employees_cmd.py`（添加 feishu 子命令）
  - `marneo/gateway/manager.py`（start_all 读取员工飞书配置）
  - `marneo/gateway/adapters/feishu.py`（适配器携带 employee_name）
