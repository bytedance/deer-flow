"""Regression anchors for outbound IM attachment file IO.

Feishu, Telegram, and WeCom send attachments from async channel handlers. File
open/read/hash work must run off the event loop; otherwise a large outbound
artifact stalls every channel and Gateway coroutine on that worker.
"""

from __future__ import annotations

import asyncio
import base64
import builtins
import hashlib
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.channels.feishu import FeishuChannel
from app.channels.message_bus import MessageBus, OutboundMessage, ResolvedAttachment
from app.channels.telegram import TelegramChannel
from app.channels.wecom import WeComChannel

pytestmark = pytest.mark.asyncio


def _attachment(path: Path, *, is_image: bool) -> ResolvedAttachment:
    return ResolvedAttachment(
        virtual_path=f"/mnt/user-data/outputs/{path.name}",
        actual_path=path,
        filename=path.name,
        mime_type="image/png" if is_image else "application/octet-stream",
        size=path.stat().st_size,
        is_image=is_image,
    )


def _outbound(channel_name: str) -> OutboundMessage:
    return OutboundMessage(
        channel_name=channel_name,
        chat_id="123",
        thread_id="thread-1",
        text="attachment",
    )


def _builder(*, captured_file: dict[str, object] | None = None) -> MagicMock:
    builder = MagicMock()
    for method_name in ("request_body", "image_type", "file_type", "file_name"):
        getattr(builder, method_name).return_value = builder
    if captured_file is not None:

        def _capture(file_obj):
            captured_file["file"] = file_obj
            return builder

        builder.image.side_effect = _capture
        builder.file.side_effect = _capture
    builder.build.return_value = object()
    return builder


async def test_feishu_outbound_uploads_do_not_block_event_loop(tmp_path: Path, monkeypatch) -> None:
    image_path = tmp_path / "chart.png"
    file_path = tmp_path / "report.pdf"
    await asyncio.to_thread(image_path.write_bytes, b"image-bytes")
    await asyncio.to_thread(file_path.write_bytes, b"file-bytes")

    channel = FeishuChannel(MessageBus(), {})
    channel._api_client = MagicMock()

    real_open = builtins.open
    opened_on_threads: list[int] = []
    tracked_paths = {str(image_path), str(file_path)}

    def _tracked_open(file, *args, **kwargs):
        if str(file) in tracked_paths:
            opened_on_threads.append(threading.get_ident())
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", _tracked_open)

    image_capture: dict[str, object] = {}
    channel._CreateImageRequest = MagicMock()
    channel._CreateImageRequest.builder.return_value = _builder()
    channel._CreateImageRequestBody = MagicMock()
    channel._CreateImageRequestBody.builder.return_value = _builder(captured_file=image_capture)

    image_response = MagicMock()
    image_response.success.return_value = True
    image_response.data.image_key = "image-key"
    image_worker_thread: int | None = None

    def _create_image(_request):
        nonlocal image_worker_thread
        image_worker_thread = threading.get_ident()
        file_obj = image_capture["file"]
        assert not file_obj.closed
        assert file_obj.read() == b"image-bytes"
        return image_response

    channel._api_client.im.v1.image.create.side_effect = _create_image

    file_capture: dict[str, object] = {}
    channel._CreateFileRequest = MagicMock()
    channel._CreateFileRequest.builder.return_value = _builder()
    channel._CreateFileRequestBody = MagicMock()
    channel._CreateFileRequestBody.builder.return_value = _builder(captured_file=file_capture)

    file_response = MagicMock()
    file_response.success.return_value = True
    file_response.data.file_key = "file-key"
    file_worker_thread: int | None = None

    def _create_file(_request):
        nonlocal file_worker_thread
        file_worker_thread = threading.get_ident()
        file_obj = file_capture["file"]
        assert not file_obj.closed
        assert file_obj.read() == b"file-bytes"
        return file_response

    channel._api_client.im.v1.file.create.side_effect = _create_file

    event_loop_thread = threading.get_ident()
    assert await channel._upload_image(image_path) == "image-key"
    assert await channel._upload_file(file_path, file_path.name) == "file-key"
    assert len(opened_on_threads) == 2
    assert all(thread_id != event_loop_thread for thread_id in opened_on_threads)
    assert image_worker_thread != event_loop_thread
    assert file_worker_thread != event_loop_thread


@pytest.mark.parametrize("is_image", [False, True])
async def test_telegram_outbound_upload_does_not_block_event_loop(tmp_path: Path, is_image: bool) -> None:
    path = tmp_path / ("chart.png" if is_image else "report.bin")
    payload = b"telegram-payload"
    await asyncio.to_thread(path.write_bytes, payload)

    sent_file = None

    class _Bot:
        async def send_document(self, **kwargs):
            nonlocal sent_file
            sent_file = kwargs["document"]
            return SimpleNamespace(message_id=7)

        async def send_photo(self, **kwargs):
            nonlocal sent_file
            sent_file = kwargs["photo"]
            if hasattr(sent_file, "read"):
                sent_file.read()
            return SimpleNamespace(message_id=7)

    channel = TelegramChannel(MessageBus(), {})
    channel._application = SimpleNamespace(bot=_Bot())

    assert await channel.send_file(_outbound("telegram"), _attachment(path, is_image=is_image))
    assert sent_file.input_file_content == payload
    assert sent_file.filename == path.name


async def test_wecom_outbound_upload_does_not_block_event_loop(tmp_path: Path) -> None:
    path = tmp_path / "report.bin"
    payload = b"x" * (512 * 1024 + 17)
    await asyncio.to_thread(path.write_bytes, payload)

    channel = WeComChannel(MessageBus(), {})
    channel._ws_client = object()
    channel._send_ws_upload_command = AsyncMock(
        side_effect=[
            {"body": {"upload_id": "upload-1"}},
            {"body": {}},
            {"body": {}},
            {"body": {"media_id": "media-1"}},
        ]
    )

    result = await channel._upload_media_ws(
        media_type="file",
        filename=path.name,
        path=str(path),
        size=len(payload),
    )

    assert result == "media-1"
    calls = channel._send_ws_upload_command.await_args_list
    assert calls[0].args[1]["md5"] == hashlib.md5(payload).hexdigest()
    encoded_chunks = [call.args[1]["base64_data"] for call in calls[1:-1]]
    assert b"".join(base64.b64decode(chunk) for chunk in encoded_chunks) == payload
