"""Tests for gateway CLI lifecycle behavior."""
from __future__ import annotations

import os
import signal
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from marneo.cli.app import app
from marneo.cli import gateway_cmd
from marneo.gateway import status as gateway_status

runner = CliRunner()


def test_gateway_stop_waits_for_process_exit_before_success(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    gateway_status.write_pid_file(424242)
    monkeypatch.setattr(gateway_status, "is_process_alive", lambda pid: pid == 424242)
    monkeypatch.setattr(gateway_cmd, "_wait_for_pid_exit", lambda pid, timeout=10.0: False)
    killed = []
    monkeypatch.setattr(gateway_cmd.os, "kill", lambda pid, sig: killed.append((pid, sig)))

    result = runner.invoke(app, ["gateway", "stop"])

    assert result.exit_code == 1
    assert killed == [(424242, signal.SIGTERM)]
    assert "停止超时" in result.output
    assert gateway_status.get_pid_path().exists()


def test_gateway_restart_does_not_spawn_new_process_when_old_pid_survives(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    gateway_status.write_pid_file(555555)
    monkeypatch.setattr(gateway_status, "is_process_alive", lambda pid: pid == 555555)
    monkeypatch.setattr(gateway_cmd, "_wait_for_pid_exit", lambda pid, timeout=10.0: False)
    monkeypatch.setattr(gateway_cmd.os, "kill", lambda pid, sig: None)
    spawned = []
    monkeypatch.setattr(gateway_cmd, "_spawn_gateway_process", lambda: spawned.append(True))

    result = runner.invoke(app, ["gateway", "restart"])

    assert result.exit_code == 1
    assert spawned == []
    assert "旧进程未退出" in result.output


def test_gateway_start_reports_child_failure(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    proc = SimpleNamespace(pid=777777, poll=lambda: 1)
    monkeypatch.setattr(gateway_cmd, "_spawn_gateway_process", lambda: proc)
    monkeypatch.setattr(gateway_cmd, "_wait_for_gateway_start", lambda proc, timeout=5.0: False)

    result = runner.invoke(app, ["gateway", "start"])

    assert result.exit_code == 1
    assert "启动失败" in result.output


def test_gateway_start_waits_for_running_status_after_pid_file(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    gateway_status.write_pid_file(os.getpid())
    gateway_status.write_runtime_status(gateway_state="starting")
    proc = SimpleNamespace(pid=os.getpid(), poll=lambda: None)

    assert gateway_cmd._wait_for_gateway_start(proc, timeout=0.01) is False

    gateway_status.write_runtime_status(gateway_state="running")
    assert gateway_cmd._wait_for_gateway_start(proc, timeout=0.01) is True


def test_gateway_stop_timeout_preserves_target_pid_in_status(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    gateway_status.write_pid_file(424242)
    monkeypatch.setattr(gateway_cmd, "_wait_for_pid_exit", lambda pid, timeout=10.0: False)
    monkeypatch.setattr(gateway_cmd.os, "kill", lambda pid, sig: None)

    assert gateway_cmd._terminate_gateway_pid(424242, restart_requested=False) is False

    state = gateway_status.read_runtime_status()
    assert state is not None
    assert state["pid"] == 424242
    assert state["gateway_state"] == "stopping"


@pytest.mark.parametrize("command", [["gateway", "start"], ["gateway", "restart"]])
def test_gateway_start_commands_wait_until_child_writes_pid(monkeypatch, tmp_path, command):
    monkeypatch.setenv("HOME", str(tmp_path))
    if command[-1] == "restart":
        monkeypatch.setattr(gateway_cmd, "_read_pid", lambda: None)
    proc = SimpleNamespace(pid=888888, poll=lambda: None)
    monkeypatch.setattr(gateway_cmd, "_spawn_gateway_process", lambda: proc)
    monkeypatch.setattr(gateway_cmd, "_wait_for_gateway_start", lambda proc, timeout=5.0: True)

    result = runner.invoke(app, command)

    assert result.exit_code == 0
    assert "888888" in result.output
