from marneo.cli.setup_cmd import (
    _api_key_from_env,
    _build_local_provider_from_options,
    _build_provider_from_options,
    _existing_provider_choices,
    _feishu_next_steps,
    _local_cli_next_steps,
    _mask_secret,
)


def test_api_key_from_env_uses_known_provider_hint(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")

    provider = _build_provider_from_options(
        provider_id="openrouter",
        api_key=None,
        model="anthropic/claude-sonnet-4-6",
        base_url=None,
        protocol=None,
        use_env=True,
    )

    assert provider.id == "openrouter"
    assert provider.base_url == "https://openrouter.ai/api/v1"
    assert provider.protocol == "openai-compatible"
    assert provider.model == "anthropic/claude-sonnet-4-6"
    assert provider.api_key == "${OPENROUTER_API_KEY}"


def test_custom_provider_requires_base_url():
    try:
        _build_provider_from_options(
            provider_id="custom",
            api_key="sk-test",
            model="model-x",
            base_url=None,
            protocol=None,
            use_env=False,
        )
    except ValueError as exc:
        assert "Base URL" in str(exc)
    else:
        raise AssertionError("custom provider without base_url should fail")


def test_mask_secret_keeps_secret_out_of_status():
    assert _mask_secret("sk-1234567890abcdef") == "sk-1…cdef"
    assert _mask_secret("${OPENROUTER_API_KEY}") == "${OPENROUTER_API_KEY}"
    assert _mask_secret("") == "—"


def test_api_key_from_env_returns_reference_not_raw_secret(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "super-secret")

    ref = _api_key_from_env("anthropic")

    assert ref == "${ANTHROPIC_API_KEY}"


def test_existing_provider_choices_offer_skip_to_feishu_instead_of_only_reconfigure():
    choices = _existing_provider_choices()

    assert choices[0][0] == "skip_feishu"
    assert "跳过 Provider" in choices[0][1]
    assert any(action == "reconfigure_provider" for action, _label in choices)
    assert any(action == "exit" for action, _label in choices)


def test_feishu_next_steps_make_employee_channel_explicit():
    text = _feishu_next_steps("laoqi")

    assert "feishu:laoqi" in text
    assert "marneo setup feishu --employee laoqi" in text
    assert "marneo gateway restart" in text


def test_ollama_provider_does_not_require_real_api_key():
    provider = _build_provider_from_options(
        provider_id="ollama",
        api_key=None,
        model="qwen2.5-coder:7b",
        base_url=None,
        protocol=None,
        use_env=False,
    )

    assert provider.id == "ollama"
    assert provider.base_url == "http://localhost:11434/v1"
    assert provider.api_key == "ollama"
    assert provider.model == "qwen2.5-coder:7b"


def test_local_cli_next_steps_prefer_work_not_web():
    text = _local_cli_next_steps()

    assert "marneo work" in text
    assert "marneo gateway" not in text
    assert "marneo web" not in text


def test_build_local_provider_from_options_enforces_loopback():
    provider = _build_local_provider_from_options(model="llama3.3", base_url="http://127.0.0.1:11434/v1")

    assert provider.id == "ollama"
    assert provider.base_url == "http://127.0.0.1:11434/v1"
    assert provider.api_key == "ollama"
    assert provider.model == "llama3.3"

    try:
        _build_local_provider_from_options(model="bad", base_url="https://openrouter.ai/api/v1")
    except ValueError as exc:
        assert "local" in str(exc).lower() or "本地" in str(exc)
    else:
        raise AssertionError("local setup must reject non-loopback provider URLs")
