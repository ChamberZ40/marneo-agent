## ADDED Requirements

### Requirement: 员工专属飞书 Bot 配置
每个员工 SHALL 能配置独立的飞书 Bot 凭证，存储在员工目录下。

#### Scenario: 配置员工飞书 Bot
- **WHEN** 用户运行 `marneo employee feishu setup GAI`
- **THEN** 向导引导填写 app_id/app_secret，验证后存储到 `~/.marneo/employees/GAI/feishu.yaml`

#### Scenario: Gateway 多员工启动
- **WHEN** 运行 `marneo gateway start` 且有多个员工配置了飞书 Bot
- **THEN** 每个员工的 FeishuChannelAdapter 独立启动，各自监听自己的 Bot 消息

#### Scenario: 消息路由到正确员工
- **WHEN** 飞书用户向员工 GAI 的 Bot 发消息
- **THEN** 消息路由到 GAI 的 ChatSession，而不是其他员工
