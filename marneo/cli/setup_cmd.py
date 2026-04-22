# marneo/cli/setup_cmd.py
"""marneo setup — configure provider."""
from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel

console = Console()
setup_app = typer.Typer(help="配置 Marneo（Provider 等）。", invoke_without_command=True)

KNOWN_PROVIDERS = [
    {"id": "anthropic", "name": "Anthropic (Claude)",
     "base_url": "https://api.anthropic.com",
     "protocol": "anthropic-compatible",
     "models": ["claude-sonnet-4-6", "claude-haiku-4-5-20251001"],
     "key_hint": "ANTHROPIC_API_KEY"},
    {"id": "openai", "name": "OpenAI (GPT)",
     "base_url": "https://api.openai.com/v1",
     "protocol": "openai-compatible",
     "models": ["gpt-4o", "gpt-4o-mini"],
     "key_hint": "OPENAI_API_KEY"},
    {"id": "deepseek", "name": "DeepSeek",
     "base_url": "https://api.deepseek.com/v1",
     "protocol": "openai-compatible",
     "models": ["deepseek-chat", "deepseek-reasoner"],
     "key_hint": "DEEPSEEK_API_KEY"},
    {"id": "qwen", "name": "阿里云百炼 / 通义千问",
     "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
     "protocol": "openai-compatible",
     "models": ["qwen-plus", "qwen-max"],
     "key_hint": "DASHSCOPE_API_KEY"},
    {"id": "moonshot", "name": "月之暗面 (Kimi)",
     "base_url": "https://api.moonshot.cn/v1",
     "protocol": "openai-compatible",
     "models": ["moonshot-v1-8k", "kimi-k2.5"],
     "key_hint": "MOONSHOT_API_KEY"},
    {"id": "groq", "name": "Groq",
     "base_url": "https://api.groq.com/openai/v1",
     "protocol": "openai-compatible",
     "models": ["llama-3.3-70b-versatile"],
     "key_hint": "GROQ_API_KEY"},
    {"id": "openrouter", "name": "OpenRouter (聚合)",
     "base_url": "https://openrouter.ai/api/v1",
     "protocol": "openai-compatible",
     "models": ["anthropic/claude-sonnet-4-6"],
     "key_hint": "OPENROUTER_API_KEY"},
    {"id": "ollama", "name": "Ollama (本地)",
     "base_url": "http://localhost:11434/v1",
     "protocol": "openai-compatible",
     "models": ["llama3.3", "qwen2.5-coder:7b"],
     "key_hint": "(无需 Key，填 ollama)"},
    {"id": "custom", "name": "自定义 (Custom)",
     "base_url": "", "protocol": "",
     "models": [], "key_hint": ""},
]


def _detect_protocol(url: str) -> str:
    u = url.lower()
    if "anthropic.com" in u or u.rstrip("/").endswith("/anthropic"):
        return "anthropic-compatible"
    return "openai-compatible"


@setup_app.callback(invoke_without_command=True)
def setup_main(ctx: typer.Context) -> None:
    """配置 Marneo Provider。"""
    if ctx.invoked_subcommand is None:
        _run_setup()


def _run_setup() -> None:
    from prompt_toolkit import prompt as pt_prompt
    from marneo.tui.select_ui import radiolist
    from marneo.core.config import ProviderConfig, save_config, load_config

    console.print()
    console.print(Panel(
        "[bold #FF6611]Marneo 配置向导[/bold #FF6611]\n\n"
        "配置 LLM Provider，让数字员工有能力思考。\n"
        "[dim]↑↓ 移动  Enter 确认[/dim]",
        border_style="#FF6611", padding=(1, 2),
    ))

    cfg = load_config()
    if cfg.provider:
        console.print(f"[green]✓ 已配置: {cfg.provider.id} / {cfg.provider.model}[/green]")
        try:
            ans = pt_prompt("  重新配置？(y/N) ").strip().lower()
        except KeyboardInterrupt:
            return
        if ans not in ("y", "yes"):
            return

    items = [f"{p['name']}  ({', '.join(p['models'][:2])})" for p in KNOWN_PROVIDERS]
    idx = radiolist("选择 Provider：", items, default=0)
    selected = KNOWN_PROVIDERS[idx]

    if selected["id"] == "custom":
        try:
            base_url = pt_prompt("  Base URL (含 /v1): ").strip()
            protocol = _detect_protocol(base_url)
            console.print(f"  [dim]自动推断协议: {protocol}[/dim]")
        except KeyboardInterrupt:
            return
    else:
        base_url = selected["base_url"]
        protocol = selected["protocol"]
        console.print(f"\n  [dim]Base URL:[/dim] {base_url}")

    key_hint = selected.get("key_hint", "")
    try:
        api_key = pt_prompt(
            f"  API Key{f' ({key_hint})' if key_hint else ''}: ",
            is_password=True,
        ).strip()
        if not api_key:
            console.print("[yellow]已跳过。[/yellow]")
            return
    except KeyboardInterrupt:
        return

    default_model = selected["models"][0] if selected["models"] else ""
    examples = ", ".join(selected["models"][:2])
    try:
        model = pt_prompt(
            f"  模型{f' (例: {examples})' if examples else ''} [{default_model}]: "
        ).strip() or default_model
    except KeyboardInterrupt:
        return

    provider = ProviderConfig(
        id=selected["id"],
        base_url=base_url,
        api_key=api_key,
        model=model,
        protocol=protocol,
    )
    path = save_config(provider)

    console.print("\n[dim]测试连接...[/dim]")
    _test_provider(provider)
    console.print(f"\n[green]✓ 配置已保存 → {path}[/green]")
    console.print("[dim]运行 marneo work 开始工作。[/dim]")


def _test_provider(provider: "ProviderConfig") -> None:
    try:
        import httpx
        if provider.protocol == "openai-compatible":
            url = f"{provider.base_url.rstrip('/')}/chat/completions"
            headers = {"Authorization": f"Bearer {provider.api_key}", "Content-Type": "application/json"}
            body = {"model": provider.model or "test", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1}
        else:
            url = f"{provider.base_url.rstrip('/')}/messages"
            headers = {"x-api-key": provider.api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}
            body = {"model": provider.model or "claude-haiku-4-5-20251001", "max_tokens": 1, "messages": [{"role": "user", "content": "hi"}]}

        resp = httpx.post(url, json=body, headers=headers, timeout=15.0)
        if resp.status_code in (200, 201, 400):
            console.print("[green]✓ 连接成功[/green]")
        else:
            console.print(f"[yellow]⚠ 状态码 {resp.status_code}[/yellow]")
    except Exception as e:
        console.print(f"[yellow]⚠ 连接测试失败: {e}[/yellow]")
