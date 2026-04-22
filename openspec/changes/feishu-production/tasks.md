## 1. 双模式连接

- [ ] 1.1 添加 `connection_mode` 配置字段（`websocket` | `webhook`，默认 `websocket`）
- [ ] 1.2 WebSocket 模式：独立线程 + 独立 event loop（已有，修复稳定性 — 捕获异常自动重连）
- [ ] 1.3 Webhook 模式：启动 aiohttp 服务器监听 `webhook_host:webhook_port`，路由 POST 事件

## 2. 磁盘持久化去重

- [ ] 2.1 创建 `MessageDeduplicator` 类：JSON 文件存储 `~/.marneo/feishu/dedup_{app_id}.json`，TTL=24h
- [ ] 2.2 启动时加载已有记录；处理每条消息后写入 msg_id；定期（每小时）清理过期条目

## 3. Reaction 反馈

- [ ] 3.1 收到消息时调用 MessageReaction API 添加 ⏳ reaction
- [ ] 3.2 处理成功后移除 ⏳，添加 ✅ reaction
- [ ] 3.3 处理失败时移除 ⏳，添加 ❌ reaction

## 4. 媒体支持

- [ ] 4.1 图片消息：下载到 `~/.marneo/media/`，在上下文中传递本地路径
- [ ] 4.2 文件消息：同上，记录文件名和 MIME 类型
- [ ] 4.3 语音消息：下载 opus 文件，可选调用外部 ASR 转文字

## 5. 卡片按钮点击

- [ ] 5.1 注册 `P2CardActionTrigger` 事件处理器
- [ ] 5.2 解析点击事件中的 `action.value`，构造文本消息路由给 `manager.dispatch()`

## 6. 白名单 + Webhook 签名验证

- [ ] 6.1 `allowed_users` 配置：空列表 = 不限制；非空 = 仅列表内 open_id 可触发处理
- [ ] 6.2 Webhook 模式：验证请求头中的 `X-Lark-Signature`，不匹配则返回 403
