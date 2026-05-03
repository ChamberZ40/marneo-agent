import yaml

from marneo.core.config import (
    ProviderConfig,
    is_local_only_mode,
    is_local_provider_url,
    load_config,
    save_config,
)
from marneo.core.paths import get_config_path


def test_load_config_reads_privacy_local_only():
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.dump(
            {
                "privacy": {"local_only": True},
                "provider": {
                    "id": "ollama",
                    "base_url": "http://localhost:11434/v1",
                    "api_key": "ollama",
                    "model": "qwen2.5-coder:7b",
                    "protocol": "openai-compatible",
                },
            }
        ),
        encoding="utf-8",
    )

    cfg = load_config()

    assert cfg.privacy.local_only is True
    assert is_local_only_mode() is True


def test_save_config_can_enable_local_only():
    path = save_config(
        ProviderConfig(
            id="ollama",
            base_url="http://127.0.0.1:11434/v1",
            api_key="ollama",
            model="llama3.3",
        ),
        local_only=True,
    )

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))

    assert raw["privacy"]["local_only"] is True
    assert raw["provider"]["id"] == "ollama"


def test_is_local_provider_url_accepts_loopback_only():
    assert is_local_provider_url("http://localhost:11434/v1") is True
    assert is_local_provider_url("http://127.0.0.1:11434/v1") is True
    assert is_local_provider_url("http://[::1]:11434/v1") is True
    assert is_local_provider_url("https://openrouter.ai/api/v1") is False
