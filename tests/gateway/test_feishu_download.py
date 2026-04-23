# tests/gateway/test_feishu_download.py
import pytest
from unittest.mock import MagicMock, patch
from marneo.gateway.adapters.feishu import FeishuChannelAdapter


def _make_adapter():
    manager = MagicMock()
    adapter = FeishuChannelAdapter(manager, employee_name="test")
    adapter._app_id = "app1"
    adapter._app_secret = "secret1"
    adapter._domain = "feishu"
    return adapter


@pytest.mark.asyncio
async def test_download_resource_returns_bytes_and_media_type():
    """_download_feishu_resource returns (bytes, media_type, filename) on success."""
    adapter = _make_adapter()

    mock_file = MagicMock()
    mock_file.getvalue.return_value = b"fake-image-bytes"

    mock_response = MagicMock()
    mock_response.success.return_value = True
    mock_response.file = mock_file
    mock_response.file_name = "photo.jpg"
    mock_response.raw = MagicMock()
    mock_response.raw.headers = {"Content-Type": "image/jpeg"}

    mock_client = MagicMock()
    mock_client.im.v1.message_resource.get.return_value = mock_response

    with patch.object(adapter, "_build_lark_client", return_value=mock_client):
        data, media_type, filename = await adapter._download_feishu_resource(
            message_id="msg1", file_key="fk1", resource_type="image"
        )

    assert data == b"fake-image-bytes"
    assert "image" in media_type
    assert filename == "photo.jpg"


@pytest.mark.asyncio
async def test_download_resource_returns_empty_on_api_failure():
    adapter = _make_adapter()

    mock_response = MagicMock()
    mock_response.success.return_value = False
    mock_response.code = 403
    mock_response.msg = "forbidden"

    mock_client = MagicMock()
    mock_client.im.v1.message_resource.get.return_value = mock_response

    with patch.object(adapter, "_build_lark_client", return_value=mock_client):
        data, media_type, filename = await adapter._download_feishu_resource(
            message_id="msg1", file_key="fk1", resource_type="file"
        )

    assert data == b""
    assert media_type == ""
    assert filename == ""


@pytest.mark.asyncio
async def test_download_resource_returns_empty_when_missing_app_id():
    adapter = _make_adapter()
    adapter._app_id = ""  # not configured

    data, media_type, filename = await adapter._download_feishu_resource(
        message_id="msg1", file_key="fk1", resource_type="image"
    )

    assert data == b""
