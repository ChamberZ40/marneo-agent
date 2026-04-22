## 1. Docker 容器化

- [ ] 1.1 编写 `Dockerfile`（Python 3.11 slim，非 root 用户 `marneo`，`~/.marneo` 挂载为 volume）
- [ ] 1.2 编写 `docker-compose.yml`（marneo gateway 服务 + 数据卷 `marneo-data:/home/marneo/.marneo`）
- [ ] 1.3 添加 `.dockerignore`（排除 `__pycache__`、`*.egg-info`、`.env`、`tests/`）

## 2. 环境变量支持

- [ ] 2.1 `marneo/core/config.py`：支持 `MARNEO_PROVIDER_API_KEY` / `MARNEO_MODEL` 等 env 覆盖（env 优先于 config 文件）
- [ ] 2.2 gateway channel 凭证支持 `${ENV_VAR}` 引用展开（feishu app_secret、telegram token 等）
- [ ] 2.3 添加 `.env.example`，列出所有可用 env 变量及说明

## 3. 系统服务文件

- [ ] 3.1 `deploy/marneo-gateway.service`（systemd，Linux，`Restart=always`，`WantedBy=multi-user.target`）
- [ ] 3.2 `deploy/com.marneo.gateway.plist`（launchd，macOS，`RunAtLoad=true`，日志到 `~/Library/Logs/marneo/`）
- [ ] 3.3 `marneo gateway install-service` CLI 命令：检测 OS，复制服务文件到系统目录，执行 enable/load

## 4. 健康检查端点

- [ ] 4.1 `marneo/gateway/manager.py`：启动 aiohttp 健康检查服务器（默认 `0.0.0.0:8765`，路由 `GET /health`）
- [ ] 4.2 `/health` 返回 JSON：`{status, pid, uptime_seconds, connected_channels: [...]}`
- [ ] 4.3 `Dockerfile` 添加 `HEALTHCHECK` 指令：`curl -f http://localhost:8765/health`
