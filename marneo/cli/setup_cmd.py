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


def _provider_by_id(provider_id: str) -> dict | None:
    for provider in KNOWN_PROVIDERS:
        if provider["id"] == provider_id:
            return provider
    return None


def _detect_protocol(url: str) -> str:
    u = url.lower()
    if "anthropic.com" in u or u.rstrip("/").endswith("/anthropic"):
        return "anthropic-compatible"
    return "openai-compatible"


def _api_key_from_env(provider_id: str) -> str | None:
    """Return a ${ENV_VAR} reference for a known provider if that env var exists."""
    import os

    provider = _provider_by_id(provider_id)
    if not provider:
        return None
    key_hint = str(provider.get("key_hint", ""))
    if not key_hint or " " in key_hint or key_hint.startswith("("):
        return None
    if os.environ.get(key_hint):
        return f"${{{key_hint}}}"
    return None


def _mask_secret(value: str) -> str:
    if not value:
        return "—"
    if value.startswith("${") and value.endswith("}"):
        return value
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}…{value[-4:]}"


def _build_local_provider_from_options(
    model: str | None = None,
    base_url: str | None = None,
):
    """Build a loopback-only Ollama/OpenAI-compatible provider for private mode."""
    from marneo.core.config import ProviderConfig, is_local_provider_url

    final_base_url = base_url or "http://localhost:11434/v1"
    if not is_local_provider_url(final_base_url):
        raise ValueError("本地-only/private 模式只允许 localhost/loopback Provider URL")
    return ProviderConfig(
        id="ollama",
        base_url=final_base_url,
        api_key="ollama",
        model=model or "llama3.3",
        protocol="openai-compatible",
    )


def _build_provider_from_options(
    provider_id: str,
    api_key: str | None,
    model: str | None,
    base_url: str | None,
    protocol: str | None,
    use_env: bool = True,
):
    """Build a ProviderConfig from non-interactive setup options."""
    from marneo.core.config import ProviderConfig

    selected = _provider_by_id(provider_id)
    if not selected:
        raise ValueError(f"Unknown provider: {provider_id}")

    final_base_url = base_url or str(selected.get("base_url", ""))
    if not final_base_url:
        raise ValueError("Base URL is required for custom provider")

    final_protocol = protocol or str(selected.get("protocol", "")) or _detect_protocol(final_base_url)
    final_model = model or (selected.get("models") or [""])[0]
    final_api_key = api_key or (_api_key_from_env(provider_id) if use_env else None)
    if not final_api_key and provider_id == "ollama":
        final_api_key = "ollama"
    if not final_api_key:
        raise ValueError("API key is required")

    return ProviderConfig(
        id=provider_id,
        base_url=final_base_url,
        api_key=final_api_key,
        model=final_model,
        protocol=final_protocol,
    )


def _existing_provider_choices() -> list[tuple[str, str]]:
    """Actions shown when Provider already exists.

    The first action must keep onboarding moving forward: users often want to add
    another Feishu bot/channel, not re-enter their LLM provider credentials.
    """
    return [
        ("skip_feishu", "跳过 Provider，继续新增/配置飞书机器人"),
        ("reconfigure_provider", "重新配置 Provider"),
        ("exit", "退出"),
    ]


def _feishu_next_steps(employee_name: str | None = None) -> str:
    if employee_name:
        setup_cmd = f"marneo setup feishu --employee {employee_name}"
        channel = f"feishu:{employee_name}"
    else:
        setup_cmd = "marneo setup feishu"
        channel = "feishu:<员工名>"
    return (
        "下一步：\n"
        f"  1. 新增/更新飞书机器人 → {setup_cmd}\n"
        f"  2. 重启网关 → marneo gateway restart\n"
        f"  3. 查看状态 → marneo gateway status\n"
        f"  4. 期望 channel → {channel}"
    )


def _local_cli_next_steps() -> str:
    return (
        "本地 CLI 下一步：\n"
        "  1. 创建/确认数字员工 → marneo hire\n"
        "  2. 本地命令行对话 → marneo work\n"
        "  3. 本地-only/private 模式下，外联工具会被禁用，LLM 应使用 Ollama/localhost"
    )


def _choose_existing_provider_action() -> str:
    from marneo.tui.select_ui import radiolist

    choices = _existing_provider_choices()
    idx = radiolist("Provider 已配置，下一步：", [label for _action, label in choices], default=0)
    return choices[idx][0]


@setup_app.callback(invoke_without_command=True)
def setup_main(ctx: typer.Context) -> None:
    """配置 Marneo Provider。"""
    if ctx.invoked_subcommand is None:
        _run_setup()


@setup_app.command("feishu")
def setup_feishu(
    employee: str | None = typer.Option(None, "--employee", "-e", help="要绑定飞书机器人的员工名称"),
) -> None:
    """新增/配置员工专属飞书 Bot，并形成 feishu:<员工名> channel。"""
    _run_feishu_setup(employee)


@setup_app.command("local")
def setup_local(
    model: str = typer.Option("llama3.3", "--model", "-m", help="本地模型名，例如 llama3.3 / qwen2.5-coder:7b"),
    base_url: str = typer.Option("http://localhost:11434/v1", "--base-url", help="本地 OpenAI-compatible Provider URL"),
) -> None:
    """配置本地-only/private 模式，默认使用 Ollama/localhost。"""
    provider = _build_local_provider_from_options(model=model, base_url=base_url)
    from marneo.core.config import save_config

    path = save_config(provider, local_only=True)
    console.print(f"[green]✓ 本地-only/private 配置已保存 → {path}[/green]")
    console.print(Panel(_local_cli_next_steps(), border_style="#00FFCC", padding=(1, 2)))


def _run_feishu_setup(employee_name: str | None = None) -> None:
    from marneo.employee.profile import list_employees

    target = employee_name
    employees = list_employees()
    if not target:
        if not employees:
            console.print("[yellow]还没有员工。请先运行 [bold]marneo hire[/bold] 创建员工，再运行 [bold]marneo setup feishu[/bold]。[/yellow]")
            return
        if len(employees) == 1:
            target = employees[0]
            console.print(f"[dim]使用唯一员工：{target}[/dim]")
        else:
            from marneo.tui.select_ui import radiolist
            idx = radiolist("选择要绑定飞书机器人的员工：", employees, default=0)
            target = employees[idx]

    from marneo.cli.employee_feishu_cmd import cmd_setup as setup_employee_feishu

    setup_employee_feishu(target)
    console.print()
    console.print(Panel(_feishu_next_steps(target), border_style="#00FFCC", padding=(1, 2)))


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
        console.print(f"[green]✓ 已配置 Provider: {cfg.provider.id} / {cfg.provider.model}[/green]")
        console.print("[dim]如果只是新增飞书机器人/channel，不需要重新配置 Provider。[/dim]")
        try:
            action = _choose_existing_provider_action()
        except KeyboardInterrupt:
            return
        if action == "skip_feishu":
            _run_feishu_setup()
            return
        if action != "reconfigure_provider":
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
        if not api_key and selected["id"] == "ollama":
            api_key = "ollama"
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
    path = save_config(provider, local_only=(selected["id"] == "ollama"))

    console.print("\n[dim]测试连接...[/dim]")
    _test_provider(provider)
    console.print(f"\n[green]✓ 配置已保存 → {path}[/green]")
    console.print(f"[dim]{_feishu_next_steps()}[/dim]")


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
