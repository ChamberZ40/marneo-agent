# marneo/cli/team_cmd.py
"""marneo team — manage multi-employee team collaboration."""
from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()
team_app = typer.Typer(help="多员工团队协作管理。", invoke_without_command=True)


@team_app.callback(invoke_without_command=True)
def team_default(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        console.print("[dim]用法: marneo team <命令> <项目>[/dim]")
        console.print("[dim]  setup  <project>  交互式配置团队[/dim]")
        console.print("[dim]  list   <project>  查看团队配置[/dim]")
        console.print("[dim]  add    <project>  添加成员[/dim]")
        console.print("[dim]  remove <project>  移除成员[/dim]")


@team_app.command("list")
def cmd_list(project: str = typer.Argument(..., help="项目名称")) -> None:
    """查看项目团队配置。"""
    from marneo.collaboration.team import load_team_config
    from marneo.project.workspace import load_project

    p = load_project(project)
    if not p:
        console.print(f"[red]项目 '{project}' 不存在。[/red]")
        raise typer.Exit(1)

    team = load_team_config(project)
    if not team or not team.members:
        console.print(f"[dim]项目 '{project}' 尚未配置团队。运行 marneo team setup {project}[/dim]")
        return

    t = Table(title=f"团队：{project}", show_header=True, header_style="bold #FFD700")
    t.add_column("员工", style="cyan")
    t.add_column("角色")
    t.add_column("身份", style="dim")
    for m in team.members:
        identity = "[bold #FF6611]协调者[/bold #FF6611]" if m.employee == team.coordinator else "专员"
        t.add_row(m.employee, m.role or "—", identity)

    console.print()
    console.print(t)
    if team.team_chat_id:
        console.print(f"  [dim]团队群 ID：{team.team_chat_id}[/dim]")
    console.print()


@team_app.command("setup")
def cmd_setup(project: str = typer.Argument(..., help="项目名称")) -> None:
    """交互式配置团队（选成员+角色+协调者+群ID）。"""
    from prompt_toolkit import prompt as pt_prompt
    from marneo.collaboration.team import TeamConfig, TeamMember, save_team_config
    from marneo.employee.profile import list_employees
    from marneo.project.workspace import load_project
    from marneo.tui.select_ui import checklist, radiolist

    p = load_project(project)
    if not p:
        console.print(f"[red]项目 '{project}' 不存在。[/red]")
        raise typer.Exit(1)

    console.print()
    console.print(Panel(
        f"[bold #FF6611]配置项目团队：{project}[/bold #FF6611]\n\n"
        "设置多员工并行协作团队。\n"
        "[dim]↑↓ 移动  空格 选择  Enter 确认[/dim]",
        border_style="#FF6611", padding=(1, 2),
    ))

    all_employees = list_employees()
    if len(all_employees) < 2:
        console.print("[yellow]至少需要 2 名员工才能组建团队。运行 marneo hire 招聘更多员工。[/yellow]")
        raise typer.Exit(1)

    # Select team members
    selected_idx = checklist("选择团队成员（至少 2 人）：", all_employees)
    if len(selected_idx) < 2:
        console.print("[yellow]至少需要选择 2 名成员。[/yellow]")
        raise typer.Exit(1)

    selected_names = [all_employees[i] for i in selected_idx]

    # Assign roles
    members: list[TeamMember] = []
    for emp_name in selected_names:
        try:
            role = pt_prompt(f"  {emp_name} 的角色（如：数据分析、内容策划）: ").strip()
        except KeyboardInterrupt:
            role = ""
        members.append(TeamMember(employee=emp_name, role=role))

    # Select coordinator
    coord_idx = radiolist("选择协调者（负责分配任务和汇总结果）：", selected_names, default=0)
    coordinator = selected_names[coord_idx]

    # Team chat ID
    try:
        team_chat_id = pt_prompt(
            "  飞书团队群 ID（用于员工间 @mention 协作，可稍后配置）: "
        ).strip()
    except KeyboardInterrupt:
        team_chat_id = ""

    config = TeamConfig(
        project_name=project,
        coordinator=coordinator,
        team_chat_id=team_chat_id,
        members=members,
    )
    save_team_config(config)

    console.print()
    console.print(Panel(
        f"[bold #FF6611]团队已配置！[/bold #FF6611]\n\n"
        f"  协调者：[bold #FFD700]{coordinator}[/bold #FFD700]\n"
        f"  成员：{', '.join(selected_names)}\n"
        f"  团队群：[dim]{team_chat_id or '未设置'}[/dim]\n\n"
        "运行 [bold]marneo work[/bold] 与协调者对话，触发团队协作。",
        border_style="#FFD700", padding=(1, 2),
    ))


@team_app.command("add")
def cmd_add(
    project: str = typer.Argument(..., help="项目名称"),
    employee: str = typer.Option(..., "--employee", "-e", help="员工名称"),
    role: str = typer.Option("", "--role", "-r", help="角色描述"),
) -> None:
    """向团队添加成员。"""
    from marneo.collaboration.team import load_team_config, TeamConfig, TeamMember, save_team_config

    team = load_team_config(project) or TeamConfig(project_name=project)
    if employee in team.member_names:
        console.print(f"[yellow]{employee} 已在团队中。[/yellow]")
        return
    team.members.append(TeamMember(employee=employee, role=role))
    if not team.coordinator:
        team.coordinator = employee
    save_team_config(team)
    console.print(f"[green]✓ {employee} 已加入团队 {project}[/green]")


@team_app.command("remove")
def cmd_remove(
    project: str = typer.Argument(..., help="项目名称"),
    employee: str = typer.Option(..., "--employee", "-e", help="员工名称"),
) -> None:
    """从团队移除成员。"""
    from marneo.collaboration.team import load_team_config, save_team_config

    team = load_team_config(project)
    if not team:
        console.print(f"[dim]项目 '{project}' 尚无团队配置。[/dim]")
        return
    new_members = [m for m in team.members if m.employee != employee]
    if len(new_members) == len(team.members):
        console.print(f"[yellow]{employee} 不在团队中。[/yellow]")
        return
    team.members = new_members
    if team.coordinator == employee:
        team.coordinator = new_members[0].employee if new_members else ""
    save_team_config(team)
    console.print(f"[dim]{employee} 已从团队 {project} 移除。[/dim]")
