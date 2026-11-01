"""Feishu image/file uploads must fail with a diagnosable error.

``_upload_image``/``_upload_file`` used to read ``response.data.image_key`` /
``response.data.file_key`` straight after ``success()``. A success response
without ``data`` surfaced as a bare ``AttributeError``, an empty key was handed
on to ``message.reply``/``message.create`` as ``{"image_key": ""}``, and the
business-failure error omitted the ``log_id`` that every other Feishu API error
in the channel carries.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.channels.feishu import FeishuChannel
from app.channels.message_bus import MessageBus


def _channel() -> FeishuChannel:
    channel = FeishuChannel(MessageBus(), config={})
    channel._api_client = MagicMock()
    return channel


def _response(*, success: bool, data=None, log_id: str = "log-upload-1"):
    response = MagicMock()
    response.success.return_value = success
    response.code = 0 if success else 99991400
    response.msg = "ok" if success else "param invalid"
    response.data = data
    response.get_log_id.return_value = log_id
    return response


def _upload(channel: FeishuChannel, kind: str, tmp_path):
    path = tmp_path / ("image.png" if kind == "image" else "report.pdf")
    path.write_bytes(b"data")
    if kind == "image":
        return asyncio.run(channel._upload_image(path))
    return asyncio.run(channel._upload_file(path, path.name))


def _patch_sync_upload(channel: FeishuChannel, kind: str, response) -> None:
    if kind == "image":
        channel._upload_image_sync = MagicMock(return_value=response)
    else:
        channel._upload_file_sync = MagicMock(return_value=response)


@pytest.mark.parametrize("kind", ["image", "file"])
def test_upload_business_failure_includes_log_id(kind, tmp_path):
    channel = _channel()
    _patch_sync_upload(channel, kind, _response(success=False, log_id="log-upload-fail"))

    with pytest.raises(RuntimeError, match="log_id=log-upload-fail"):
        _upload(channel, kind, tmp_path)


@pytest.mark.parametrize("kind", ["image", "file"])
@pytest.mark.parametrize(
    "data",
    [
        None,
        SimpleNamespace(image_key=None, file_key=None),
        SimpleNamespace(image_key="", file_key=""),
        SimpleNamespace(image_key=123, file_key=456),
    ],
    ids=["no-data", "none-key", "empty-key", "non-str-key"],
)
def test_upload_success_without_key_raises_runtime_error(kind, data, tmp_path):
    channel = _channel()
    _patch_sync_upload(channel, kind, _response(success=True, data=data, log_id="log-no-key"))

    with pytest.raises(RuntimeError, match=f"no {kind}_key.*log_id=log-no-key"):
        _upload(channel, kind, tmp_path)


@pytest.mark.parametrize("kind", ["image", "file"])
def test_upload_success_returns_key(kind, tmp_path):
    channel = _channel()
    data = SimpleNamespace(image_key="img-key-1", file_key="file-key-1")
    _patch_sync_upload(channel, kind, _response(success=True, data=data))

    expected = "img-key-1" if kind == "image" else "file-key-1"
    assert _upload(channel, kind, tmp_path) == expected
