## 1. 员工飞书配置数据层

- [ ] 1.1 创建 `marneo/employee/feishu_config.py`：save/load/exists/list_configured
- [ ] 1.2 feishu.yaml 结构：app_id, app_secret, domain, bot_open_id, team_chat_id

## 2. CLI 命令

- [ ] 2.1 创建 `marneo/cli/employee_feishu_cmd.py`
- [ ] 2.2 `marneo employee feishu setup <name>`：向导配置（填凭证→验证→保存）
- [ ] 2.3 `marneo employee feishu status <name>`：显示配置状态
- [ ] 2.4 将 feishu 子命令注册到 employees_cmd 或 app.py

## 3. Gateway 多员工适配器

- [ ] 3.1 GatewayManager.start_all：扫描所有员工的 feishu.yaml，为每个员工创建 FeishuChannelAdapter
- [ ] 3.2 FeishuChannelAdapter 添加 employee_name 属性
- [ ] 3.3 dispatch 时 ChannelMessage 携带 employee_name，路由到对应员工的 ChatSession
