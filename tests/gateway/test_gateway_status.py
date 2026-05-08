"""Tests for gateway runtime status files."""
from __future__ import annotations

import json
import os

from marneo.gateway import status as gateway_status


def test_gateway_status_paths_live_under_marneo_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))

    assert gateway_status.get_pid_path() == tmp_path / ".marneo" / "gateway.pid"
    assert gateway_status.get_runtime_status_path() == tmp_path / ".marneo" / "gateway_state.json"
    assert gateway_status.get_gateway_log_path() == tmp_path / ".marneo" / "logs" / "gateway.log"


def test_pid_file_round_trip_and_stale_cleanup(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))

    gateway_status.write_pid_file(os.getpid())
    assert gateway_status.read_pid_file() == os.getpid()

    gateway_status.get_pid_path().write_text("999999999", encoding="utf-8")
    assert gateway_status.read_pid_file() is None
    assert not gateway_status.get_pid_path().exists()


def test_runtime_status_initializes_and_merges_fields(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))

    gateway_status.write_runtime_status(gateway_state="starting", active_agents=0)
    first = gateway_status.read_runtime_status()

    assert first is not None
    assert first["kind"] == "marneo-gateway"
    assert first["pid"] == os.getpid()
    assert first["gateway_state"] == "starting"
    assert first["active_agents"] == 0
    assert first["channels"] == {}
    assert "updated_at" in first

    gateway_status.write_runtime_status(gateway_state="running", restart_requested=True)
    second = gateway_status.read_runtime_status()

    assert second is not None
    assert second["gateway_state"] == "running"
    assert second["restart_requested"] is True
    assert second["active_agents"] == 0
    assert second["pid"] == os.getpid()


def test_update_channel_status_preserves_other_channels(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))

    gateway_status.update_channel_status("feishu:xiaoa2hao", {"state": "connected", "employee": "xiaoa2hao"})
    gateway_status.update_channel_status("feishu:xiaoa3hao", {"state": "failed", "employee": "xiaoa3hao"})

    payload = gateway_status.read_runtime_status()
    assert payload is not None
    assert payload["channels"]["feishu:xiaoa2hao"]["state"] == "connected"
    assert payload["channels"]["feishu:xiaoa3hao"]["state"] == "failed"
    assert payload["channels"]["feishu:xiaoa2hao"]["channel_id"] == "feishu:xiaoa2hao"


def test_runtime_status_recovers_from_corrupt_json(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    path = gateway_status.get_runtime_status_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not-json", encoding="utf-8")

    gateway_status.write_runtime_status(gateway_state="running")

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["gateway_state"] == "running"
    assert payload["kind"] == "marneo-gateway"


def test_redact_secret_text_masks_common_credentials():
    text = (
        "app_secret=abc12345678901234567890 "
        "Authorization: Bearer verylongbearertoken123456789 "
        "ticket=ws-ticket-secret-value access_key=access-key-secret-value"
    )
    structured = {
        "Authorization": "Bearer structuredbearertoken123456789",
        "nested": {"auth_header": "Bearer lowerstructuredtoken123456789"},
    }

    redacted = gateway_status.redact_secret_text(text)
    structured_redacted = gateway_status._redact_value(structured)
    gateway_status.write_runtime_status(
        error_message=(
            "upstream failed with Authorization=Bearer equalsbearertoken123456789 "
            "headers={'Authorization': 'Bearer dictbearertoken123456789', "
            "'access_token': 'jsonaccesstoken123456789', "
            "\"app_secret\": \"jsonappsecret123456789\", "
            "bot_token: bottoken123456789012}"
        )
    )
    persisted = gateway_status.read_runtime_status()

    assert "abc12345678901234567890" not in redacted
    assert "verylongbearertoken123456789" not in redacted
    assert "ws-ticket-secret-value" not in redacted
    assert "access-key-secret-value" not in redacted
    assert structured_redacted["Authorization"] == "***"
    assert structured_redacted["nested"]["auth_header"] == "***"
    assert persisted is not None
    assert "equalsbearertoken123456789" not in persisted["error_message"]
    assert "dictbearertoken123456789" not in persisted["error_message"]
    assert "jsonaccesstoken123456789" not in persisted["error_message"]
    assert "jsonappsecret123456789" not in persisted["error_message"]
    assert "bottoken123456789012" not in persisted["error_message"]
    assert "***" in redacted
