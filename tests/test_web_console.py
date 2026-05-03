import pytest
from typer.testing import CliRunner

from marneo.cli.app import app
from marneo.core.config import ProviderConfig, save_config
from marneo.employee.profile import create_employee
from marneo.project.workspace import assign_employee, create_project


runner = CliRunner()


def test_web_command_is_registered_in_cli_help():
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "web" in result.output
    assert "local" in result.output.lower() or "本地" in result.output


def test_web_rejects_non_loopback_host_unless_lan_is_explicitly_allowed():
    from marneo.web.app import validate_bind_host

    with pytest.raises(ValueError):
        validate_bind_host("0.0.0.0", allow_lan=False)

    assert validate_bind_host("127.0.0.1", allow_lan=False) == "127.0.0.1"
    assert validate_bind_host("localhost", allow_lan=False) == "localhost"
    assert validate_bind_host("0.0.0.0", allow_lan=True) == "0.0.0.0"


def test_web_status_payload_is_local_and_redacted(monkeypatch):
    from marneo.web.api import build_status_payload

    save_config(
        ProviderConfig(
            id="openrouter",
            base_url="https://openrouter.ai/api/v1",
            api_key="sk-super-secret-value",
            model="anthropic/claude-sonnet-4-6",
        ),
        local_only=False,
    )
    create_employee("laoqi")

    payload = build_status_payload()

    assert payload["provider"]["configured"] is True
    assert payload["provider"]["id"] == "openrouter"
    assert payload["provider"]["api_key"] != "sk-super-secret-value"
    assert "super-secret" not in str(payload)
    assert payload["employees"]["count"] == 1
    assert payload["server"]["bind_default"] == "127.0.0.1"


def test_web_api_lists_employees_and_projects():
    from marneo.web.api import build_employees_payload, build_projects_payload

    create_employee("Alice", personality="务实", domains="增长", style="简洁")
    create_project("growth", description="增长项目", goals=["GMV"],)
    assign_employee("growth", "Alice")

    employees = build_employees_payload()
    projects = build_projects_payload()

    assert employees["employees"][0]["name"] == "Alice"
    assert employees["employees"][0]["projects"] == ["growth"]
    assert projects["projects"][0]["name"] == "growth"
    assert projects["projects"][0]["assigned_employees"] == ["Alice"]


def test_web_index_is_static_local_console_not_external_channel():
    from marneo.web.app import render_index_html

    html = render_index_html()

    assert "Marneo Local Console" in html
    assert "/api/status" in html
    assert "marneo work" in html
    assert "third channel" not in html.lower()
