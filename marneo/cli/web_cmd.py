"""marneo web — local browser console."""
from __future__ import annotations

import webbrowser

import typer
from rich.console import Console

console = Console()
web_app = typer.Typer(help="本地 Web Console（loopback-only）。", invoke_without_command=True)


@web_app.callback(invoke_without_command=True)
def cmd_web(
    host: str = typer.Option("127.0.0.1", "--host", help="绑定地址，默认只监听本机 loopback。"),
    port: int = typer.Option(8787, "--port", "-p", help="监听端口。"),
    open_browser: bool = typer.Option(False, "--open", help="启动后打开浏览器。"),
    allow_lan: bool = typer.Option(False, "--allow-lan", help="允许绑定到 0.0.0.0 或局域网地址。"),
) -> None:
    """启动本地 Web Console。"""
    from marneo.web.app import validate_bind_host, serve

    try:
        bind_host = validate_bind_host(host, allow_lan=allow_lan)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    url_host = "127.0.0.1" if bind_host in {"0.0.0.0", "::"} else bind_host
    url = f"http://{url_host}:{port}"
    console.print("[bold #FF6611]Marneo Local Console[/bold #FF6611]")
    console.print(f"[dim]Listening on {url}[/dim]")
    console.print("[dim]This is a local UI over marneo work data; Feishu remains under marneo gateway.[/dim]")
    if open_browser:
        webbrowser.open(url)
    try:
        serve(host=bind_host, port=port, allow_lan=True)
    except KeyboardInterrupt:
        console.print("\n[dim]Marneo Local Console stopped.[/dim]")
