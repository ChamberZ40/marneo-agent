# marneo/cli/hire_cmd.py
"""marneo hire — interview and onboard a new digital employee."""
from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel

console = Console()
hire_app = typer.Typer(help="招聘新的数字员工（面试入职）。", invoke_without_command=True)

_RST  = "\033[0m"
_PRI  = "\033[1;38;2;255;102;17m"
_GOLD = "\033[38;2;255;215;0m"
_DIM  = "\033[38;2;85;85;85m"


@hire_app.callback(invoke_without_command=True)
def cmd_hire(
    name: str | None = typer.Option(None, "--name", "-n", help="员工名称"),
) -> None:
    """招聘新的数字员工——通过 LLM 面试生成专属身份档案。"""
    from prompt_toolkit import prompt as pt_prompt
    from marneo.employee.profile import create_employee, load_profile
    from marneo.employee.interview import next_question, parse_question, synthesize_soul, MAX_ROUNDS

    console.print()
    console.print(Panel(
        "[bold #FF6611]Marneo 招聘面试[/bold #FF6611]\n\n"
        "通过 AI 面试，为新员工生成专属身份档案（SOUL.md）。\n"
        "[dim]Ctrl+C 可随时取消。[/dim]",
        border_style="#FF6611", padding=(1, 2),
    ))

    # Get employee name
    if not name:
        try:
            name = pt_prompt("  员工名称（如 GAI）: ").strip()
        except KeyboardInterrupt:
            console.print("\n[dim]已取消。[/dim]")
            raise typer.Exit()
    if not name:
        console.print("[red]员工名称不能为空。[/red]")
        raise typer.Exit(1)

    # Check existing
    if load_profile(name):
        console.print(f"[yellow]员工 {name} 已存在。[/yellow]")
        try:
            ans = pt_prompt("  重新面试？(y/N) ").strip().lower()
        except KeyboardInterrupt:
            raise typer.Exit()
        if ans not in ("y", "yes"):
            raise typer.Exit()

    # Interview loop
    history: list[dict] = []
    round_num = 0

    while round_num < MAX_ROUNDS:
        console.print(f"\n[dim]正在生成第 {round_num + 1} 个问题...[/dim]")
        question = next_question(history, round_num)
        if question is None:
            break

        round_num += 1
        q_text, options = parse_question(question)

        console.print(f"\n[bold #FFD700]Q{round_num}[/bold #FFD700]  {q_text}")
        for letter, opt_text in options:
            console.print(f"  [dim]{letter}.[/dim] {opt_text}")
        if options:
            console.print(f"  [dim]输入字母选择，可追加说明（如 A 但我更倾向于...）[/dim]")

        try:
            raw_answer = pt_prompt("  → ").strip()
        except KeyboardInterrupt:
            console.print("\n[dim]已取消。[/dim]")
            raise typer.Exit()

        if not raw_answer:
            raw_answer = "（跳过）"

        # Expand letter selection
        answer = raw_answer
        if options and raw_answer:
            first_char = raw_answer[0].upper()
            matched = next(
                (text for letter, text in options if letter == first_char), None
            )
            if matched:
                supplement = raw_answer[1:].strip().lstrip("，,、 ")
                answer = f"{matched}。{supplement}" if supplement else matched

        history.append({"role": "assistant", "content": question})
        history.append({"role": "user", "content": answer})

    # Synthesize SOUL.md
    console.print(f"\n[dim]面试完成（{round_num} 轮），正在生成身份档案...[/dim]")
    soul_content = synthesize_soul(history)

    # Show preview
    console.print()
    console.print(Panel(
        soul_content,
        title=f"[bold #00FFCC]✦ {name} 的 SOUL.md[/bold #00FFCC]",
        border_style="#00FFCC", padding=(1, 2),
    ))

    # Confirm or refine
    try:
        confirm = pt_prompt("  直接回车保存，输入意见让 AI 修改，q 取消: ").strip()
    except KeyboardInterrupt:
        raise typer.Exit()

    if confirm.lower() in ("q", "quit", "取消"):
        console.print("[dim]已取消。[/dim]")
        raise typer.Exit()

    if confirm:
        console.print("[dim]修改中...[/dim]")
        try:
            from marneo.employee.interview import _call_llm
            soul_content = _call_llm(
                [{"role": "user", "content": (
                    f"当前文档：\n{soul_content}\n\n"
                    f"修改意见：{confirm}\n\n"
                    "请直接输出修改后的完整文档。"
                )}],
                system="你是专业文字编辑，直接输出修改后的内容，不要任何解释。",
                max_tokens=600,
            )
        except Exception:
            pass

    # Save profile and SOUL.md
    answers = [m["content"] for m in history if m["role"] == "user"]
    profile = create_employee(
        name=name,
        personality=answers[0][:30] if answers else "",
        domains=answers[1][:30] if len(answers) > 1 else "",
        style=answers[2][:30] if len(answers) > 2 else "",
    )
    profile.soul_path.write_text(soul_content, encoding="utf-8")

    console.print()
    console.print(Panel(
        f"[bold #FF6611]{name}[/bold #FF6611] 已正式入职！🎉\n\n"
        f"  级别：[bold #FFD700]实习生[/bold #FFD700]\n"
        f"  SOUL：[dim]{profile.soul_path}[/dim]\n\n"
        f"运行 [bold]marneo work[/bold] 开始与 {name} 对话。",
        border_style="#FFD700", padding=(1, 2),
    ))
