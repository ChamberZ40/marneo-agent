# marneo/cli/projects_cmd.py
"""marneo projects + marneo assign commands."""
from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()
projects_app = typer.Typer(help="项目管理。", invoke_without_command=True)
assign_app = typer.Typer(help="将员工分配到项目。")


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
            t.add_row(name, p.description[:40] or "—",
                      ", ".join(p.assigned_employees) or "—", str(len(p.goals)))
    console.print()
    console.print(t)


@projects_app.command("new")
def cmd_new(name: str = typer.Argument(..., help="项目名称")) -> None:
    """通过 LLM 面试创建新项目。"""
    from prompt_toolkit import prompt as pt_prompt
    from marneo.project.workspace import load_project, create_project
    from marneo.project.interview import (
        next_question, synthesize_agent_md, extract_project_yaml_data, MAX_ROUNDS,
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

    history: list[dict] = []
    round_num = 0

    while round_num < MAX_ROUNDS:
        console.print(f"\n[dim]思考中...[/dim]")
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

        ans = raw
        if options and raw:
            first = raw[0].upper()
            matched = next((t for l, t in options if l == first), None)
            if matched:
                sup = raw[1:].strip().lstrip("，, ")
                ans = f"{matched}。{sup}" if sup else matched

        history.append({"role": "assistant", "content": question})
        history.append({"role": "user", "content": ans})

    console.print(f"\n[dim]面试完成（{round_num} 轮），生成项目档案...[/dim]")

    agent_md = synthesize_agent_md(history, name)
    yaml_data = extract_project_yaml_data(history)

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
        f"  工作档案 → [dim]{project.agent_path}[/dim]\n\n"
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

    goals_str = "\n".join(f"  • {g}" for g in p.goals) or "  （暂无）"
    console.print()
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
        console.print(Panel(agent, title="[dim]工作档案[/dim]",
                            border_style="#555555", padding=(1, 2)))
    console.print()


@assign_app.callback(invoke_without_command=True)
def cmd_assign(
    project: str = typer.Argument(..., help="项目名称"),
    employee: str | None = typer.Option(None, "--employee", "-e"),
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
