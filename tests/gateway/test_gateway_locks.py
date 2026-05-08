"""Tests for gateway single-instance and scoped identity locks."""
from __future__ import annotations

import json
import os

import pytest

from marneo.gateway.locks import LockUnavailable, acquire_gateway_lock, acquire_scoped_lock, release_lock


def test_gateway_lock_rejects_second_holder(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))

    first = acquire_gateway_lock()
    try:
        with pytest.raises(LockUnavailable):
            acquire_gateway_lock()
    finally:
        release_lock(first)

    second = acquire_gateway_lock()
    release_lock(second)


def test_scoped_lock_hashes_identity_and_redacts_raw_value(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    identity = "cli_a_fake_feishu_app_id_secretish"

    handle = acquire_scoped_lock(
        "feishu-app",
        identity,
        metadata={"employee": "xiaoa2hao", "channel_id": "feishu:xiaoa2hao", "app_secret": "secretish-value"},
    )
    try:
        payload = json.loads(handle.path.read_text(encoding="utf-8"))
        raw = handle.path.read_text(encoding="utf-8")

        assert payload["kind"] == "marneo-gateway-lock"
        assert payload["pid"] == os.getpid()
        assert payload["scope"] == "feishu-app"
        assert payload["metadata"]["employee"] == "xiaoa2hao"
        assert payload["metadata"]["app_secret"] == "***"
        assert payload["identity_hash"]
        assert identity not in raw
        assert "secretish-value" not in raw
    finally:
        release_lock(handle)


def test_scoped_lock_rejects_same_identity_but_allows_different(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))

    first = acquire_scoped_lock("feishu-app", "app-one")
    other = acquire_scoped_lock("feishu-app", "app-two")
    try:
        with pytest.raises(LockUnavailable):
            acquire_scoped_lock("feishu-app", "app-one")
    finally:
        release_lock(first)
        release_lock(other)

    reacquired = acquire_scoped_lock("feishu-app", "app-one")
    release_lock(reacquired)
