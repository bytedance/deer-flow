"""Telegram photo rejection recovery through real SDK request serialization.

The offline transport models documented photo geometry limits. It is not a
live Telegram reproduction, and these tests never contact the platform.
"""

from __future__ import annotations

import asyncio
import json
import struct
import zlib
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from telegram import Bot
from telegram.error import NetworkError, TimedOut
from telegram.request import BaseRequest

from app.channels.message_bus import MessageBus, OutboundMessage, ResolvedAttachment
from app.channels.telegram import TelegramChannel


def _png(width: int, height: int) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    rows = (b"\0" + bytes((width + 7) // 8)) * height
    header = struct.pack(">IIBBBBB", width, height, 1, 0, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


class _PhotoRequest(BaseRequest):
    def __init__(self):
        self.calls = []
        self.errors = {}
        self.blocked_endpoint = None
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    @property
    def read_timeout(self):
        return 5

    async def initialize(self):
        pass

    async def shutdown(self):
        pass

    async def do_request(self, url, method, request_data=None, **kwargs):
        endpoint = url.rsplit("/", 1)[-1]
        params = request_data.parameters if request_data else {}
        if endpoint == "getMe":
            result = {"id": 1, "is_bot": True, "first_name": "Offline", "username": "offline_bot"}
        else:
            uploads = request_data.multipart_data
            self.calls.append((endpoint, params, uploads))
            if endpoint == self.blocked_endpoint:
                self.started.set()
                await self.release.wait()
            error = self.errors.get(endpoint)
            if isinstance(error, Exception):
                raise error
            if error:
                status, description = error
                return status, json.dumps({"ok": False, "error_code": status, "description": description, "parameters": {"retry_after": 30} if status == 429 else {}}).encode()
            if endpoint == "sendPhoto":
                data = next(iter(uploads.values()))[1]
                width, height = struct.unpack(">II", data[16:24])
                if width + height > 10000 or max(width, height) > 20 * min(width, height):
                    return 400, b'{"ok": false, "error_code": 400, "description": "Bad Request: PHOTO_INVALID_DIMENSIONS"}'
            result = {"message_id": 100 + len(self.calls), "date": 0, "chat": {"id": params["chat_id"], "type": "private" if params["chat_id"] > 0 else "supergroup"}}
        return 200, json.dumps({"ok": True, "result": result}).encode()


@pytest_asyncio.fixture
async def channel():
    request = _PhotoRequest()
    async with Bot("123:offline-test-only", request=request, get_updates_request=request) as bot:
        instance = TelegramChannel(MessageBus(), {"bot_token": "123:offline-test-only"})
        instance._application = SimpleNamespace(bot=bot)
        instance._remember_reply_thread = AsyncMock(return_value=True)
        yield instance, request


def _attachment(tmp_path, width=64, height=64):
    path = tmp_path / "original chart.png"
    data = _png(width, height)
    path.write_bytes(data)
    return ResolvedAttachment("/mnt/user-data/outputs/" + path.name, path, path.name, "image/png", len(data), True)


def _message(chat_id="12345"):
    return OutboundMessage(channel_name="telegram", chat_id=chat_id, thread_id="thread", text="Complete answer")


def _endpoints(request):
    return [call[0] for call in request.calls]


@pytest.mark.asyncio
@pytest.mark.parametrize("chat_id", ["12345", "-12345"])
@pytest.mark.parametrize("dimensions", [(100, 3000), (6000, 5000)])
async def test_rejected_photo_delivers_original_document_and_preserves_reply(channel, tmp_path, chat_id, dimensions):
    instance, request = channel
    attachment = _attachment(tmp_path, *dimensions)
    original = attachment.actual_path.read_bytes()
    instance._last_bot_message[chat_id] = 42
    message = _message(chat_id)

    assert await instance.send_file(message, attachment)

    assert _endpoints(request) == ["sendPhoto", "sendDocument"]
    photo, document = request.calls
    assert photo[2]["photo"] == document[2]["document"]
    assert document[2]["document"][:2] == (attachment.filename, original)
    assert photo[1]["chat_id"] == document[1]["chat_id"] == int(chat_id)
    assert photo[1]["reply_parameters"] == document[1]["reply_parameters"]
    reply = document[1]["reply_parameters"]
    assert reply["message_id"] == 42
    assert bool(reply.get("allow_sending_without_reply")) is (int(chat_id) > 0)
    assert instance._last_bot_message[chat_id] == 102
    instance._remember_reply_thread.assert_awaited_once_with(message, 102)


@pytest.mark.asyncio
@pytest.mark.parametrize("description", ["Bad Request: IMAGE_PROCESS_FAILED", "Bad Request: image_process_failed", "Bad Request: photo_invalid_dimensions"])
async def test_explicit_media_rejections_fall_back_once(channel, tmp_path, description):
    instance, request = channel
    request.errors["sendPhoto"] = (400, description)
    assert await instance.send_file(_message(), _attachment(tmp_path))
    assert _endpoints(request) == ["sendPhoto", "sendDocument"]
    assert "reply_parameters" not in request.calls[-1][1]


@pytest.mark.asyncio
@pytest.mark.parametrize("is_image,size,endpoint", [(True, 10 * 1024 * 1024, "sendPhoto"), (True, 10 * 1024 * 1024 + 1, "sendDocument"), (False, 72, "sendDocument"), (False, 50 * 1024 * 1024, "sendDocument")])
async def test_existing_photo_and_document_selection(channel, tmp_path, is_image, size, endpoint):
    instance, request = channel
    # Metadata sizes exercise the existing routing boundaries without large files.
    attachment = replace(_attachment(tmp_path), is_image=is_image, size=size)
    assert await instance.send_file(_message(), attachment)
    assert _endpoints(request) == [endpoint]
    instance._remember_reply_thread.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        (400, "Bad Request: message to be replied not found"),
        (400, "Bad Request: unknown photo failure"),
        (400, "Bad Request: PHOTO_INVALID_DIMENSIONS extra detail"),
        (403, "Forbidden: bot was blocked by the user"),
        (403, "PHOTO_INVALID_DIMENSIONS"),
        (429, "Too Many Requests"),
        NetworkError("PHOTO_INVALID_DIMENSIONS"),
        TimedOut(),
    ],
)
async def test_unrelated_or_uncertain_photo_errors_do_not_resend(channel, tmp_path, error):
    instance, request = channel
    request.errors["sendPhoto"] = error
    instance._last_bot_message["12345"] = 42
    assert not await instance.send_file(_message(), _attachment(tmp_path))
    assert _endpoints(request) == ["sendPhoto"]
    assert instance._last_bot_message["12345"] == 42
    instance._remember_reply_thread.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [(400, "Bad Request: PHOTO_INVALID_DIMENSIONS"), (403, "Forbidden: bot was blocked by the user"), (429, "Too Many Requests"), NetworkError("offline connection failed")])
async def test_document_fallback_failure_is_not_retried_or_registered(channel, tmp_path, error):
    instance, request = channel
    request.errors["sendDocument"] = error
    instance._last_bot_message["12345"] = 42
    assert not await instance.send_file(_message(), _attachment(tmp_path, 100, 3000))
    assert _endpoints(request) == ["sendPhoto", "sendDocument"]
    assert instance._last_bot_message["12345"] == 42
    instance._remember_reply_thread.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["sendPhoto", "sendDocument"])
async def test_cancellation_during_send_propagates_without_registration(channel, tmp_path, endpoint):
    instance, request = channel
    request.blocked_endpoint = endpoint
    attachment = _attachment(tmp_path, 100, 3000)
    instance._last_bot_message["12345"] = 42
    task = asyncio.create_task(instance.send_file(_message(), attachment))
    try:
        await asyncio.wait_for(request.started.wait(), timeout=5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert _endpoints(request) == (["sendPhoto"] if endpoint == "sendPhoto" else ["sendPhoto", "sendDocument"])
    assert instance._last_bot_message["12345"] == 42
    instance._remember_reply_thread.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_file_and_oversized_attachment_do_not_send(channel, tmp_path):
    instance, request = channel
    attachment = _attachment(tmp_path)
    assert not await instance.send_file(_message(), replace(attachment, size=50 * 1024 * 1024 + 1))
    attachment.actual_path.unlink()
    assert not await instance.send_file(_message(), attachment)
    assert not request.calls
    instance._remember_reply_thread.assert_not_awaited()


@pytest.mark.asyncio
async def test_mixed_attachment_batch_continues_without_resending_success(channel, tmp_path):
    instance, request = channel
    wide = _attachment(tmp_path, 100, 3000)
    ordinary_path = tmp_path / "notes.txt"
    ordinary_path.write_bytes(b"notes")
    ordinary = ResolvedAttachment("/mnt/user-data/outputs/notes.txt", ordinary_path, "notes.txt", "text/plain", 5, False)
    message = replace(_message(), attachments=[wide, ordinary])
    assert await instance._send_attachments(message) == []
    assert _endpoints(request) == ["sendPhoto", "sendDocument", "sendDocument"]
    assert request.calls[-1][2]["document"][:2] == ("notes.txt", b"notes")
    assert request.calls[-1][1]["reply_parameters"]["message_id"] == 102
    assert instance._remember_reply_thread.await_count == 2


@pytest.mark.asyncio
async def test_fallback_binds_delivered_group_document_to_original_thread(channel, tmp_path):
    instance, request = channel
    instance._remember_reply_thread = TelegramChannel._remember_reply_thread.__get__(instance)
    store = SimpleNamespace(claim_thread_id=AsyncMock())
    instance.config["channel_store"] = store
    instance._last_bot_message["-12345"] = 42
    message = replace(_message("-12345"), thread_ts="17")

    assert await instance.send_file(message, _attachment(tmp_path, 100, 3000))

    assert _endpoints(request) == ["sendPhoto", "sendDocument"]
    assert store.claim_thread_id.await_count == 2
    claims = store.claim_thread_id.await_args_list
    assert {entry.args for entry in claims} == {("telegram", "-12345", "thread")}
    assert {entry.kwargs["topic_id"] for entry in claims} == {"17", "102"}


@pytest.mark.asyncio
async def test_unavailable_bot_and_invalid_chat_do_not_send(channel, tmp_path):
    instance, request = channel
    attachment = _attachment(tmp_path)
    assert not await instance.send_file(_message("not-a-chat-id"), attachment)
    instance._application = None
    assert not await instance.send_file(_message(), attachment)
    assert not request.calls
    instance._remember_reply_thread.assert_not_awaited()
