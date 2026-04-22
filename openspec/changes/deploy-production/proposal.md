# Change: 部署生产级支持

## Why

marneo 目前只能手动运行，缺乏服务器部署能力。需要 Docker 容器化和系统服务集成，使其可以在服务器上稳定运行，并支持 CI/CD 流水线注入配置。

## What Changes

- **Docker**：`Dockerfile` + `docker-compose.yml`，一键启动全套服务
- **systemd**：Linux 系统服务文件，开机自启
- **launchd**：macOS 服务文件，开机自启
- **环境变量**：所有配置支持 env 注入（适配 CI/CD 和 Docker）
- **健康检查**：gateway 暴露 `/health` 端点，返回运行状态

## Impact

- Affected specs: deploy（新建）
- Affected code: `marneo/gateway/manager.py`（添加 health 端点）、`marneo/core/config.py`（env 覆盖）
- New files: `Dockerfile`、`docker-compose.yml`、`.env.example`、`deploy/marneo-gateway.service`、`deploy/com.marneo.gateway.plist`
