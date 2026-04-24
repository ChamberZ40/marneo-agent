# tests/tools/test_lark_cli.py
import json
import pytest
from unittest.mock import patch, MagicMock
from marneo.tools.core.lark_cli import (
    lark_cli, _get_feishu_credentials, _ensure_lark_cli_configured
)


def test_lark_cli_missing_command():
    result = json.loads(lark_cli({}))
    assert "error" in result


def test_lark_cli_no_lark_binary():
    with patch("shutil.which", return_value=None):
        result = json.loads(lark_cli({"command": "calendar +agenda"}))
    assert "error" in result
    assert "not installed" in result["error"]


def test_lark_cli_no_credentials():
    with patch("marneo.tools.core.lark_cli._get_feishu_credentials", return_value=("", "", "feishu")):
        result = json.loads(lark_cli({"command": "calendar +agenda"}))
    assert "error" in result


def test_get_feishu_credentials_returns_tuple():
    """Should return (app_id, app_secret, domain) tuple."""
    result = _get_feishu_credentials()
    assert isinstance(result, tuple)
    assert len(result) == 3


def test_ensure_configured_returns_none_on_success():
    """Returns None when already configured."""
    mock_proc = MagicMock()
    mock_proc.stdout = "app_id: cli_test123"
    mock_proc.stderr = ""
    mock_proc.returncode = 0
    with patch("subprocess.run", return_value=mock_proc):
        result = _ensure_lark_cli_configured("cli_test123", "secret", "feishu")
    assert result is None  # None = success


def test_lark_cli_appends_as_bot():
    """Verify --as bot is appended to commands."""
    mock_proc = MagicMock()
    mock_proc.stdout = '{"ok": true}'
    mock_proc.stderr = ""
    mock_proc.returncode = 0
    with patch("shutil.which", return_value="/usr/bin/lark-cli"), \
         patch("marneo.tools.core.lark_cli._get_feishu_credentials", return_value=("aid", "asec", "feishu")), \
         patch("marneo.tools.core.lark_cli._ensure_lark_cli_configured", return_value=None), \
         patch("subprocess.run", return_value=mock_proc) as mock_run:
        lark_cli({"command": "calendar +agenda"})
        call_args = mock_run.call_args[0][0]
        assert "--as" in call_args
        assert "bot" in call_args
