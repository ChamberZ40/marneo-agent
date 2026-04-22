# Marneo Agent Phase 3 — Projects System Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 实现项目系统：`marneo projects new`（LLM 面试创建项目）、`marneo assign`（员工分配到项目）、员工工作时携带所有项目上下文、`marneo skills` 技能管理。

**Architecture:** 项目数据存 `~/.marneo/projects/<name>/`（YAML），一个员工可以被分配到多个项目。`marneo work` 时员工知道自己的所有项目（project.yaml + AGENT.md 注入 system prompt）。Skill 系统按 global/project 两级作用域管理。

**Tech Stack:** Python 3.11+, pyyaml, typer, rich, prompt-toolkit（已有）

**Reference:**
- `/Users/chamber/code/marneo-agent/marneo/employee/` — 迁移参考
- `/Users/chamber/code/marneo-agent/marneo/` — 当前结构

---

## Task 1: Project 数据模型

**Files:**
- Create: `marneo/project/__init__.py`
- Create: `marneo/project/workspace.py`

### Step 1: 创建 `marneo/project/__init__.py`（空文件）

### Step 2: 创建 `marneo/project/workspace.py`

```python
# marneo/project/workspace.py
"""Project workspace — YAML-based, stored under ~/.marneo/projects/<name>/

Layout:
  ~/.marneo/projects/
  └── affiliate-ops/
      ├── project.yaml      # 项目配置（描述、KPI、成员）
      ├── AGENT.md          # 项目工作档案（LLM 面试生成）
      ├── memory/           # 项目记忆（预留）
      └── skills/           # 项目专属 skill
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from marneo.core.paths import get_projects_dir


@dataclass
class KPI:
    name: str
    target: str = ""
    unit: str = ""


@dataclass
class ProjectWorkspace:
    name: str
    description: str = ""
    goals: list[str] = field(default_factory=list)
    kpis: list[KPI] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    created_at: str = ""
    assigned_employees: list[str] = field(default_factory=list)

    @property
    def directory(self) -> Path:
        d = get_projects_dir() / self.name
        d.mkdir(exist_ok=True)
        return d

    @property
    def agent_path(self) -> Path:
        return self.directory / "AGENT.md"

    @property
    def skills_dir(self) -> Path:
        d = self.directory / "skills"
        d.mkdir(exist_ok=True)
        return d


def list_projects() -> list[str]:
    """Return names of all configured projects."""
    d = get_projects_dir()
    return sorted(
        p.name for p in d.iterdir()
        if p.is_dir() and (p / "project.yaml").exists()
    )


def load_project(name: str) -> ProjectWorkspace | None:
    """Load project from YAML. Returns None if not found."""
    path = get_projects_dir() / name / "project.yaml"
    if not path.exists():
        return None
    try:
        data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        kpis = [
            KPI(name=k.get("name", ""), target=str(k.get("target", "")), unit=k.get("unit", ""))
            for k in data.get("kpis", [])
            if isinstance(k, dict)
        ]
        return ProjectWorkspace(
            name=name,
            description=data.get("description", ""),
            goals=data.get("goals", []),
            kpis=kpis,
            tools=data.get("tools", []),
            created_at=data.get("created_at", ""),
            assigned_employees=data.get("assigned_employees", []),
        )
    except Exception:
        return None


def save_project(project: ProjectWorkspace) -> Path:
    """Save project to YAML. Returns the project.yaml path."""
    project.directory.mkdir(parents=True, exist_ok=True)
    path = project.directory / "project.yaml"
    data: dict[str, Any] = {
        "name": project.name,
        "description": project.description,
        "goals": project.goals,
        "kpis": [{"name": k.name, "target": k.target, "unit": k.unit} for k in project.kpis],
        "tools": project.tools,
        "created_at": project.created_at,
        "assigned_employees": project.assigned_employees,
    }
    path.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
    return path


def create_project(
    name: str,
    description: str = "",
    goals: list[str] | None = None,
) -> ProjectWorkspace:
    """Create and save a new project workspace."""
    project = ProjectWorkspace(
        name=name,
        description=description,
        goals=goals or [],
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    save_project(project)
    return project


def assign_employee(project_name: str, employee_name: str) -> bool:
    """Add employee to project's assigned list. Returns True if changed."""
    project = load_project(project_name)
    if not project:
        return False
    if employee_name not in project.assigned_employees:
        project.assigned_employees.append(employee_name)
        save_project(project)
    return True


def get_employee_projects(employee_name: str) -> list[ProjectWorkspace]:
    """Return all projects assigned to this employee."""
    result: list[ProjectWorkspace] = []
    for name in list_projects():
        p = load_project(name)
        if p and employee_name in p.assigned_employees:
            result.append(p)
    return result
```

### Step 3: 冒烟测试

```bash
cd /Users/chamber/code/marneo-agent && python3 -c "
from marneo.project.workspace import (
    create_project, load_project, save_project, list_projects,
    assign_employee, get_employee_projects
)
import shutil

p = create_project('test-proj', description='测试项目', goals=['目标1'])
assert p.name == 'test-proj'
loaded = load_project('test-proj')
assert loaded.description == '测试项目'
assert 'test-proj' in list_projects()

assign_employee('test-proj', 'GAI')
loaded2 = load_project('test-proj')
assert 'GAI' in loaded2.assigned_employees

projects = get_employee_projects('GAI')
assert any(p.name == 'test-proj' for p in projects)

shutil.rmtree(p.directory)
print('ALL OK')
"
```

### Step 4: Commit

```bash
cd /Users/chamber/code/marneo-agent
git add marneo/project/
git commit -m "feat: add project workspace data model (YAML-based)"
```

---

## Task 2: 项目 LLM 面试引擎

**Files:**
- Create: `marneo/project/interview.py`

### Step 1: 创建 `marneo/project/interview.py`

```python
# marneo/project/interview.py
"""LLM-driven project interview — generates project.yaml + AGENT.md."""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

MAX_ROUNDS = 8
MIN_ROUNDS = 5

_INTERVIEWER_SYSTEM = """\
你是一位项目管理顾问，正在帮助一个团队梳理一个新项目的背景信息。
你的目标是通过对话收集足够的信息，最终生成：
1. 项目配置（project.yaml）
2. 数字员工的项目工作档案（AGENT.md）

访谈规则：
- 每次只问一个问题，简短有力
- 根据前面的回答动态调整下一个问题
- 前 {min_rounds} 轮必须继续；之后如果信息足够，输出 ##DONE##
- 问题要覆盖：项目目标/KPI/团队/工具/挑战/工作方式
- 每个问题附带 3-4 个选项（字母编号），允许追加自由回答

格式（严格遵守）：
问题文本

A. 选项一
B. 选项二
C. 选项三
D. 其他（请自行描述）

只输出问题+选项（或 ##DONE##），不要任何前缀。
"""

_AGENT_SYSTEM = """\
你是一位 HR 专家，请根据以下项目访谈记录，为数字员工生成项目工作档案（AGENT.md）。

项目名称：{project_name}
访谈记录：
{qa_content}

要求：
1. 第一行：# {project_name} — 工作档案
2. 包含 ## 核心职责 / ## 工作目标 / ## 工作规范 / ## 协作方式 四节
3. 每节 3-5 条精炼要点，总字数 300-500 字
4. 基于访谈内容，专业具体

直接输出内容，不要解释。
"""

_YAML_SYSTEM = """\
根据以下项目访谈记录，提取结构化信息。

访谈记录：
{qa_content}

请用 JSON 格式输出以下字段（如无明确信息则用空字符串或空列表）：
{{
  "description": "一句话描述项目",
  "goals": ["目标1", "目标2"],
  "kpis": [{{"name": "KPI名称", "target": "目标值", "unit": "单位"}}],
  "tools": ["工具1", "工具2"]
}}

只输出 JSON，不要任何其他内容。
"""


def _call_llm(messages: list[dict], *, system: str, max_tokens: int = 800) -> str:
    """Synchronous LLM call — reuse interview engine."""
    from marneo.employee.interview import _call_llm as _base
    return _base(messages, system=system, max_tokens=max_tokens)


def next_question(history: list[dict], round_number: int) -> str | None:
    """Ask LLM for next project interview question."""
    system = _INTERVIEWER_SYSTEM.format(min_rounds=MIN_ROUNDS)
    msgs = history if history else [{"role": "user", "content": "请开始项目访谈，提出第一个问题。"}]
    try:
        response = _call_llm(msgs, system=system, max_tokens=300)
    except Exception as e:
        log.error("Project interview LLM error: %s", e)
        return None
    if "##DONE##" in response or round_number >= MAX_ROUNDS:
        return None
    return response.replace("##DONE##", "").strip() or None


def synthesize_agent_md(history: list[dict], project_name: str) -> str:
    """Generate AGENT.md from project interview history."""
    qa_content = "\n\n".join(
        f"{'问' if m['role'] == 'assistant' else '答'}：{m['content']}"
        for m in history
    )
    system = _AGENT_SYSTEM.format(project_name=project_name, qa_content=qa_content)
    try:
        return _call_llm(
            [{"role": "user", "content": f"请为 {project_name} 项目生成工作档案。"}],
            system=system, max_tokens=800,
        )
    except Exception as e:
        log.error("AGENT.md synthesis error: %s", e)
        return f"# {project_name} — 工作档案\n\n## 核心职责\n- 推进项目目标\n\n## 工作目标\n- 达成既定 KPI\n"


def extract_project_yaml_data(history: list[dict]) -> dict:
    """Extract structured project data from interview."""
    import json
    qa_content = "\n\n".join(
        f"{'问' if m['role'] == 'assistant' else '答'}：{m['content']}"
        for m in history
    )
    system = _YAML_SYSTEM.format(qa_content=qa_content)
    try:
        raw = _call_llm(
            [{"role": "user", "content": "请提取项目信息。"}],
            system=system, max_tokens=400,
        )
        # Strip markdown code fences if present
        raw = raw.strip()
        if raw.startswith("```"):
            raw = "\n".join(raw.splitlines()[1:])
        if raw.endswith("```"):
            raw = "\n".join(raw.splitlines()[:-1])
        return json.loads(raw.strip())
    except Exception as e:
        log.error("YAML extraction error: %s", e)
        return {"description": "", "goals": [], "kpis": [], "tools": []}
```

### Step 2: 冒烟测试

```bash
cd /Users/chamber/code/marneo-agent && python3 -c "
from marneo.project.interview import MAX_ROUNDS, MIN_ROUNDS, _call_llm
assert MAX_ROUNDS == 8 and MIN_ROUNDS == 5
print('imports OK, MAX_ROUNDS:', MAX_ROUNDS)
print('ALL OK')
"
```

### Step 3: Commit

```bash
cd /Users/chamber/code/marneo-agent
git add marneo/project/interview.py
git commit -m "feat: add project LLM interview engine (generates project.yaml + AGENT.md)"
```

---

## Task 3: `marneo projects` + `marneo assign` 命令

**Files:**
- Create: `marneo/cli/projects_cmd.py`
- Modify: `marneo/cli/app.py`

### Step 1: 创建 `marneo/cli/projects_cmd.py`

```python
# marneo/cli/projects_cmd.py
"""marneo projects — manage project workspaces."""
from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()
projects_app = typer.Typer(help="项目管理。", invoke_without_command=True)
assign_app = typer.Typer(help="将员工分配到项目。")

_DIM = "\033[38;2;85;85;85m"
_RST = "\033[0m"
_PRI = "\033[1;38;2;255;102;17m"


@projects_app.callback(invoke_without_command=True)
def projects_default(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        cmd_list()


@projects_app.command("list")
def cmd_list() -> None:
    """列出所有项目。"""
    from marneo.project.workspace import list_projects, load_project

    names = list_projects()
    if not names:
        console.print("[dim]尚无项目。运行 marneo projects new <name> 创建。[/dim]")
        return

    t = Table(title="项目列表", show_header=True, header_style="bold #FFD700")
    t.add_column("名称", style="bold cyan")
    t.add_column("描述")
    t.add_column("员工", style="dim")
    t.add_column("目标数", justify="right")

    for name in names:
        p = load_project(name)
        if p:
            t.add_row(
                name,
                p.description[:40] or "—",
                ", ".join(p.assigned_employees) or "—",
                str(len(p.goals)),
            )
    console.print()
    console.print(t)


@projects_app.command("new")
def cmd_new(name: str = typer.Argument(..., help="项目名称（英文，如 affiliate-ops）")) -> None:
    """通过 LLM 面试创建新项目。"""
    from prompt_toolkit import prompt as pt_prompt
    from marneo.project.workspace import load_project, create_project, save_project
    from marneo.project.interview import (
        next_question, synthesize_agent_md, extract_project_yaml_data, MAX_ROUNDS
    )
    from marneo.employee.interview import parse_question

    if load_project(name):
        console.print(f"[yellow]项目 '{name}' 已存在。[/yellow]")
        try:
            if pt_prompt("  重新创建？(y/N) ").strip().lower() not in ("y", "yes"):
                raise typer.Exit()
        except KeyboardInterrupt:
            raise typer.Exit()

    console.print()
    console.print(Panel(
        f"[bold #FF6611]新建项目：{name}[/bold #FF6611]\n\n"
        "通过 AI 面试梳理项目背景，生成项目配置和工作档案。\n"
        "[dim]Ctrl+C 可随时取消。[/dim]",
        border_style="#FF6611", padding=(1, 2),
    ))

    # Interview loop
    history: list[dict] = []
    round_num = 0

    while round_num < MAX_ROUNDS:
        console.print(f"\n[dim]生成第 {round_num + 1} 个问题...[/dim]")
        question = next_question(history, round_num)
        if question is None:
            break

        round_num += 1
        q_text, options = parse_question(question)

        console.print(f"\n[bold #FFD700]Q{round_num}[/bold #FFD700]  {q_text}")
        for letter, opt_text in options:
            console.print(f"  [dim]{letter}.[/dim] {opt_text}")
        if options:
            console.print(f"  [dim]输入字母选择，可追加说明[/dim]")

        try:
            raw = pt_prompt("  → ").strip()
        except KeyboardInterrupt:
            console.print("\n[dim]已取消。[/dim]")
            raise typer.Exit()

        if not raw:
            raw = "（跳过）"

        # Expand letter selection
        ans = raw
        if options and raw:
            first = raw[0].upper()
            matched = next((t for l, t in options if l == first), None)
            if matched:
                sup = raw[1:].strip().lstrip("，, ")
                ans = f"{matched}。{sup}" if sup else matched

        history.append({"role": "assistant", "content": question})
        history.append({"role": "user", "content": ans})

    # Generate outputs
    console.print(f"\n[dim]面试完成（{round_num} 轮），生成项目档案...[/dim]")

    agent_md = synthesize_agent_md(history, name)
    yaml_data = extract_project_yaml_data(history)

    # Show AGENT.md preview
    console.print()
    console.print(Panel(
        agent_md,
        title=f"[bold #00FFCC]✦ {name} 工作档案[/bold #00FFCC]",
        border_style="#00FFCC", padding=(1, 2),
    ))

    try:
        confirm = pt_prompt("  回车保存，输入意见修改，q 取消: ").strip()
    except KeyboardInterrupt:
        raise typer.Exit()

    if confirm.lower() in ("q", "quit"):
        console.print("[dim]已取消。[/dim]")
        raise typer.Exit()

    if confirm:
        console.print("[dim]修改中...[/dim]")
        try:
            from marneo.employee.interview import _call_llm
            agent_md = _call_llm(
                [{"role": "user", "content": f"当前文档：\n{agent_md}\n\n修改意见：{confirm}\n\n直接输出修改后完整文档。"}],
                system="你是专业文字编辑，直接输出修改后内容。",
                max_tokens=800,
            )
        except Exception:
            pass

    # Save
    project = create_project(
        name=name,
        description=yaml_data.get("description", ""),
        goals=yaml_data.get("goals", []),
    )
    project.agent_path.write_text(agent_md, encoding="utf-8")

    console.print()
    console.print(Panel(
        f"[bold #FF6611]项目 {name} 已创建！[/bold #FF6611]\n\n"
        f"  描述：{project.description or '—'}\n"
        f"  目标：{len(project.goals)} 个\n"
        f"  AGENT.md → [dim]{project.agent_path}[/dim]\n\n"
        f"运行 [bold]marneo assign {name}[/bold] 将员工派到此项目。",
        border_style="#FFD700", padding=(1, 2),
    ))


@projects_app.command("show")
def cmd_show(name: str = typer.Argument(..., help="项目名称")) -> None:
    """查看项目详情。"""
    from marneo.project.workspace import load_project

    p = load_project(name)
    if not p:
        console.print(f"[red]项目 '{name}' 不存在。[/red]")
        raise typer.Exit(1)

    console.print()
    goals_str = "\n".join(f"  • {g}" for g in p.goals) or "  （暂无）"
    console.print(Panel(
        f"[bold #FF6611]{p.name}[/bold #FF6611]\n\n"
        f"  描述：{p.description or '—'}\n"
        f"  员工：{', '.join(p.assigned_employees) or '—'}\n\n"
        f"  目标：\n{goals_str}",
        title="[bold #FFD700]✦ 项目档案[/bold #FFD700]",
        border_style="#FF6611", padding=(1, 2),
    ))

    if p.agent_path.exists():
        agent = p.agent_path.read_text(encoding="utf-8").strip()
        console.print(Panel(agent, title="[dim]AGENT.md[/dim]",
                            border_style="#555555", padding=(1, 2)))
    console.print()


# marneo assign <project> [--employee <name>]
@assign_app.callback(invoke_without_command=True)
def cmd_assign(
    project: str = typer.Argument(..., help="项目名称"),
    employee: str | None = typer.Option(None, "--employee", "-e", help="员工名称"),
) -> None:
    """将员工分配到项目。"""
    from marneo.project.workspace import assign_employee, load_project
    from marneo.employee.profile import list_employees

    p = load_project(project)
    if not p:
        console.print(f"[red]项目 '{project}' 不存在。运行 marneo projects new {project} 创建。[/red]")
        raise typer.Exit(1)

    if not employee:
        names = list_employees()
        if not names:
            console.print("[dim]尚无员工。运行 marneo hire 招聘。[/dim]")
            raise typer.Exit(1)
        if len(names) == 1:
            employee = names[0]
        else:
            from marneo.tui.select_ui import radiolist
            idx = radiolist("选择员工：", names, default=0)
            employee = names[idx]

    assign_employee(project, employee)
    console.print(f"[green]✓ {employee} 已分配到项目 {project}[/green]")
    console.print(f"[dim]运行 marneo work 开始工作。[/dim]")
```

### Step 2: 注册到 app.py

```python
from marneo.cli.projects_cmd import projects_app, assign_app
app.add_typer(projects_app, name="projects")
app.add_typer(assign_app, name="assign")
```

### Step 3: 冒烟测试

```bash
cd /Users/chamber/code/marneo-agent
python3 -c "from marneo.cli.projects_cmd import projects_app, assign_app; print('OK')"
marneo projects --help
marneo assign --help
```

### Step 4: Commit

```bash
git add marneo/cli/projects_cmd.py marneo/cli/app.py
git commit -m "feat: add marneo projects new/list/show + marneo assign commands"
```

---

## Task 4: Skills 系统

**Files:**
- Create: `marneo/project/skills.py`
- Create: `marneo/cli/skills_cmd.py`
- Modify: `marneo/cli/app.py`

### Step 1: 创建 `marneo/project/skills.py`

```python
# marneo/project/skills.py
"""Skill management — global and project-scoped skills.

Skill format (Markdown with YAML frontmatter):
  ---
  name: skill-name
  description: One-line description
  scope: global | project:<name>
  enabled: true
  ---

  Skill content here...
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from marneo.core.paths import get_marneo_dir, get_projects_dir


@dataclass
class Skill:
    id: str           # filename without .md
    name: str
    description: str = ""
    scope: str = "global"   # "global" or "project:<name>"
    enabled: bool = True
    content: str = ""
    source_path: Path | None = None


def _global_skills_dir() -> Path:
    d = get_marneo_dir() / "skills"
    d.mkdir(exist_ok=True)
    return d


def _parse_skill_file(path: Path) -> Skill | None:
    text = path.read_text(encoding="utf-8")
    meta: dict[str, Any] = {}
    body = text

    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            try:
                meta = yaml.safe_load(text[3:end]) or {}
            except Exception:
                pass
            body = text[end + 3:].strip()

    skill_id = path.stem
    return Skill(
        id=skill_id,
        name=meta.get("name", skill_id),
        description=meta.get("description", ""),
        scope=meta.get("scope", "global"),
        enabled=bool(meta.get("enabled", True)),
        content=body,
        source_path=path,
    )


def list_skills(include_project: str | None = None) -> list[Skill]:
    """List all enabled skills (global + optionally project-specific)."""
    skills: list[Skill] = []

    # Global skills
    for path in sorted(_global_skills_dir().glob("*.md")):
        skill = _parse_skill_file(path)
        if skill and skill.enabled:
            skills.append(skill)

    # Project skills
    if include_project:
        proj_skills_dir = get_projects_dir() / include_project / "skills"
        if proj_skills_dir.exists():
            for path in sorted(proj_skills_dir.glob("*.md")):
                skill = _parse_skill_file(path)
                if skill and skill.enabled:
                    skills.append(skill)

    return skills


def save_skill(skill: Skill) -> Path:
    """Save skill to file. Returns the file path."""
    if skill.scope.startswith("project:"):
        proj_name = skill.scope[len("project:"):]
        skills_dir = get_projects_dir() / proj_name / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
    else:
        skills_dir = _global_skills_dir()

    path = skills_dir / f"{skill.id}.md"
    meta = {
        "name": skill.name,
        "description": skill.description,
        "scope": skill.scope,
        "enabled": skill.enabled,
    }
    content = f"---\n{yaml.dump(meta, allow_unicode=True)}---\n\n{skill.content}"
    path.write_text(content, encoding="utf-8")
    return path


def get_skills_context(employee_name: str) -> str:
    """Build skill context string for system prompt injection."""
    # Get employee's projects
    from marneo.project.workspace import get_employee_projects
    projects = get_employee_projects(employee_name)

    all_skills: list[Skill] = list_skills()  # global
    for proj in projects:
        all_skills.extend(list_skills(include_project=proj.name))

    if not all_skills:
        return ""

    lines = ["# 可用技能\n"]
    for skill in all_skills:
        lines.append(f"## {skill.name}\n{skill.description}\n\n{skill.content}\n")

    return "\n".join(lines)
```

### Step 2: 创建 `marneo/cli/skills_cmd.py`

```python
# marneo/cli/skills_cmd.py
"""marneo skills — manage skills."""
from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()
skills_app = typer.Typer(help="技能管理。", invoke_without_command=True)


@skills_app.callback(invoke_without_command=True)
def skills_default(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        cmd_list()


@skills_app.command("list")
def cmd_list(
    project: str | None = typer.Option(None, "--project", "-p", help="包含指定项目的技能"),
) -> None:
    """列出所有技能。"""
    from marneo.project.skills import list_skills

    skills = list_skills(include_project=project)
    if not skills:
        console.print("[dim]尚无技能。运行 marneo skills add 创建。[/dim]")
        return

    t = Table(title="技能列表", show_header=True, header_style="bold #FFD700")
    t.add_column("ID", style="cyan")
    t.add_column("名称")
    t.add_column("描述")
    t.add_column("作用域", style="dim")

    for s in skills:
        t.add_row(s.id, s.name, s.description[:40], s.scope)

    console.print()
    console.print(t)


@skills_app.command("add")
def cmd_add(
    skill_id: str = typer.Argument(..., help="技能 ID（英文，如 daily-report）"),
    project: str | None = typer.Option(None, "--project", "-p", help="项目作用域"),
) -> None:
    """创建新技能。"""
    from prompt_toolkit import prompt as pt_prompt
    from marneo.project.skills import Skill, save_skill

    try:
        name = pt_prompt(f"  技能名称 [{skill_id}]: ").strip() or skill_id
        description = pt_prompt("  一句话描述: ").strip()
        console.print("  技能内容（输入后按 Ctrl+D 完成）:")
        lines: list[str] = []
        try:
            while True:
                line = pt_prompt("  ").strip()
                lines.append(line)
        except (KeyboardInterrupt, EOFError):
            pass
        content = "\n".join(lines)
    except KeyboardInterrupt:
        console.print("\n[dim]已取消。[/dim]")
        raise typer.Exit()

    scope = f"project:{project}" if project else "global"
    skill = Skill(id=skill_id, name=name, description=description,
                  scope=scope, content=content)
    path = save_skill(skill)
    console.print(f"[green]✓ 技能已保存 → {path}[/green]")


@skills_app.command("show")
def cmd_show(skill_id: str = typer.Argument(..., help="技能 ID")) -> None:
    """查看技能详情。"""
    from marneo.project.skills import list_skills

    all_skills = list_skills()
    skill = next((s for s in all_skills if s.id == skill_id), None)
    if not skill:
        console.print(f"[red]技能 '{skill_id}' 不存在。[/red]")
        raise typer.Exit(1)

    console.print()
    console.print(Panel(
        f"[bold]{skill.name}[/bold]\n\n"
        f"  作用域：{skill.scope}\n"
        f"  描述：{skill.description}\n\n"
        f"{skill.content}",
        title=f"[bold #FFD700]{skill.id}[/bold #FFD700]",
        border_style="#FFD700", padding=(1, 2),
    ))


@skills_app.command("disable")
def cmd_disable(skill_id: str = typer.Argument(..., help="技能 ID")) -> None:
    """禁用技能。"""
    from marneo.project.skills import list_skills, save_skill
    from dataclasses import replace

    all_skills = list_skills()
    skill = next((s for s in all_skills if s.id == skill_id), None)
    if not skill:
        console.print(f"[red]技能 '{skill_id}' 不存在。[/red]")
        raise typer.Exit(1)

    updated = replace(skill, enabled=False)
    save_skill(updated)
    console.print(f"[dim]{skill_id} 已禁用。[/dim]")


@skills_app.command("enable")
def cmd_enable(skill_id: str = typer.Argument(..., help="技能 ID")) -> None:
    """启用技能。"""
    from marneo.project.skills import list_skills, save_skill
    from dataclasses import replace

    # Check disabled skills too
    from marneo.core.paths import get_marneo_dir
    from marneo.project.skills import _parse_skill_file
    skills_dir = get_marneo_dir() / "skills"
    path = skills_dir / f"{skill_id}.md"
    if not path.exists():
        console.print(f"[red]技能 '{skill_id}' 不存在。[/red]")
        raise typer.Exit(1)

    skill = _parse_skill_file(path)
    if skill:
        from dataclasses import replace
        updated = replace(skill, enabled=True)
        save_skill(updated)
        console.print(f"[green]✓ {skill_id} 已启用。[/green]")
```

### Step 3: 注册到 app.py

```python
from marneo.cli.skills_cmd import skills_app
app.add_typer(skills_app, name="skills")
```

### Step 4: 冒烟测试

```bash
cd /Users/chamber/code/marneo-agent
python3 -c "
from marneo.project.skills import list_skills, save_skill, Skill
from marneo.cli.skills_cmd import skills_app

# Test save/load
s = Skill(id='test-skill', name='测试技能', description='测试', content='内容')
path = save_skill(s)
skills = list_skills()
assert any(sk.id == 'test-skill' for sk in skills)
import os; os.unlink(path)
print('ALL OK')
"
marneo skills --help
```

### Step 5: Commit

```bash
git add marneo/project/skills.py marneo/cli/skills_cmd.py marneo/cli/app.py
git commit -m "feat: add skill system (global/project scope) + marneo skills command"
```

---

## Task 5: 更新 `marneo work` — 项目上下文注入

**Files:**
- Modify: `marneo/cli/work.py`

### Step 1: 在 `_work_loop` 的 system prompt 构建部分注入项目上下文

找到 `_work_loop` 里的 `base_system` 构建区域，在最后加：

```python
    # Inject project context for all assigned projects
    try:
        from marneo.project.workspace import get_employee_projects
        projects = get_employee_projects(employee_name)
        if projects:
            proj_ctx_parts: list[str] = []
            for proj in projects:
                proj_ctx_parts.append(f"## 项目：{proj.name}")
                if proj.description:
                    proj_ctx_parts.append(f"描述：{proj.description}")
                if proj.goals:
                    proj_ctx_parts.append("目标：" + "、".join(proj.goals[:3]))
                if proj.agent_path.exists():
                    agent_md = proj.agent_path.read_text(encoding="utf-8").strip()
                    proj_ctx_parts.append(agent_md)
            if proj_ctx_parts:
                base_system = base_system + "\n\n# 当前项目\n\n" + "\n\n".join(proj_ctx_parts)
    except Exception:
        pass

    # Inject skills
    try:
        from marneo.project.skills import get_skills_context
        skills_ctx = get_skills_context(employee_name)
        if skills_ctx:
            base_system = base_system + "\n\n" + skills_ctx
    except Exception:
        pass
```

Also update the welcome banner to show project count:

```python
    proj_count = len(get_employee_projects(employee_name)) if profile else 0
    proj_info = f"  {_DIM}{proj_count} 个项目{_RST}" if proj_count else ""
    welcome = (
        f"\n  {_PRI}◆ {employee_name}{level_str}{_RST}"
        f"{proj_info}"
        f"  {_DIM}/help · Ctrl+C 退出{_RST}\n"
    )
```

### Step 2: 测试

```bash
cd /Users/chamber/code/marneo-agent
python3 -c "from marneo.cli.work import cmd_work, work_app; print('OK')"
```

### Step 3: Commit

```bash
git add marneo/cli/work.py
git commit -m "feat: inject project context + skills into marneo work system prompt"
```

---

## Task 6: 最终集成验证

### Step 1: 全量测试

```bash
cd /Users/chamber/code/marneo-agent && python3 -c "
print('=== Marneo Phase 3 Integration Checks ===')

from marneo.project.workspace import (
    create_project, load_project, list_projects, assign_employee,
    get_employee_projects, save_project
)
from marneo.project.interview import MAX_ROUNDS, MIN_ROUNDS
from marneo.project.skills import list_skills, save_skill, Skill, get_skills_context
from marneo.cli.projects_cmd import projects_app, assign_app
from marneo.cli.skills_cmd import skills_app
from marneo.cli.work import work_app
print('✓ All imports OK')

import shutil, os

# Project model
p = create_project('test-p3', description='Phase 3 test', goals=['目标A'])
assert load_project('test-p3').description == 'Phase 3 test'
assert 'test-p3' in list_projects()
print('✓ Project model OK')

# Assign
assign_employee('test-p3', 'GAI')
loaded = load_project('test-p3')
assert 'GAI' in loaded.assigned_employees
projs = get_employee_projects('GAI')
assert any(proj.name == 'test-p3' for proj in projs)
print('✓ Assign OK')

# Skills
s = Skill(id='test-skill-p3', name='测试技能', description='测试', content='技能内容')
path = save_skill(s)
skills = list_skills()
assert any(sk.id == 'test-skill-p3' for sk in skills)
os.unlink(path)
print('✓ Skills OK')

# Cleanup
shutil.rmtree(p.directory)

import subprocess
for cmd in [['marneo','projects','--help'],['marneo','assign','--help'],['marneo','skills','--help']]:
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == 0, f'{cmd}: {r.stderr[:60]}'
print('✓ CLI commands OK')

print()
print('ALL CHECKS PASSED')
"
```

### Step 2: 最终提交

```bash
cd /Users/chamber/code/marneo-agent
git log --oneline -5
```
