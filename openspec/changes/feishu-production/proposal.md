# Change: 飞书适配器生产级完整化

## Why

当前 `marneo/gateway/adapters/feishu.py` 仅 270 行，缺少生产环境所需的可靠性功能。参考 Hermes feishu.py（4360 行）全面升级，使飞书渠道达到生产可用标准。

## What Changes

- **双模式连接**：WebSocket（默认，无需公网）+ Webhook（需公网 URL）
- **媒体支持**：收发图片/文件/音频，缓存到 `~/.marneo/media/`
- **Reaction 反馈**：收到消息加 ⏳ reaction，完成后改 ✅，失败改 ❌
- **卡片按钮点击**：P2CardActionTrigger 路由到 `manager.dispatch()`
- **磁盘持久化去重**：`~/.marneo/feishu/dedup_{app_id}.json`，重启不丢
- **白名单控制**：`allowed_users` 配置，空列表 = 不限制
- **Webhook 签名验证**：`verification_token` 校验

## Impact

- Affected specs: feishu（新建）
- Affected code: `marneo/gateway/adapters/feishu.py`（重写）
- New config fields: `connection_mode`, `allowed_users`, `verification_token`, `webhook_host`, `webhook_port`
