# Marneo Agent

> **Mare**（马）+ **Neo**（新）= **新马** 🐴

**Marneo** 是项目数字员工系统——不是个人助理，是专注项目的 AI 员工。

## 快速开始

```bash
pip install -e .
marneo setup          # 配置 LLM Provider
marneo hire           # 招聘第一位数字员工
marneo work           # 开始工作
```

## 完整命令

```
# 仪表板
marneo                     启动仪表板（显示员工/项目/网关状态）
marneo status              全局状态详情

# 员工
marneo hire                招聘员工（LLM 动态面试 → SOUL.md）
marneo work [--employee]   与员工对话（自动携带项目上下文）
marneo employees list      列出所有员工
marneo employees show      查看员工详情

# 项目
marneo projects new        创建项目（LLM 面试补充知识）
marneo projects list       列出项目
marneo projects show       查看项目详情
marneo assign <project>    将员工分配到项目

# 技能
marneo skills list         列出技能（global + 项目）
marneo skills add          手动添加技能
marneo skills show         查看技能

# 报告
marneo report daily        日报（--push 推送到 IM）
marneo report weekly       周报
marneo report history      历史记录
marneo report push-config  配置推送目标

# 网关
marneo gateway start       后台启动 IM 网关
marneo gateway stop        停止网关
marneo gateway status      查看状态
marneo gateway logs        查看日志
marneo gateway channels list   渠道状态
marneo gateway channels add    配置渠道
marneo gateway channels test   测试连接

# 配置
marneo setup               配置 LLM Provider（交互向导）
marneo --version           版本信息
```

## 支持的 IM 渠道

| 渠道 | 接入方式 |
|------|---------|
| 飞书 / Feishu | WebSocket 长连接（lark-oapi SDK） |
| 微信 / WeChat | Tencent iLink Bot（QR 扫码登录） |
| Telegram | Bot API（python-telegram-bot） |
| Discord | Bot API（discord.py） |

## 数据目录

```
~/.marneo/
├── config.yaml              # LLM Provider + 渠道配置
├── gateway.pid / gateway.log
├── employees/
│   └── <name>/
│       ├── profile.yaml     # 等级、成就
│       ├── SOUL.md          # 身份自述
│       ├── push.yaml        # 报告推送配置
│       └── reports/         # 日报/周报
└── projects/
    └── <name>/
        ├── project.yaml     # KPI、成员
        ├── AGENT.md         # 工作档案
        └── skills/          # 项目技能
```

## 路线图

- ✅ Phase 1 — CLI + Provider + 对话 TUI
- ✅ Phase 2 — 员工系统（hire/work/employees/report）
- ✅ Phase 3 — 项目系统（projects/assign/skills）
- ✅ Phase 4 — Gateway（飞书/微信/Telegram/Discord）
- ✅ Phase 5 — 打磨（dashboard/status/push/auto-learn）
