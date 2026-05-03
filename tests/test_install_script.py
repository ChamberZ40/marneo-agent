from pathlib import Path
import os
import subprocess


ROOT = Path(__file__).resolve().parents[1]
INSTALL_SCRIPT = ROOT / "scripts" / "install.sh"
README = ROOT / "README.md"


def test_install_script_exists_and_uses_hermes_style_layout():
    text = INSTALL_SCRIPT.read_text(encoding="utf-8")

    assert text.startswith("#!/usr/bin/env bash")
    assert "MARNEO_HOME" in text
    assert "MARNEO_INSTALL_DIR" in text
    assert "~/.marneo/marneo-agent" in text
    assert "git clone" in text
    assert "uv venv" in text
    assert "uv pip install -e" in text
    assert "ln -sf" in text
    assert "marneo setup" in text


def test_install_script_supports_noninteractive_and_skip_setup_options():
    text = INSTALL_SCRIPT.read_text(encoding="utf-8")

    assert "IS_INTERACTIVE" in text
    assert "--skip-setup" in text
    assert "--branch" in text
    assert "--dir" in text
    assert "--marneo-home" in text
    assert "MARNEO_INSTALL_DRY_RUN" in text


def test_install_script_is_secret_safe():
    text = INSTALL_SCRIPT.read_text(encoding="utf-8").lower()

    assert "app_secret=" not in text
    assert "api_key=" not in text
    assert "access_token=" not in text
    assert "ticket=" not in text
    assert "sk-" not in text


def test_install_script_marneo_home_updates_default_install_dir():
    result = subprocess.run(
        [
            "bash",
            str(INSTALL_SCRIPT),
            "--skip-setup",
            "--marneo-home",
            "/tmp/marneo-home-only-test",
        ],
        env={**os.environ, "MARNEO_INSTALL_DRY_RUN": "1"},
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    assert "Data directory:    /tmp/marneo-home-only-test" in result.stdout
    assert "Install directory: /tmp/marneo-home-only-test/marneo-agent" in result.stdout


def test_readme_documents_automatic_install_before_developer_install():
    text = README.read_text(encoding="utf-8")

    auto = text.index("curl -fsSL https://raw.githubusercontent.com/ChamberZ40/marneo-agent/main/scripts/install.sh | bash")
    dev = text.index("python3 -m pip install -e '.[dev]'")
    assert auto < dev
    assert "MARNEO_INSTALL_DIR" in text
    assert "marneo gateway start" in text
