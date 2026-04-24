# marneo/cli/memory_cmd.py
"""marneo memory — memory management commands."""
from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

console = Console()
memory_app = typer.Typer(help="记忆管理。")


@memory_app.command("add")
def cmd_add(
    content: str = typer.Argument(..., help="要记住的内容"),
    name: str = typer.Option(..., "--employee", "-e", help="员工名称"),
    core: bool = typer.Option(False, "--core", help="写入核心记忆（永远加载）"),
) -> None:
    """为员工添加记忆条目。"""
    if core:
        from marneo.memory.core import CoreMemory
        cm = CoreMemory.for_employee(name)
        cm.add(content, source="manual")
        console.print(f"[green]✓ 已写入核心记忆：{content[:60]}[/green]")
    else:
        from marneo.memory.episodes import EpisodeStore, Episode
        store = EpisodeStore.for_employee(name)
        ep = Episode(content=content, type="general", source="episode")
        ep_id = store.add(ep)
        console.print(f"[green]✓ 已写入经验记忆 [{ep_id}]：{content[:60]}[/green]")


@memory_app.command("list")
def cmd_list(
    name: str = typer.Option(..., "--employee", "-e", help="员工名称"),
    core: bool = typer.Option(False, "--core", help="只显示核心记忆"),
    n: int = typer.Option(20, "-n", help="显示最近 N 条经验"),
) -> None:
    """列出员工的记忆条目。"""
    if core:
        from marneo.memory.core import CoreMemory
        cm = CoreMemory.for_employee(name)
        entries = cm.list_entries()
        if not entries:
            console.print("[dim]暂无核心记忆。[/dim]")
            return
        t = Table(title=f"{name} 核心记忆", show_header=True, header_style="bold #FFD700")
        t.add_column("内容")
        t.add_column("来源", style="dim")
        for e in entries:
            t.add_row(e["content"], e.get("source", "manual"))
        console.print(t)
    else:
        from marneo.memory.episodes import EpisodeStore
        store = EpisodeStore.for_employee(name)
        episodes = store.list_recent(limit=n)
        if not episodes:
            console.print("[dim]暂无经验记忆。[/dim]")
            return
        t = Table(title=f"{name} 经验记忆（最近 {n} 条）", show_header=True, header_style="bold #FFD700")
        t.add_column("ID", style="dim")
        t.add_column("内容")
        t.add_column("类型", style="dim")
        t.add_column("来源", style="dim")
        t.add_column("召回", justify="right", style="dim")
        for ep in episodes:
            t.add_row(ep.id[:12], ep.content[:60], ep.type, ep.source, str(ep.access_count))
        console.print(t)


@memory_app.command("stats")
def cmd_stats(
    name: str = typer.Option(..., "--employee", "-e", help="员工名称"),
) -> None:
    """查看记忆库统计。"""
    from marneo.memory.core import CoreMemory
    from marneo.memory.episodes import EpisodeStore

    cm = CoreMemory.for_employee(name)
    core_entries = cm.list_entries()
    store = EpisodeStore.for_employee(name)
    total = store.count()
    skills = len([e for e in store.list_recent(limit=10000, source="skill")])
    episodes_count = total - skills

    console.print(f"\n[bold #FF6611]{name} 记忆统计[/bold #FF6611]")
    console.print(f"  核心记忆：{len(core_entries)} 条")
    console.print(f"  经验记忆：{episodes_count} 条")
    console.print(f"  技能索引：{skills} 条")
    console.print(f"  总计：{total} 条\n")


@memory_app.command("rebuild")
def cmd_rebuild(
    name: str = typer.Option(..., "--employee", "-e", help="员工名称"),
) -> None:
    """重建技能索引 + 向量索引。"""
    from marneo.memory.skill_index import rebuild_skill_index
    from marneo.memory.retriever import HybridRetriever

    console.print("[dim]重建技能索引...[/dim]")
    count = rebuild_skill_index(name)
    console.print(f"[dim]技能已索引 {count} 个，重建向量索引...[/dim]")
    retriever = HybridRetriever.for_employee(name)
    retriever.rebuild_index()
    console.print(f"[green]✓ 重建完成（{count} 个技能）[/green]")
