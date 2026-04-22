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
    project: str | None = typer.Option(None, "--project", "-p"),
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
    skill_id: str = typer.Argument(..., help="技能 ID"),
    project: str | None = typer.Option(None, "--project", "-p"),
) -> None:
    """创建新技能。"""
    from prompt_toolkit import prompt as pt_prompt
    from marneo.project.skills import Skill, save_skill

    try:
        name = pt_prompt(f"  技能名称 [{skill_id}]: ").strip() or skill_id
        description = pt_prompt("  一句话描述: ").strip()
        console.print("  技能内容（Enter 换行，Ctrl+D 完成）:")
        lines: list[str] = []
        try:
            while True:
                line = pt_prompt("  ").strip()
                lines.append(line)
        except (EOFError, KeyboardInterrupt):
            pass
        content = "\n".join(lines)
    except KeyboardInterrupt:
        console.print("\n[dim]已取消。[/dim]")
        raise typer.Exit()

    scope = f"project:{project}" if project else "global"
    skill = Skill(id=skill_id, name=name, description=description, scope=scope, content=content)
    path = save_skill(skill)
    console.print(f"[green]✓ 技能已保存 → {path}[/green]")


@skills_app.command("show")
def cmd_show(skill_id: str = typer.Argument(..., help="技能 ID")) -> None:
    """查看技能详情。"""
    from marneo.project.skills import list_skills

    skills = list_skills()
    skill = next((s for s in skills if s.id == skill_id), None)
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
    from dataclasses import replace as dc_replace
    skills = list_skills()
    skill = next((s for s in skills if s.id == skill_id), None)
    if not skill:
        console.print(f"[red]技能 '{skill_id}' 不存在。[/red]")
        raise typer.Exit(1)
    save_skill(dc_replace(skill, enabled=False))
    console.print(f"[dim]{skill_id} 已禁用。[/dim]")


@skills_app.command("enable")
def cmd_enable(skill_id: str = typer.Argument(..., help="技能 ID")) -> None:
    """启用技能。"""
    from marneo.project.skills import _global_skills_dir, _parse_skill_file, save_skill
    from dataclasses import replace as dc_replace
    path = _global_skills_dir() / f"{skill_id}.md"
    if not path.exists():
        console.print(f"[red]技能 '{skill_id}' 不存在。[/red]")
        raise typer.Exit(1)
    skill = _parse_skill_file(path)
    if skill:
        save_skill(dc_replace(skill, enabled=True))
        console.print(f"[green]✓ {skill_id} 已启用。[/green]")
