"""Outbound limits apply to bytes read, even when resolved files change."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.channels.message_bus import MessageBus, OutboundMessage, ResolvedAttachment
from app.channels.wechat import WechatChannel, _decrypt_aes_128_ecb


@pytest.mark.parametrize("is_image", [True, False], ids=["image", "file"])
@pytest.mark.parametrize(
    ("initial_size", "growth", "limit", "expected"),
    [
        (64, 0, 64, True),
        (32, 16, 64, True),
        (32, 96, 64, False),
        (65, 0, 64, False),
        (32, 96, 0, True),
        (32, 96, -1, True),
    ],
    ids=["exact-limit", "growth-within-limit", "growth-over-limit", "already-over-limit", "disabled-zero", "disabled-negative"],
)
def test_send_attachment_bounds_reads(monkeypatch, tmp_path, is_image, initial_size, growth, limit, expected):
    path = tmp_path / ("chart.png" if is_image else "report.txt")
    path.write_bytes(b"a" * initial_size)
    attachment = ResolvedAttachment(
        virtual_path=f"/mnt/user-data/outputs/{path.name}",
        actual_path=path,
        filename=path.name,
        mime_type="image/png" if is_image else "text/plain",
        size=path.stat().st_size,
        is_image=is_image,
    )
    real_open = Path.open
    requests: list[int] = []
    lengths: list[int] = []

    class RecordingReader:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def read(self, size=-1):
            requests.append(size)
            data = self.stream.read(size)
            lengths.append(len(data))
            return data

    def open_with_growth(self, mode="r", *args, **kwargs):
        if self == path and mode == "rb":
            if growth:
                with real_open(path, "ab") as writer:
                    writer.write(b"b" * growth)
            return RecordingReader(real_open(self, mode, *args, **kwargs))
        return real_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_with_growth)
    channel = WechatChannel(bus=MessageBus(), config={"bot_token": "test-token", "max_outbound_image_bytes": limit, "max_outbound_file_bytes": limit})
    channel._context_tokens_by_chat["wx-user"] = "test-context"
    channel._request_json = AsyncMock(side_effect=[{"ret": 0, "upload_full_url": "https://cdn.example/upload", "upload_param": "test-param"}, {"ret": 0}])
    channel._upload_cdn_bytes = AsyncMock(return_value="test-param")
    message = OutboundMessage(channel_name="wechat", chat_id="wx-user", thread_id="test-thread", text="")

    assert asyncio.run(channel.send_file(message, attachment)) is expected
    if limit > 0 and initial_size > limit:
        assert requests == []
    else:
        assert len(requests) == 1
        if limit > 0:
            assert 0 < requests[0] <= limit + 1
            assert lengths == [min(initial_size + growth, limit + 1)]
        else:
            assert lengths == [initial_size + growth]

    if expected:
        assert channel._request_json.await_count == 2
        channel._upload_cdn_bytes.assert_awaited_once()
        upload_request = channel._request_json.call_args_list[0].args[1]
        encrypted = channel._upload_cdn_bytes.call_args.args[1]
        plaintext = _decrypt_aes_128_ecb(encrypted, bytes.fromhex(upload_request["aeskey"]))
        assert plaintext == b"a" * initial_size + b"b" * growth
    else:
        channel._request_json.assert_not_awaited()
        channel._upload_cdn_bytes.assert_not_awaited()


@pytest.mark.parametrize("is_image", [True, False], ids=["image", "file"])
def test_send_attachment_handles_missing_file(tmp_path, is_image):
    path = tmp_path / ("missing.png" if is_image else "missing.txt")
    channel = WechatChannel(bus=MessageBus(), config={"bot_token": "test-token"})
    channel._context_tokens_by_chat["wx-user"] = "test-context"
    channel._request_json = AsyncMock()
    attachment = ResolvedAttachment(
        virtual_path=f"/mnt/user-data/outputs/{path.name}",
        actual_path=path,
        filename=path.name,
        mime_type="image/png" if is_image else "text/plain",
        size=32,
        is_image=is_image,
    )
    message = OutboundMessage(channel_name="wechat", chat_id="wx-user", thread_id="test-thread", text="")
    assert asyncio.run(channel.send_file(message, attachment)) is False
    channel._request_json.assert_not_awaited()
