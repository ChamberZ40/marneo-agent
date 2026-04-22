## ADDED Requirements

### Requirement: Docker 容器化部署
系统 SHALL 提供 `Dockerfile` 和 `docker-compose.yml`，支持以非 root 用户运行，数据持久化到宿主机卷。

#### Scenario: docker-compose 启动
- **WHEN** 执行 `docker-compose up -d`（配置 env 已设置）
- **THEN** marneo gateway 在容器中启动，`~/.marneo/` 数据挂载到宿主机卷，重启容器后数据不丢失

#### Scenario: 非 root 运行
- **WHEN** 容器启动
- **THEN** 进程以 `marneo` 用户身份运行，不以 root 执行

---

### Requirement: 环境变量配置覆盖
系统 SHALL 支持通过环境变量覆盖配置文件中的值，env 变量优先级高于配置文件。

#### Scenario: API Key 注入
- **WHEN** 设置环境变量 `MARNEO_PROVIDER_API_KEY=sk-xxx` 并启动
- **THEN** 系统使用 env 中的 API key，忽略配置文件中的对应值

#### Scenario: 变量引用展开
- **WHEN** 配置文件中的值为 `${FEISHU_APP_SECRET}`
- **THEN** 系统在加载时展开为对应 env 变量的值

---

### Requirement: HTTP 健康检查端点
系统 SHALL 在 gateway 运行期间暴露 HTTP 健康检查端点，供 Docker、systemd 和负载均衡器探测存活状态。

#### Scenario: 健康检查响应
- **WHEN** `GET http://localhost:8765/health`（gateway 正常运行中）
- **THEN** 返回 HTTP 200，JSON body：`{"status": "ok", "pid": N, "uptime_seconds": N, "connected_channels": [...]}`

#### Scenario: 未启动时无响应
- **WHEN** gateway 未运行，发起健康检查请求
- **THEN** 连接被拒绝（端口未监听），Docker healthcheck 标记为 unhealthy

---

### Requirement: 系统服务集成
系统 SHALL 提供 systemd（Linux）和 launchd（macOS）服务文件，并通过 CLI 命令一键安装。

#### Scenario: Linux 服务安装
- **WHEN** 在 Linux 上执行 `marneo gateway install-service`
- **THEN** `marneo-gateway.service` 被复制到 `/etc/systemd/system/`，`systemctl enable` 注册开机自启

#### Scenario: macOS 服务安装
- **WHEN** 在 macOS 上执行 `marneo gateway install-service`
- **THEN** `com.marneo.gateway.plist` 被复制到 `~/Library/LaunchAgents/`，`launchctl load` 立即启动
