# tests/tools/test_feishu_send_file.py
"""Tests for the feishu_send_file tool — file/image upload to Feishu chats."""
import json
import pytest
from unittest.mock import patch, MagicMock

from marneo.tools.core.feishu_tools import (
    feishu_send_file,
    _is_image_file,
    _MAX_FILE_BYTES,
    _MAX_IMAGE_BYTES,
)
from marneo.tools.registry import registry


# ── Registration ─────────────────────────────────────────────────────────────

def test_tool_registered():
    """feishu_send_file must be present in the global tool registry."""
    entry = registry.get_entry("feishu_send_file")
    assert entry is not None
    assert entry.name == "feishu_send_file"
    assert entry.handler is feishu_send_file


# ── Input validation ─────────────────────────────────────────────────────────

def test_file_not_found(tmp_path):
    """Returns error for a nonexistent file path."""
    nonexistent = str(tmp_path / "no_such_file.txt")
    result = json.loads(feishu_send_file({
        "file_path": nonexistent,
        "chat_id": "oc_test123",
    }))
    assert "error" in result
    assert "not found" in result["error"].lower() or nonexistent in result["error"]


def test_missing_file_path():
    """Returns error when file_path is empty."""
    result = json.loads(feishu_send_file({
        "file_path": "",
        "chat_id": "oc_test123",
    }))
    assert "error" in result


def test_missing_chat_id(tmp_path):
    """Returns error when chat_id is empty."""
    f = tmp_path / "test.txt"
    f.write_text("hello")
    result = json.loads(feishu_send_file({
        "file_path": str(f),
        "chat_id": "",
    }))
    assert "error" in result


# ── Size limits ──────────────────────────────────────────────────────────────

def test_file_too_large(tmp_path):
    """Returns error for a file exceeding the 20 MB limit."""
    big = tmp_path / "huge.pdf"
    # Write just over the limit (20 MB + 1 byte)
    big.write_bytes(b"\x00" * (_MAX_FILE_BYTES + 1))
    result = json.loads(feishu_send_file({
        "file_path": str(big),
        "chat_id": "oc_test123",
    }))
    assert "error" in result
    assert "too large" in result["error"].lower()


def test_image_too_large(tmp_path):
    """Returns error for an image exceeding the 10 MB limit."""
    big_img = tmp_path / "huge.png"
    big_img.write_bytes(b"\x00" * (_MAX_IMAGE_BYTES + 1))
    result = json.loads(feishu_send_file({
        "file_path": str(big_img),
        "chat_id": "oc_test123",
    }))
    assert "error" in result
    assert "too large" in result["error"].lower()


def test_file_within_limit_passes_size_check(tmp_path):
    """A file at exactly 20 MB should NOT be rejected for size."""
    exact = tmp_path / "exact.pdf"
    exact.write_bytes(b"\x00" * _MAX_FILE_BYTES)
    # Should pass size validation and fail only on missing credentials
    with patch(
        "marneo.tools.core.feishu_tools._get_feishu_credentials",
        side_effect=ValueError("No Feishu credentials configured"),
    ):
        result = json.loads(feishu_send_file({
            "file_path": str(exact),
            "chat_id": "oc_test123",
        }))
    # Error should be about credentials, NOT about file size
    assert "error" in result
    assert "credentials" in result["error"].lower() or "feishu" in result["error"].lower()


# ── Image vs file type detection ─────────────────────────────────────────────

def test_detect_image_type_jpg(tmp_path):
    """jpg and png are detected as image uploads."""
    for ext in ("jpg", "jpeg", "png", "gif", "webp"):
        f = tmp_path / f"photo.{ext}"
        f.write_bytes(b"\x00" * 100)
        assert _is_image_file(str(f)) is True, f".{ext} should be detected as image"


def test_detect_file_type(tmp_path):
    """pdf and docx should NOT be detected as image upload."""
    for ext in ("pdf", "docx", "xlsx", "zip", "csv"):
        f = tmp_path / f"document.{ext}"
        f.write_bytes(b"\x00" * 100)
        assert _is_image_file(str(f)) is False, f".{ext} should NOT be detected as image"


def test_detect_image_case_insensitive(tmp_path):
    """Image detection is case-insensitive (.PNG, .JPG, etc.)."""
    f = tmp_path / "PHOTO.PNG"
    f.write_bytes(b"\x00" * 100)
    assert _is_image_file(str(f)) is True


# ── Credential check ────────────────────────────────────────────────────────

def test_no_credentials_returns_error(tmp_path):
    """When no Feishu credentials are configured, returns a clear error."""
    f = tmp_path / "test.txt"
    f.write_text("hello")
    with patch(
        "marneo.tools.core.feishu_tools._get_feishu_credentials",
        side_effect=ValueError("No Feishu credentials configured"),
    ):
        result = json.loads(feishu_send_file({
            "file_path": str(f),
            "chat_id": "oc_test123",
        }))
    assert "error" in result
    assert "credentials" in result["error"].lower() or "configured" in result["error"].lower()
