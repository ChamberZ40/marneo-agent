# Marneo Agent Phase 5 — Polish & Ecosystem Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 打磨用户体验：`marneo` 启动仪表板、首次运行引导、全局状态命令、报告推送到 Gateway、Skill 自动学习、README 文档。

**Architecture:** 五个独立改进模块，互不依赖可并行实现。无新模块，全部修改/扩展现有文件。

**Tech Stack:** Python 3.11+, typer, rich（已有）

---

## Task 1: `marneo` 启动仪表板 + 首次运行引导

**Files:**
- Modify: `marneo/cli/app.py`

### Step 1: 更新 `app.py` 的 `main()` callback

当无子命令时，不直接进 `marneo work`，而是先判断是否已配置：

```python
@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False, "--version", "-v",
        callback=_version_cb, is_eager=True,
        help="Show version.",
    ),
) -> None:
    """Marneo — Project-focused digital employees."""
    if ctx.invoked_subcommand is not None:
        return

    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich import box as rich_box

    console = Console()
    from marneo import __version__
    from marneo.core.config import is_configured
    from marneo.employee.profile import list_employees
    from marneo.project.workspace import list_projects
    from marneo.gateway.config import load_channel_configs

    # ── First-run wizard ──────────────────────────────────────────────
    if not is_configured():
        console.print()
        console.print(Panel(
            f"[bold #FF6611]欢迎使用 Marneo v{__version__}[/bold #FF6611]\n\n"
            "新马，新征程。\n\n"
            "[dim]首次使用需要完成初始配置：[/dim]\n"
            "  1. 配置 LLM Provider\n"
            "  2. 招聘第一位数字员工\n\n"
            "运行 [bold]marneo setup[/bold] 开始配置。",
            border_style="#FF6611", padding=(1, 2),
        ))
        return

    employees = list_employees()
    if not employees:
        console.print()
        console.print(Panel(
            "[bold #FFD700]Provider 已配置，还没有员工。[/bold #FFD700]\n\n"
            "运行 [bold]marneo hire[/bold] 招聘第一位数字员工。",
            border_style="#FFD700", padding=(1, 1),
        ))
        return

    # ── Dashboard ─────────────────────────────────────────────────────
    from marneo.employee.profile import load_profile
    from marneo.employee.growth import days_at_level

    console.print()
    console.print(f"[bold #FF6611]◆ Marneo[/bold #FF6611]  [dim]v{__version__}[/dim]")
    console.print()

    # Employees
    t = Table(box=rich_box.SIMPLE, show_header=True, header_style="bold")
    t.add_column("员工", style="bold cyan")
    t.add_column("等级", style="#FFD700")
    t.add_column("项目")
    t.add_column("在职天数", justify="right", style="dim")

    from marneo.project.workspace import get_employee_projects
    for name in employees:
        p = load_profile(name)
        if p:
            projs = get_employee_projects(name)
            t.add_row(
                name, p.level,
                ", ".join(proj.name for proj in projs[:2]) or "—",
                str(days_at_level(p)),
            )
    console.print(t)

    # Gateway status
    from marneo.cli.gateway_cmd import _read_pid
    gw = "[green]🟢 运行中[/green]" if _read_pid() else "[dim]⚪ 未启动[/dim]"
    channels = load_channel_configs()
    enabled_ch = [p for p, c in channels.items() if c.get("enabled")]
    ch_str = ", ".join(enabled_ch) if enabled_ch else "未配置"
    console.print(f"  网关：{gw}  渠道：[dim]{ch_str}[/dim]")
    console.print()
    console.print(f"  [dim]marneo work     开始工作[/dim]")
    console.print(f"  [dim]marneo hire      招聘员工[/dim]")
    console.print(f"  [dim]marneo projects  管理项目[/dim]")
    console.print()
```

### Step 2: 测试

```bash
cd /Users/chamber/code/marneo-agent

# First-run (no provider)
python3 -c "
from marneo.core.config import load_config, save_config, ProviderConfig
# backup
cfg = load_config()
"

# Normal run (with employees)
marneo
```

Expected: 显示仪表板（员工列表 + 网关状态 + 快捷命令）

### Step 3: Commit

```bash
git add marneo/cli/app.py
git commit -m "feat: add marneo dashboard with first-run wizard"
```

---

## Task 2: `marneo status` 全局状态命令

**Files:**
- Create: `marneo/cli/status_cmd.py`
- Modify: `marneo/cli/app.py`

### Step 1: 创建 `marneo/cli/status_cmd.py`

```python
# marneo/cli/status_cmd.py
"""marneo status — show global system status."""
from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel

console = Console()


def cmd_status() -> None:
    """显示全局状态：Provider、员工、项目、Gateway。"""
    from rich.table import Table
    from rich import box as rich_box
    from marneo.core.config import load_config, is_configured
    from marneo.employee.profile import list_employees, load_profile
    from marneo.employee.growth import days_at_level
    from marneo.project.workspace import list_projects, load_project, get_employee_projects
    from marneo.gateway.config import load_channel_configs
    from marneo.cli.gateway_cmd import _read_pid

    console.print()

    # ── Provider ──────────────────────────────────────────────────────
    cfg = load_config()
    if cfg.provider and cfg.provider.api_key:
        p_status = f"[green]✓[/green] {cfg.provider.id} / {cfg.provider.model}"
    else:
        p_status = "[red]✗ 未配置[/red]"
    console.print(f"  Provider:  {p_status}")

    # ── Gateway ───────────────────────────────────────────────────────
    pid = _read_pid()
    gw_status = f"[green]🟢 运行中 (PID: {pid})[/green]" if pid else "[dim]⚪ 未启动[/dim]"
    console.print(f"  Gateway:   {gw_status}")

    channels = load_channel_configs()
    for platform, config in channels.items():
        enabled = "[green]✓[/green]" if config.get("enabled") else "[dim]○[/dim]"
        console.print(f"    {enabled} {platform}")

    # ── Employees ─────────────────────────────────────────────────────
    console.print()
    employees = list_employees()
    if employees:
        t = Table(box=rich_box.SIMPLE, show_header=True, header_style="bold dim")
        t.add_column("员工", style="cyan")
        t.add_column("等级")
        t.add_column("在职天数", justify="right", style="dim")
        t.add_column("对话总数", justify="right", style="dim")
        for name in employees:
            p = load_profile(name)
            if p:
                t.add_row(name, p.level, str(days_at_level(p)), str(p.total_conversations))
        console.print(t)
    else:
        console.print("  [dim]暂无员工。运行 marneo hire 招聘。[/dim]")

    # ── Projects ──────────────────────────────────────────────────────
    proj_names = list_projects()
    if proj_names:
        console.print(f"  项目：{', '.join(proj_names)}")
    else:
        console.print("  [dim]暂无项目。运行 marneo projects new 创建。[/dim]")

    console.print()
```

### Step 2: 注册到 app.py

在 `_register_subcommands()` 添加：
```python
from marneo.cli.status_cmd import cmd_status

@app.command("status")
def status() -> None:
    """显示全局状态。"""
    cmd_status()
```

### Step 3: 测试

```bash
marneo status
```

Expected: 显示 Provider、Gateway、员工表格、项目列表

### Step 4: Commit

```bash
git add marneo/cli/status_cmd.py marneo/cli/app.py
git commit -m "feat: add marneo status command (global system overview)"
```

---

## Task 3: 报告推送到 Gateway Channel

**Files:**
- Modify: `marneo/cli/report_cmd.py`
- Create: `marneo/employee/report_push.py`

### Step 1: 创建 `marneo/employee/report_push.py`

```python
# marneo/employee/report_push.py
"""Push reports to gateway channel."""
from __future__ import annotations

import asyncio
import logging

log = logging.getLogger(__name__)


async def push_to_channel(text: str, platform: str, chat_id: str) -> bool:
    """Send text to a specific channel/chat via gateway adapters."""
    from marneo.gateway.config import get_channel_config

    config = get_channel_config(platform)
    if not config or not config.get("enabled"):
        return False

    try:
        if platform == "feishu":
            from marneo.gateway.adapters.feishu import FeishuChannelAdapter
            from marneo.gateway.manager import GatewayManager
            adapter = FeishuChannelAdapter(GatewayManager())
            connected = await adapter.connect(config)
            if connected:
                result = await adapter.send_reply(chat_id, text)
                await adapter.disconnect()
                return result
        elif platform == "wechat":
            from marneo.gateway.adapters.wechat import WeChatChannelAdapter
            from marneo.gateway.manager import GatewayManager
            adapter = WeChatChannelAdapter(GatewayManager())
            connected = await adapter.connect(config)
            if connected:
                result = await adapter.send_reply(chat_id, text)
                await adapter.disconnect()
                return result
        elif platform == "telegram":
            from marneo.gateway.adapters.telegram import TelegramAdapter
            from marneo.gateway.manager import GatewayManager
            adapter = TelegramAdapter(GatewayManager())
            connected = await adapter.connect(config)
            if connected:
                result = await adapter.send_reply(chat_id, text)
                await adapter.disconnect()
                return result
    except Exception as e:
        log.error("push_to_channel error: %s", e)
    return False


def push_report(text: str, employee_name: str) -> bool:
    """Push report text to employee's configured push channel.

    Reads push target from employee config: push_platform + push_chat_id.
    Falls back gracefully if not configured.
    """
    from marneo.employee.profile import load_profile
    from marneo.core.paths import get_employees_dir
    import yaml

    # Read push config from employee dir
    config_path = get_employees_dir() / employee_name / "push.yaml"
    if not config_path.exists():
        return False

    try:
        cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        platform = cfg.get("platform", "")
        chat_id = cfg.get("chat_id", "")
        if not platform or not chat_id:
            return False
    except Exception:
        return False

    return asyncio.run(push_to_channel(text, platform, chat_id))


def configure_push(employee_name: str, platform: str, chat_id: str) -> None:
    """Save push configuration for employee."""
    import yaml
    from marneo.core.paths import get_employees_dir

    config_path = get_employees_dir() / employee_name / "push.yaml"
    config_path.write_text(
        yaml.dump({"platform": platform, "chat_id": chat_id}, allow_unicode=True),
        encoding="utf-8",
    )
```

### Step 2: 更新 `report_cmd.py` 的 `cmd_daily` — 实现 `--push`

找到 `cmd_daily` 中的 `if push:` 行，替换为：

```python
    if push:
        from marneo.employee.report_push import push_report
        ok = push_report(report, name)
        if ok:
            console.print("[green]✓ 报告已推送[/green]")
        else:
            console.print("[yellow]⚠ 推送失败（未配置推送目标）[/yellow]")
        console.print("[dim]运行 marneo report push-config 配置推送目标[/dim]")
```

### Step 3: 添加 `marneo report push-config` 命令

在 `report_cmd.py` 添加：

```python
@report_app.command("push-config")
def cmd_push_config(
    employee: str | None = typer.Option(None, "--employee", "-e"),
) -> None:
    """配置报告推送目标（平台 + chat_id）。"""
    from prompt_toolkit import prompt as pt_prompt
    from marneo.employee.report_push import configure_push
    from marneo.tui.select_ui import radiolist

    name = employee or _active_employee()
    if not name:
        console.print("[dim]尚无员工。[/dim]")
        return

    platforms = ["feishu", "wechat", "telegram", "discord"]
    idx = radiolist("推送平台：", platforms, default=0)
    platform = platforms[idx]

    try:
        chat_id = pt_prompt(f"  Chat ID（{platform} 的群/用户 ID）: ").strip()
        if not chat_id:
            return
    except KeyboardInterrupt:
        return

    configure_push(name, platform, chat_id)
    console.print(f"[green]✓ 推送配置已保存：{platform} → {chat_id}[/green]")
    console.print("[dim]运行 marneo report daily --push 测试推送[/dim]")
```

### Step 4: 测试

```bash
python3 -c "
from marneo.employee.report_push import push_report, configure_push
print('report_push imports OK')
"
marneo report --help
```

### Step 5: Commit

```bash
git add marneo/employee/report_push.py marneo/cli/report_cmd.py
git commit -m "feat: implement report push to gateway channel + marneo report push-config"
```

---

## Task 4: Skill 自动学习

**Files:**
- Create: `marneo/employee/skill_learner.py`
- Modify: `marneo/cli/work.py`

### Step 1: 创建 `marneo/employee/skill_learner.py`

```python
# marneo/employee/skill_learner.py
"""Auto-extract learnable skills from conversations."""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

MIN_TEXT_LEN = 200  # Skip short replies
LEARNING_LEVELS = {"实习生", "初级员工"}  # Only junior employees auto-learn


def should_learn(level: str, reply_text: str) -> bool:
    return level in LEARNING_LEVELS and len(reply_text) >= MIN_TEXT_LEN


def extract_skill_insight(user_msg: str, assistant_reply: str) -> str | None:
    """Use LLM to extract a learnable skill insight from a conversation turn.

    Returns a brief skill description or None if nothing worth learning.
    """
    from marneo.employee.interview import _call_llm

    prompt = f"""\
分析以下对话，判断其中是否有值得提炼为可复用技能的知识点。

用户：{user_msg[:300]}
助手：{assistant_reply[:800]}

如果有，用一句话（20-60字）概括这个技能点，直接输出内容。
如果没有值得提炼的技能（闲聊、简单问答等），只输出：SKIP
"""
    try:
        result = _call_llm(
            [{"role": "user", "content": prompt}],
            system="你是一个技能提炼助手，简洁输出。",
            max_tokens=100,
        )
        return None if result.upper().startswith("SKIP") else result.strip() or None
    except Exception as e:
        log.debug("skill extraction error: %s", e)
        return None


def maybe_save_skill(employee_name: str, user_msg: str, reply: str) -> str | None:
    """If reply is substantial and employee is junior, try to extract and save a skill.

    Returns the insight string if saved, None otherwise.
    """
    from marneo.employee.profile import load_profile

    profile = load_profile(employee_name)
    if not profile or not should_learn(profile.level, reply):
        return None

    insight = extract_skill_insight(user_msg, reply)
    if not insight:
        return None

    # Save as auto-learned global skill
    from marneo.project.skills import Skill, save_skill, list_skills
    import hashlib, time

    # Avoid duplicate skills
    existing = [s.description for s in list_skills()]
    if any(insight[:20] in desc for desc in existing):
        return None

    skill_id = f"auto-{int(time.time())}"
    skill = Skill(
        id=skill_id,
        name=insight[:30],
        description=insight,
        scope="global",
        content=f"从对话中提炼：\n{insight}",
    )
    save_skill(skill)
    return insight
```

### Step 2: 在 `marneo/cli/work.py` 的 `on_input` 后半段添加自动学习

找到 post-turn tracking 的 `try:` 块，在 `append_daily_entry(...)` 之后加：

```python
                # Auto-learn skill (junior/intern only)
                if reply.strip():
                    try:
                        from marneo.employee.skill_learner import maybe_save_skill  # type: ignore[import]
                        insight = maybe_save_skill(employee_name, text, reply)
                        if insight:
                            tui.print(f"\n{_DIM}💡 已提炼新技能：{insight[:40]}{_RST}")
                    except Exception:
                        pass
```

### Step 3: 测试

```bash
python3 -c "
from marneo.employee.skill_learner import should_learn, maybe_save_skill
assert should_learn('实习生', 'x' * 250)
assert not should_learn('高级员工', 'x' * 250)
assert not should_learn('实习生', 'short')
print('skill_learner OK')
"
```

### Step 4: Commit

```bash
git add marneo/employee/skill_learner.py marneo/cli/work.py
git commit -m "feat: add skill auto-learning for junior/intern employees"
```

---

## Task 5: README + 最终集成验证

### Step 1: 更新 README.md

```bash
cat > /Users/chamber/code/marneo-agent/README.md << 'MARKDOWN'
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
# 员工
marneo hire                    招聘员工（LLM 面试）
marneo work [--employee]       与员工对话
marneo employees list/show     查看员工
marneo status                  全局状态仪表板

# 项目
marneo projects new <name>     创建项目（LLM 面试）
marneo projects list/show      查看项目
marneo assign <project>        将员工分配到项目

# 技能
marneo skills list/add/show    管理技能

# 报告
marneo report daily [--push]   日报
marneo report weekly           周报
marneo report push-config      配置推送

# Gateway
marneo gateway start/stop      网关守护进程
marneo gateway status/logs     状态与日志
marneo gateway channels add    配置 IM 渠道

# 配置
marneo setup                   配置 Provider
marneo --version               版本
```

## 路线图

- ✅ Phase 1 — CLI + Provider + TUI
- ✅ Phase 2 — 员工系统（hire/work/employees/report）
- ✅ Phase 3 — 项目系统（projects/assign/skills）
- ✅ Phase 4 — Gateway（飞书/微信/Telegram/Discord）
- ✅ Phase 5 — 打磨（dashboard/status/push/auto-learn）
MARKDOWN
```

### Step 2: 全量集成验证

```bash
cd /Users/chamber/code/marneo-agent && python3 -c "
print('=== Marneo Phase 5 Integration Checks ===')

from marneo.cli.app import app
from marneo.cli.status_cmd import cmd_status
from marneo.employee.report_push import push_report, configure_push
from marneo.employee.skill_learner import should_learn, maybe_save_skill
print('✓ All imports OK')

assert should_learn('实习生', 'x' * 250)
assert not should_learn('高级员工', 'x' * 300)
print('✓ skill_learner OK')

import subprocess
for cmd in [
    ['marneo', '--version'],
    ['marneo', 'status'],
    ['marneo', 'report', '--help'],
]:
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == 0, f'{cmd}: {r.stderr[:60]}'
print('✓ CLI commands OK')

print()
print('ALL CHECKS PASSED')
"
```

### Step 3: 最终提交

```bash
git add README.md
git commit -m "docs: update README with complete command reference"
git log --oneline -8
```
