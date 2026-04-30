from marneo.cli.setup_cmd import (
    _api_key_from_env,
    _build_provider_from_options,
    _existing_provider_choices,
    _feishu_next_steps,
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
