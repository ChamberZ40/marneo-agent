## ADDED Requirements

### Requirement: 飞书适配器双模式连接
系统 SHALL 支持 WebSocket（默认）和 Webhook 两种连接模式，通过 `connection_mode` 配置切换，两种模式均能可靠接收飞书事件。

#### Scenario: WebSocket 模式启动
- **WHEN** `connection_mode` 为 `websocket` 且 `app_id`/`app_secret` 有效
- **THEN** 在独立线程 + 独立 event loop 中建立长连接，断开后自动以指数退避重连

#### Scenario: Webhook 模式启动
- **WHEN** `connection_mode` 为 `webhook`
- **THEN** 启动 aiohttp 服务器监听 `webhook_host:webhook_port`，验证飞书签名后处理事件

#### Scenario: 白名单过滤
- **WHEN** `allowed_users` 非空，且收到列表外用户的消息
- **THEN** 静默丢弃该消息，不触发处理也不回复

---

### Requirement: 消息处理 Reaction 反馈
系统 SHALL 在处理飞书消息时通过 reaction 向用户实时反馈处理状态。

#### Scenario: 开始处理
- **WHEN** 收到用户消息并开始路由处理
- **THEN** 在该消息上添加 ⏳ reaction

#### Scenario: 处理成功
- **WHEN** 成功生成并发送回复
- **THEN** 移除 ⏳ reaction，添加 ✅ reaction

#### Scenario: 处理失败
- **WHEN** 处理过程中发生未捕获异常
- **THEN** 移除 ⏳ reaction，添加 ❌ reaction

---

### Requirement: 磁盘持久化消息去重
系统 SHALL 将已处理的飞书消息 ID 持久化到磁盘，确保 gateway 重启后不重复处理平台重发的消息。

#### Scenario: 重启后去重
- **WHEN** gateway 重启后，飞书平台重发同一 `msg_id`
- **THEN** 系统从 `~/.marneo/feishu/dedup_{app_id}.json` 中检测到重复，跳过处理

#### Scenario: 过期条目清理
- **WHEN** 去重记录超过 24 小时
- **THEN** 系统定期清理过期条目，防止文件无限增长

---

### Requirement: 媒体消息接收
系统 SHALL 下载并本地缓存飞书消息中的图片、文件和语音附件。

#### Scenario: 图片消息
- **WHEN** 收到包含图片的飞书消息
- **THEN** 下载图片到 `~/.marneo/media/`，将本地路径传入处理上下文

#### Scenario: 卡片按钮点击
- **WHEN** 用户点击飞书交互卡片上的按钮
- **THEN** 解析 `action.value` 并作为文本消息路由给 `manager.dispatch()`
