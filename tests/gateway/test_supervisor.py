"""Tests for gateway service supervisor rendering and CLI wiring."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from typer.testing import CliRunner

from marneo.cli.app import app
from marneo.gateway import supervisor

runner = CliRunner()


def test_render_systemd_service_uses_dynamic_command_and_user_service_paths(tmp_path):
    rendered = supervisor.render_systemd_service("/opt/marneo/bin/marneo", tmp_path)

    assert "ExecStart=/opt/marneo/bin/marneo gateway run" in rendered
    assert "User=%i" not in rendered
    assert "WantedBy=default.target" in rendered
    assert "WorkingDirectory=%h" in rendered
    assert "Environment=HOME=%h" in rendered
    assert "StandardOutput=append:%h/.marneo/logs/gateway.log" in rendered
    assert "StandardError=append:%h/.marneo/logs/gateway.log" in rendered


def test_render_launchd_plist_uses_dynamic_command_and_marneo_log_dir(tmp_path):
    rendered = supervisor.render_launchd_plist("/opt/marneo/bin/marneo", tmp_path)

    assert "<string>/opt/marneo/bin/marneo</string>" in rendered
    assert "<string>gateway</string>" in rendered
    assert "<string>run</string>" in rendered
    assert "<key>WorkingDirectory</key>" in rendered
    assert f"<string>{tmp_path}</string>" in rendered
    assert f"<string>{tmp_path}/.marneo/logs/gateway.log</string>" in rendered
    assert "/tmp/marneo-gateway" not in rendered


def test_rendering_handles_python_module_fallback_and_spaces(tmp_path):
    argv = ["/opt/Marneo Python/bin/python3", "-m", "marneo.cli.app"]

    systemd = supervisor.render_systemd_service(argv, tmp_path)
    launchd = supervisor.render_launchd_plist(argv, tmp_path)

    assert "ExecStart='/opt/Marneo Python/bin/python3' -m marneo.cli.app gateway run" in systemd
    assert "<string>/opt/Marneo Python/bin/python3</string>" in launchd
    assert "<string>-m</string>" in launchd
    assert "<string>marneo.cli.app</string>" in launchd
    assert "<string>gateway</string>" in launchd
    assert "<string>run</string>" in launchd


def test_install_service_writes_dynamic_systemd_user_unit(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(supervisor, "detect_supervisor", lambda: supervisor.SupervisorKind.SYSTEMD_USER)
    monkeypatch.setattr(supervisor, "resolve_marneo_argv", lambda: ["/custom/bin/marneo"])

    installed = supervisor.install_service()

    assert installed == tmp_path / ".config/systemd/user/marneo-gateway.service"
    text = installed.read_text(encoding="utf-8")
    assert "ExecStart=/custom/bin/marneo gateway run" in text
    assert "User=%i" not in text
    assert (tmp_path / ".marneo/logs").is_dir()


def test_install_service_writes_dynamic_launchd_plist(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(supervisor, "detect_supervisor", lambda: supervisor.SupervisorKind.LAUNCHD_USER)
    monkeypatch.setattr(supervisor, "resolve_marneo_argv", lambda: ["/Applications/Marneo/bin/marneo"])

    installed = supervisor.install_service()

    assert installed == tmp_path / "Library/LaunchAgents/com.marneo.gateway.plist"
    text = installed.read_text(encoding="utf-8")
    assert "<string>/Applications/Marneo/bin/marneo</string>" in text
    assert "<string>gateway</string>" in text
    assert "<string>run</string>" in text
    assert "/tmp/marneo-gateway" not in text


def test_gateway_install_and_install_service_alias_call_supervisor(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    installed = tmp_path / "unit.service"
    calls: list[str] = []

    def fake_install_service() -> Path:
        calls.append("install")
        return installed

    monkeypatch.setattr(supervisor, "install_service", fake_install_service)

    result_install = runner.invoke(app, ["gateway", "install"])
    result_alias = runner.invoke(app, ["gateway", "install-service"])

    assert result_install.exit_code == 0
    assert result_alias.exit_code == 0
    assert calls == ["install", "install"]
    assert "已安装系统服务" in result_install.output
    assert "unit.service" in result_install.output


def test_gateway_run_invokes_foreground_runner(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    from marneo.cli import gateway_cmd

    calls: list[str] = []
    monkeypatch.setattr(gateway_cmd, "_gateway_runner", lambda: calls.append("run"))

    result = runner.invoke(app, ["gateway", "run"])

    assert result.exit_code == 0
    assert calls == ["run"]


def test_gateway_start_uses_service_when_installed(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    from marneo.cli import gateway_cmd

    calls: list[str] = []
    monkeypatch.setattr(gateway_cmd, "_read_pid", lambda: None)

    def fake_installed(*_args, **_kwargs) -> bool:
        return True

    monkeypatch.setattr(supervisor, "is_service_installed", fake_installed)
    monkeypatch.setattr(supervisor, "start_service", lambda: calls.append("start_service"))
    monkeypatch.setattr(gateway_cmd, "_spawn_gateway_process", lambda: calls.append("spawn"))

    result = runner.invoke(app, ["gateway", "start"])

    assert result.exit_code == 0
    assert calls == ["start_service"]
    assert "system service" in result.output.lower() or "系统服务" in result.output



def test_gateway_stop_uses_service_when_installed(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    from marneo.cli import gateway_cmd

    calls: list[str] = []
    monkeypatch.setattr(gateway_cmd, "_read_pid", lambda: 123456)
    monkeypatch.setattr(supervisor, "is_service_installed", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(supervisor, "stop_service", lambda: calls.append("stop_service"))
    monkeypatch.setattr(gateway_cmd, "_terminate_gateway_pid", lambda *_args, **_kwargs: calls.append("pid_stop"))

    result = runner.invoke(app, ["gateway", "stop"])

    assert result.exit_code == 0
    assert calls == ["stop_service"]
    assert "系统服务" in result.output



def test_gateway_restart_uses_service_when_installed(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    from marneo.cli import gateway_cmd

    calls: list[str] = []
    monkeypatch.setattr(supervisor, "is_service_installed", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(supervisor, "restart_service", lambda: calls.append("restart_service"))
    monkeypatch.setattr(gateway_cmd, "_start_background_gateway", lambda *_args, **_kwargs: calls.append("spawn"))

    result = runner.invoke(app, ["gateway", "restart"])

    assert result.exit_code == 0
    assert calls == ["restart_service"]
    assert "系统服务" in result.output



def test_reference_deploy_templates_match_supervisor_entrypoint_and_logs():
    root = Path(__file__).resolve().parents[2]
    service = (root / "deploy/marneo-gateway.service").read_text(encoding="utf-8")
    plist = (root / "deploy/com.marneo.gateway.plist").read_text(encoding="utf-8")

    assert "gateway run" in service
    assert "User=%i" not in service
    assert "WantedBy=default.target" in service
    assert "%h/.marneo/logs/gateway.log" in service
    assert "gateway</string>" in plist
    assert "run</string>" in plist
    assert "/.marneo/logs/gateway.log" in plist
    assert "/tmp/marneo-gateway" not in plist



def test_service_command_failures_raise_runtime_error(monkeypatch):
    def fake_run(cmd, check=False, capture_output=False, text=False):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom")

    monkeypatch.setattr(supervisor.subprocess, "run", fake_run)

    try:
        supervisor._run_command(["systemctl", "--user", "start", "marneo-gateway"])
    except RuntimeError as exc:
        assert "service command failed" in str(exc)
        assert "boom" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("expected RuntimeError")


def test_service_command_not_found_raises_runtime_error(monkeypatch):
    def fake_run(cmd, check=False, capture_output=False, text=False):
        raise FileNotFoundError(cmd[0])

    monkeypatch.setattr(supervisor.subprocess, "run", fake_run)

    try:
        supervisor._run_command(["systemctl", "--user", "start", "marneo-gateway"])
    except RuntimeError as exc:
        assert "command not found" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("expected RuntimeError")


def test_service_status_reports_inactive_without_raising(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(sys, "platform", "linux")
    supervisor.service_path(supervisor.SupervisorKind.SYSTEMD_USER, tmp_path).parent.mkdir(parents=True)
    supervisor.service_path(supervisor.SupervisorKind.SYSTEMD_USER, tmp_path).write_text("[Service]\n", encoding="utf-8")

    def fake_run(cmd, check=False, capture_output=False, text=False):
        return subprocess.CompletedProcess(cmd, 3, stdout="inactive\n", stderr="")

    monkeypatch.setattr(supervisor.subprocess, "run", fake_run)

    status = supervisor.service_status()

    assert status["installed"] is True
    assert status["active"] is False
    assert status["returncode"] == 3


def test_service_actions_never_call_real_manager_without_runner(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    commands: list[list[str]] = []
    monkeypatch.setattr(sys, "platform", "linux")
    def fake_installed(*_args, **_kwargs) -> bool:
        return True

    monkeypatch.setattr(supervisor, "is_service_installed", fake_installed)
    def fake_run(cmd, check=False, capture_output=False, text=False):
        commands.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout="active\n", stderr="")

    monkeypatch.setattr(supervisor.subprocess, "run", fake_run)

    supervisor.start_service()
    supervisor.stop_service()
    supervisor.restart_service()
    status = supervisor.service_status()

    assert commands[:3] == [
        ["systemctl", "--user", "start", "marneo-gateway"],
        ["systemctl", "--user", "stop", "marneo-gateway"],
        ["systemctl", "--user", "restart", "marneo-gateway"],
    ]
    assert status["kind"] == supervisor.SupervisorKind.SYSTEMD_USER.value
