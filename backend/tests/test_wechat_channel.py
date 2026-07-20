"""Tests for the WeChat IM channel."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from pathlib import Path
from typing import Any
from unittest import mock
from unittest.mock import AsyncMock

from app.channels.message_bus import InboundMessageType, MessageBus, OutboundMessage


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _MockResponse:
    def __init__(self, payload: dict[str, Any], content: bytes | None = None):
        self._payload = payload
        self.content = content or b""
        self.headers = payload.get("headers", {}) if isinstance(payload, dict) else {}

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _MockAsyncClient:
    def __init__(
        self,
        responses: list[dict[str, Any]] | None = None,
        post_calls: list[dict[str, Any]] | None = None,
        get_calls: list[dict[str, Any]] | None = None,
        put_calls: list[dict[str, Any]] | None = None,
        get_responses: list[dict[str, Any]] | None = None,
        post_responses: list[dict[str, Any]] | None = None,
        put_responses: list[dict[str, Any]] | None = None,
        **kwargs,
    ):
        self._responses = list(responses or [])
        self._post_responses = list(post_responses or self._responses)
        self._get_responses = list(get_responses or [])
        self._put_responses = list(put_responses or [])
        self._post_calls = post_calls
        self._get_calls = get_calls
        self._put_calls = put_calls
        self.kwargs = kwargs

    async def post(
        self,
        url: str,
        json: dict[str, Any] | None = None,
        headers: dict[str, Any] | None = None,
        **kwargs,
    ):
        if self._post_calls is not None:
            self._post_calls.append({"url": url, "json": json or {}, "headers": headers or {}, **kwargs})
        payload = self._post_responses.pop(0) if self._post_responses else {"ret": 0}
        return _MockResponse(payload)

    async def get(self, url: str, params: dict[str, Any] | None = None, headers: dict[str, Any] | None = None, **kwargs):
        if self._get_calls is not None:
            self._get_calls.append({"url": url, "params": params or {}, "headers": headers or {}, **kwargs})
        payload = self._get_responses.pop(0) if self._get_responses else {"ret": 0}
        return _MockResponse(payload)

    async def put(self, url: str, content: bytes, headers: dict[str, Any] | None = None, **kwargs):
        if self._put_calls is not None:
            self._put_calls.append({"url": url, "content": content, "headers": headers or {}, **kwargs})
        payload = self._put_responses.pop(0) if self._put_responses else {"ret": 0}
        return _MockResponse(payload)

    async def aclose(self) -> None:
        return None


def test_timing_config_requires_positive_finite_values():
    from app.channels.wechat import WechatChannel

    timing_defaults = {
        "polling_timeout": WechatChannel.DEFAULT_POLLING_TIMEOUT,
        "polling_retry_delay": WechatChannel.DEFAULT_RETRY_DELAY,
        "qrcode_poll_interval": WechatChannel.DEFAULT_QRCODE_POLL_INTERVAL,
        "qrcode_poll_timeout": WechatChannel.DEFAULT_QRCODE_POLL_TIMEOUT,
    }
    attributes = {
        "polling_timeout": "_polling_timeout",
        "polling_retry_delay": "_retry_delay",
        "qrcode_poll_interval": "_qrcode_poll_interval",
        "qrcode_poll_timeout": "_qrcode_poll_timeout",
    }

    for invalid in (0, -1, float("nan"), float("inf"), float("-inf"), 10**1000):
        channel = WechatChannel(
            bus=MessageBus(),
            config={"bot_token": "test-token", **dict.fromkeys(timing_defaults, invalid)},
        )
        assert {key: getattr(channel, attributes[key]) for key in timing_defaults} == timing_defaults

    channel = WechatChannel(bus=MessageBus(), config={"bot_token": "test-token", "polling_retry_delay": "0.25"})
    assert channel._retry_delay == 0.25


def test_handle_update_publishes_private_chat_message():
    from app.channels.wechat import WechatChannel

    async def go():
        bus = MessageBus()
        published = []

        async def capture(msg):
            published.append(msg)

        bus.publish_inbound = capture  # type: ignore[method-assign]

        channel = WechatChannel(bus=bus, config={"bot_token": "test-token"})
        await channel._handle_update(
            {
                "message_type": 1,
                "from_user_id": "wx-user-1",
                "context_token": "ctx-1",
                "item_list": [{"type": 1, "text_item": {"text": "hello from wechat"}}],
            }
        )

        assert len(published) == 1
        inbound = published[0]
        assert inbound.chat_id == "wx-user-1"
        assert inbound.user_id == "wx-user-1"
        assert inbound.text == "hello from wechat"
        assert inbound.msg_type == InboundMessageType.CHAT
        assert inbound.topic_id is None
        assert inbound.metadata["context_token"] == "ctx-1"
        assert channel._context_tokens_by_chat["wx-user-1"] == "ctx-1"

    _run(go())


def test_handle_update_downloads_inbound_image(monkeypatch, tmp_path: Path):
    from app.channels.wechat import WechatChannel

    async def go():
        bus = MessageBus()
        published = []

        async def capture(msg):
            published.append(msg)

        bus.publish_inbound = capture  # type: ignore[method-assign]

        plaintext = b"fake-image-bytes"
        aes_key = b"1234567890abcdef"

        channel = WechatChannel(bus=bus, config={"bot_token": "test-token", "state_dir": str(tmp_path)})
        encrypted = channel.__class__.__dict__["_extract_image_file"].__globals__["_encrypt_aes_128_ecb"](plaintext, aes_key)

        async def _fake_download(_url: str, *, timeout: float | None = None):
            return encrypted

        channel._download_cdn_bytes = _fake_download  # type: ignore[method-assign]

        await channel._handle_update(
            {
                "message_type": 1,
                "message_id": 101,
                "from_user_id": "wx-user-1",
                "context_token": "ctx-img-1",
                "item_list": [
                    {
                        "type": 2,
                        "image_item": {
                            "aeskey": aes_key.hex(),
                            "media": {"full_url": "https://cdn.example/image.bin"},
                        },
                    }
                ],
            }
        )

        assert len(published) == 1
        inbound = published[0]
        assert inbound.text == ""
        assert len(inbound.files) == 1
        file_info = inbound.files[0]
        assert file_info["source"] == "wechat"
        assert file_info["message_item_type"] == 2
        stored = Path(file_info["path"])
        assert stored.exists()
        assert stored.read_bytes() == plaintext

    _run(go())


def test_handle_update_downloads_inbound_png_with_png_extension(monkeypatch, tmp_path: Path):
    from app.channels.wechat import WechatChannel

    async def go():
        bus = MessageBus()
        published = []

        async def capture(msg):
            published.append(msg)

        bus.publish_inbound = capture  # type: ignore[method-assign]

        plaintext = b"\x89PNG\r\n\x1a\n" + b"png-body"
        aes_key = b"1234567890abcdef"

        channel = WechatChannel(bus=bus, config={"bot_token": "test-token", "state_dir": str(tmp_path)})
        encrypted = channel.__class__.__dict__["_extract_image_file"].__globals__["_encrypt_aes_128_ecb"](plaintext, aes_key)

        async def _fake_download(_url: str, *, timeout: float | None = None):
            return encrypted

        channel._download_cdn_bytes = _fake_download  # type: ignore[method-assign]

        await channel._handle_update(
            {
                "message_type": 1,
                "message_id": 303,
                "from_user_id": "wx-user-1",
                "context_token": "ctx-img-png",
                "item_list": [
                    {
                        "type": 2,
                        "image_item": {
                            "aeskey": aes_key.hex(),
                            "media": {"full_url": "https://cdn.example/image.bin"},
                        },
                    }
                ],
            }
        )

        assert len(published) == 1
        file_info = published[0].files[0]
        assert file_info["filename"].endswith(".png")
        assert file_info["mime_type"] == "image/png"

    _run(go())


def test_handle_update_preserves_text_and_ref_msg_with_image(monkeypatch, tmp_path: Path):
    from app.channels.wechat import WechatChannel

    async def go():
        bus = MessageBus()
        published = []

        async def capture(msg):
            published.append(msg)

        bus.publish_inbound = capture  # type: ignore[method-assign]

        plaintext = b"img-2"
        aes_key = b"1234567890abcdef"
        channel = WechatChannel(bus=bus, config={"bot_token": "test-token", "state_dir": str(tmp_path)})
        encrypted = channel.__class__.__dict__["_extract_image_file"].__globals__["_encrypt_aes_128_ecb"](plaintext, aes_key)

        async def _fake_download(_url: str, *, timeout: float | None = None):
            return encrypted

        channel._download_cdn_bytes = _fake_download  # type: ignore[method-assign]

        await channel._handle_update(
            {
                "message_type": 1,
                "message_id": 202,
                "from_user_id": "wx-user-1",
                "context_token": "ctx-img-2",
                "item_list": [
                    {"type": 1, "text_item": {"text": "look at this"}},
                    {
                        "type": 2,
                        "ref_msg": {"title": "quoted", "message_item": {"type": 1}},
                        "image_item": {
                            "aeskey": aes_key.hex(),
                            "media": {"full_url": "https://cdn.example/image2.bin"},
                        },
                    },
                ],
            }
        )

        assert len(published) == 1
        inbound = published[0]
        assert inbound.text == "look at this"
        assert len(inbound.files) == 1
        assert inbound.metadata["ref_msg"]["title"] == "quoted"

    _run(go())


def test_handle_update_skips_image_without_url_or_key(tmp_path: Path):
    from app.channels.wechat import WechatChannel

    async def go():
        bus = MessageBus()
        published = []

        async def capture(msg):
            published.append(msg)

        bus.publish_inbound = capture  # type: ignore[method-assign]

        channel = WechatChannel(bus=bus, config={"bot_token": "test-token", "state_dir": str(tmp_path)})

        await channel._handle_update(
            {
                "message_type": 1,
                "from_user_id": "wx-user-1",
                "context_token": "ctx-img-3",
                "item_list": [
                    {
                        "type": 2,
                        "image_item": {"media": {}},
                    }
                ],
            }
        )

        assert published == []

    _run(go())


def test_handle_update_routes_slash_command_as_command():
    from app.channels.wechat import WechatChannel

    async def go():
        bus = MessageBus()
        published = []

        async def capture(msg):
            published.append(msg)

        bus.publish_inbound = capture  # type: ignore[method-assign]

        channel = WechatChannel(bus=bus, config={"bot_token": "test-token"})
        await channel._handle_update(
            {
                "message_type": 1,
                "from_user_id": "wx-user-1",
                "context_token": "ctx-2",
                "item_list": [{"type": 1, "text_item": {"text": "/status"}}],
            }
        )

        assert len(published) == 1
        assert published[0].msg_type == InboundMessageType.COMMAND

    _run(go())


def test_allowed_users_filter_blocks_non_whitelisted_sender():
    from app.channels.wechat import WechatChannel

    async def go():
        bus = MessageBus()
        published = []

        async def capture(msg):
            published.append(msg)

        bus.publish_inbound = capture  # type: ignore[method-assign]

        channel = WechatChannel(bus=bus, config={"bot_token": "test-token", "allowed_users": ["allowed-user"]})
        await channel._handle_update(
            {
                "message_type": 1,
                "from_user_id": "blocked-user",
                "context_token": "ctx-3",
                "item_list": [{"type": 1, "text_item": {"text": "hello"}}],
            }
        )

        assert published == []

    _run(go())


def test_connect_code_bypasses_allowed_users_filter(tmp_path: Path):
    from app.channels.wechat import WechatChannel
    from deerflow.persistence.channel_connections import ChannelConnectionRepository, ChannelCredentialCipher
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine

    async def go():
        from datetime import UTC, datetime, timedelta

        await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'wechat.db'}", sqlite_dir=str(tmp_path))
        try:
            repo = ChannelConnectionRepository(
                get_session_factory(),
                cipher=ChannelCredentialCipher.from_key("wechat-secret"),
            )
            code = "wechat-bind-code"
            await repo.create_oauth_state(
                owner_user_id="deerflow-user-1",
                provider="wechat",
                state=code,
                expires_at=datetime.now(UTC) + timedelta(minutes=5),
            )

            bus = MessageBus()
            published = []

            async def capture(msg):
                published.append(msg)

            bus.publish_inbound = capture  # type: ignore[method-assign]

            # The newcomer ("blocked-user") is not in allowed_users yet, but a valid
            # /connect code must still bootstrap their first bind.
            channel = WechatChannel(
                bus=bus,
                config={"bot_token": "test-token", "allowed_users": ["allowed-user"], "connection_repo": repo},
            )
            channel._send_connection_reply = AsyncMock()  # type: ignore[method-assign]

            await channel._handle_update(
                {
                    "message_type": 1,
                    "from_user_id": "blocked-user",
                    "context_token": "ctx-connect",
                    "item_list": [{"type": 1, "text_item": {"text": f"/connect {code}"}}],
                }
            )

            connections = await repo.list_connections("deerflow-user-1")
            assert len(connections) == 1
            assert connections[0]["provider"] == "wechat"
            assert connections[0]["external_account_id"] == "blocked-user"
            # The connect-code reply was sent and no normal inbound was published.
            channel._send_connection_reply.assert_awaited_once()
            assert published == []
        finally:
            await close_engine()

    _run(go())


def test_send_uses_cached_context_token(monkeypatch):
    from app.channels.wechat import WechatChannel

    async def go():
        post_calls: list[dict[str, Any]] = []

        def _client_factory(*args, **kwargs):
            return _MockAsyncClient(responses=[{"ret": 0}], post_calls=post_calls, **kwargs)

        monkeypatch.setattr("app.channels.wechat.httpx.AsyncClient", _client_factory)

        channel = WechatChannel(bus=MessageBus(), config={"bot_token": "bot-token"})
        channel._context_tokens_by_chat["wx-user-1"] = "ctx-send"

        await channel.send(
            OutboundMessage(
                channel_name="wechat",
                chat_id="wx-user-1",
                thread_id="thread-1",
                text="reply text",
            )
        )

        assert len(post_calls) == 1
        assert post_calls[0]["url"].endswith("/ilink/bot/sendmessage")
        assert post_calls[0]["json"]["msg"]["to_user_id"] == "wx-user-1"
        assert post_calls[0]["json"]["msg"]["context_token"] == "ctx-send"
        assert post_calls[0]["headers"]["Authorization"] == "Bearer bot-token"
        assert post_calls[0]["headers"]["AuthorizationType"] == "ilink_bot_token"
        assert "X-WECHAT-UIN" in post_calls[0]["headers"]
        assert "iLink-App-ClientVersion" in post_calls[0]["headers"]

    _run(go())


def test_send_skips_when_context_token_missing(monkeypatch):
    from app.channels.wechat import WechatChannel

    async def go():
        post_calls: list[dict[str, Any]] = []

        def _client_factory(*args, **kwargs):
            return _MockAsyncClient(responses=[{"ret": 0}], post_calls=post_calls, **kwargs)

        monkeypatch.setattr("app.channels.wechat.httpx.AsyncClient", _client_factory)

        channel = WechatChannel(bus=MessageBus(), config={"bot_token": "bot-token"})
        await channel.send(
            OutboundMessage(
                channel_name="wechat",
                chat_id="wx-user-1",
                thread_id="thread-1",
                text="reply text",
            )
        )

        assert post_calls == []

    _run(go())


def test_protocol_helpers_build_expected_values():
    from app.channels.wechat import (
        MessageItemType,
        UploadMediaType,
        _build_ilink_client_version,
        _build_wechat_uin,
        _encrypted_size_for_aes_128_ecb,
    )

    assert int(MessageItemType.TEXT) == 1
    assert int(UploadMediaType.FILE) == 3
    assert _build_ilink_client_version("1.0.11") == str((1 << 16) | 11)

    encoded = _build_wechat_uin()
    decoded = base64.b64decode(encoded).decode("utf-8")
    assert decoded.isdigit()

    assert _encrypted_size_for_aes_128_ecb(0) == 16
    assert _encrypted_size_for_aes_128_ecb(1) == 16
    assert _encrypted_size_for_aes_128_ecb(16) == 32


def test_aes_roundtrip_encrypts_and_decrypts():
    from app.channels.wechat import _decrypt_aes_128_ecb, _encrypt_aes_128_ecb

    key = b"1234567890abcdef"
    plaintext = b"hello-wechat-media"

    encrypted = _encrypt_aes_128_ecb(plaintext, key)
    assert encrypted != plaintext

    decrypted = _decrypt_aes_128_ecb(encrypted, key)
    assert decrypted == plaintext


def test_build_upload_request_supports_no_need_thumb():
    from app.channels.wechat import UploadMediaType, WechatChannel

    channel = WechatChannel(bus=MessageBus(), config={"bot_token": "bot-token"})
    payload = channel._build_upload_request(
        filekey="file-key-1",
        media_type=UploadMediaType.IMAGE,
        to_user_id="wx-user-1",
        plaintext=b"image-bytes",
        aes_key=b"1234567890abcdef",
        no_need_thumb=True,
    )

    assert payload["filekey"] == "file-key-1"
    assert payload["media_type"] == 1
    assert payload["to_user_id"] == "wx-user-1"
    assert payload["rawsize"] == len(b"image-bytes")
    assert payload["filesize"] >= len(b"image-bytes")
    assert payload["no_need_thumb"] is True
    assert payload["aeskey"] == b"1234567890abcdef".hex()


def test_send_file_uploads_and_sends_image(monkeypatch, tmp_path: Path):
    from app.channels.message_bus import ResolvedAttachment
    from app.channels.wechat import WechatChannel

    async def go():
        post_calls: list[dict[str, Any]] = []
        put_calls: list[dict[str, Any]] = []

        def _client_factory(*args, **kwargs):
            return _MockAsyncClient(
                post_calls=post_calls,
                put_calls=put_calls,
                post_responses=[
                    {
                        "ret": 0,
                        "upload_param": "enc-query-original",
                        "thumb_upload_param": "enc-query-thumb",
                        "upload_full_url": "https://cdn.example/upload-original",
                    },
                    {"ret": 0},
                ],
                **kwargs,
            )

        monkeypatch.setattr("app.channels.wechat.httpx.AsyncClient", _client_factory)

        image_path = tmp_path / "chart.png"
        image_path.write_bytes(b"png-binary-data")

        channel = WechatChannel(bus=MessageBus(), config={"bot_token": "bot-token"})
        channel._context_tokens_by_chat["wx-user-1"] = "ctx-image-send"

        ok = await channel.send_file(
            OutboundMessage(
                channel_name="wechat",
                chat_id="wx-user-1",
                thread_id="thread-1",
                text="reply text",
            ),
            ResolvedAttachment(
                virtual_path="/mnt/user-data/outputs/chart.png",
                actual_path=image_path,
                filename="chart.png",
                mime_type="image/png",
                size=image_path.stat().st_size,
                is_image=True,
            ),
        )

        assert ok is True
        assert len(post_calls) == 3
        assert post_calls[0]["url"].endswith("/ilink/bot/getuploadurl")
        assert post_calls[0]["json"]["media_type"] == 1
        assert post_calls[0]["json"]["no_need_thumb"] is True
        assert len(put_calls) == 0
        assert post_calls[1]["url"] == "https://cdn.example/upload-original"
        assert post_calls[2]["url"].endswith("/ilink/bot/sendmessage")
        image_item = post_calls[2]["json"]["msg"]["item_list"][0]["image_item"]
        assert image_item["media"]["encrypt_query_param"] == "enc-query-original"
        assert image_item["media"]["encrypt_type"] == 1
        assert image_item["mid_size"] > 0
        assert "thumb_media" not in image_item
        assert "aeskey" not in image_item
        assert base64.b64decode(image_item["media"]["aes_key"]).decode("utf-8") == post_calls[0]["json"]["aeskey"]

    _run(go())


def test_send_file_returns_false_without_upload_full_url(monkeypatch, tmp_path: Path):
    from app.channels.message_bus import ResolvedAttachment
    from app.channels.wechat import WechatChannel

    async def go():
        post_calls: list[dict[str, Any]] = []

        def _client_factory(*args, **kwargs):
            return _MockAsyncClient(
                post_calls=post_calls,
                post_responses=[
                    {"ret": 0, "upload_param": "enc-query-only"},
                    {"ret": 0},
                ],
                **kwargs,
            )

        monkeypatch.setattr("app.channels.wechat.httpx.AsyncClient", _client_factory)

        image_path = tmp_path / "chart.png"
        image_path.write_bytes(b"png-binary-data")

        channel = WechatChannel(bus=MessageBus(), config={"bot_token": "bot-token"})
        channel._context_tokens_by_chat["wx-user-1"] = "ctx-image-send"

        ok = await channel.send_file(
            OutboundMessage(channel_name="wechat", chat_id="wx-user-1", thread_id="thread-1", text="reply text"),
            ResolvedAttachment(
                virtual_path="/mnt/user-data/outputs/chart.png",
                actual_path=image_path,
                filename="chart.png",
                mime_type="image/png",
                size=image_path.stat().st_size,
                is_image=True,
            ),
        )

        assert ok is True
        assert len(post_calls) == 3
        assert post_calls[1]["url"].startswith("https://novac2c.cdn.weixin.qq.com/c2c/upload?")
        assert post_calls[2]["url"].endswith("/ilink/bot/sendmessage")
        image_item = post_calls[2]["json"]["msg"]["item_list"][0]["image_item"]
        assert image_item["media"]["encrypt_query_param"] == "enc-query-only"
        assert image_item["media"]["encrypt_type"] == 1

    _run(go())


def test_send_file_prefers_cdn_response_header_for_image(monkeypatch, tmp_path: Path):
    from app.channels.message_bus import ResolvedAttachment
    from app.channels.wechat import WechatChannel

    async def go():
        post_calls: list[dict[str, Any]] = []

        def _client_factory(*args, **kwargs):
            return _MockAsyncClient(
                post_calls=post_calls,
                post_responses=[
                    {"ret": 0, "upload_param": "enc-query-original", "thumb_upload_param": "enc-query-thumb"},
                    {"ret": 0, "headers": {"x-encrypted-param": "enc-query-downloaded"}},
                    {"ret": 0},
                ],
                **kwargs,
            )

        monkeypatch.setattr("app.channels.wechat.httpx.AsyncClient", _client_factory)

        image_path = tmp_path / "chart.png"
        image_path.write_bytes(b"png-binary-data")

        channel = WechatChannel(bus=MessageBus(), config={"bot_token": "bot-token"})
        channel._context_tokens_by_chat["wx-user-1"] = "ctx-image-send"

        ok = await channel.send_file(
            OutboundMessage(channel_name="wechat", chat_id="wx-user-1", thread_id="thread-1", text="reply text"),
            ResolvedAttachment(
                virtual_path="/mnt/user-data/outputs/chart.png",
                actual_path=image_path,
                filename="chart.png",
                mime_type="image/png",
                size=image_path.stat().st_size,
                is_image=True,
            ),
        )

        assert ok is True
        assert post_calls[1]["url"].startswith("https://novac2c.cdn.weixin.qq.com/c2c/upload?")
        image_item = post_calls[2]["json"]["msg"]["item_list"][0]["image_item"]
        assert image_item["media"]["encrypt_query_param"] == "enc-query-downloaded"
        assert image_item["media"]["encrypt_type"] == 1
        assert "thumb_media" not in image_item
        assert "aeskey" not in image_item

    _run(go())


def test_send_file_skips_non_image(monkeypatch, tmp_path: Path):
    from app.channels.message_bus import ResolvedAttachment
    from app.channels.wechat import WechatChannel

    async def go():
        post_calls: list[dict[str, Any]] = []

        def _client_factory(*args, **kwargs):
            return _MockAsyncClient(post_calls=post_calls, **kwargs)

        monkeypatch.setattr("app.channels.wechat.httpx.AsyncClient", _client_factory)

        file_path = tmp_path / "notes.txt"
        file_path.write_text("hello")

        channel = WechatChannel(bus=MessageBus(), config={"bot_token": "bot-token"})
        ok = await channel.send_file(
            OutboundMessage(channel_name="wechat", chat_id="wx-user-1", thread_id="thread-1", text="reply text"),
            ResolvedAttachment(
                virtual_path="/mnt/user-data/outputs/notes.txt",
                actual_path=file_path,
                filename="notes.txt",
                mime_type="text/plain",
                size=file_path.stat().st_size,
                is_image=False,
            ),
        )

        assert ok is False
        assert post_calls == []

    _run(go())


def test_send_file_uploads_and_sends_regular_file(monkeypatch, tmp_path: Path):
    from app.channels.message_bus import ResolvedAttachment
    from app.channels.wechat import WechatChannel

    async def go():
        post_calls: list[dict[str, Any]] = []
        put_calls: list[dict[str, Any]] = []

        def _client_factory(*args, **kwargs):
            return _MockAsyncClient(
                post_calls=post_calls,
                put_calls=put_calls,
                post_responses=[
                    {
                        "ret": 0,
                        "upload_param": "enc-query-file",
                        "upload_full_url": "https://cdn.example/upload-file",
                    },
                    {"ret": 0},
                ],
                **kwargs,
            )

        monkeypatch.setattr("app.channels.wechat.httpx.AsyncClient", _client_factory)

        file_path = tmp_path / "report.pdf"
        file_path.write_bytes(b"%PDF-1.4 fake")

        channel = WechatChannel(bus=MessageBus(), config={"bot_token": "bot-token"})
        channel._context_tokens_by_chat["wx-user-1"] = "ctx-file-send"

        ok = await channel.send_file(
            OutboundMessage(channel_name="wechat", chat_id="wx-user-1", thread_id="thread-1", text="reply text"),
            ResolvedAttachment(
                virtual_path="/mnt/user-data/outputs/report.pdf",
                actual_path=file_path,
                filename="report.pdf",
                mime_type="application/pdf",
                size=file_path.stat().st_size,
                is_image=False,
            ),
        )

        assert ok is True
        assert len(post_calls) == 3
        assert post_calls[0]["url"].endswith("/ilink/bot/getuploadurl")
        assert post_calls[0]["json"]["media_type"] == 3
        assert post_calls[0]["json"]["no_need_thumb"] is True
        assert len(put_calls) == 0
        assert post_calls[1]["url"] == "https://cdn.example/upload-file"
        assert post_calls[2]["url"].endswith("/ilink/bot/sendmessage")
        file_item = post_calls[2]["json"]["msg"]["item_list"][0]["file_item"]
        assert file_item["media"]["encrypt_query_param"] == "enc-query-file"
        assert file_item["file_name"] == "report.pdf"
        assert file_item["media"]["encrypt_type"] == 1
        assert base64.b64decode(file_item["media"]["aes_key"]).decode("utf-8") == post_calls[0]["json"]["aeskey"]

    _run(go())


def test_send_regular_file_uses_cdn_upload_fallback_when_upload_full_url_missing(monkeypatch, tmp_path: Path):
    from app.channels.message_bus import ResolvedAttachment
    from app.channels.wechat import WechatChannel

    async def go():
        post_calls: list[dict[str, Any]] = []

        def _client_factory(*args, **kwargs):
            return _MockAsyncClient(
                post_calls=post_calls,
                post_responses=[
                    {"ret": 0, "upload_param": "enc-query-file"},
                    {"ret": 0, "headers": {"x-encrypted-param": "enc-query-file-final"}},
                    {"ret": 0},
                ],
                **kwargs,
            )

        monkeypatch.setattr("app.channels.wechat.httpx.AsyncClient", _client_factory)

        file_path = tmp_path / "report.pdf"
        file_path.write_bytes(b"%PDF-1.4 fake")

        channel = WechatChannel(bus=MessageBus(), config={"bot_token": "bot-token"})
        channel._context_tokens_by_chat["wx-user-1"] = "ctx-file-send"

        ok = await channel.send_file(
            OutboundMessage(channel_name="wechat", chat_id="wx-user-1", thread_id="thread-1", text="reply text"),
            ResolvedAttachment(
                virtual_path="/mnt/user-data/outputs/report.pdf",
                actual_path=file_path,
                filename="report.pdf",
                mime_type="application/pdf",
                size=file_path.stat().st_size,
                is_image=False,
            ),
        )

        assert ok is True
        assert post_calls[1]["url"].startswith("https://novac2c.cdn.weixin.qq.com/c2c/upload?")
        assert post_calls[2]["url"].endswith("/ilink/bot/sendmessage")
        file_item = post_calls[2]["json"]["msg"]["item_list"][0]["file_item"]
        assert file_item["media"]["encrypt_query_param"] == "enc-query-file-final"
        assert file_item["media"]["encrypt_type"] == 1

    _run(go())


def test_send_image_uses_post_even_when_upload_full_url_present(monkeypatch, tmp_path: Path):
    from app.channels.message_bus import ResolvedAttachment
    from app.channels.wechat import WechatChannel

    async def go():
        post_calls: list[dict[str, Any]] = []
        put_calls: list[dict[str, Any]] = []

        def _client_factory(*args, **kwargs):
            return _MockAsyncClient(
                post_calls=post_calls,
                put_calls=put_calls,
                post_responses=[
                    {
                        "ret": 0,
                        "upload_param": "enc-query-original",
                        "thumb_upload_param": "enc-query-thumb",
                        "upload_full_url": "https://cdn.example/upload-original",
                    },
                    {"ret": 0, "headers": {"x-encrypted-param": "enc-query-downloaded"}},
                    {"ret": 0},
                ],
                **kwargs,
            )

        monkeypatch.setattr("app.channels.wechat.httpx.AsyncClient", _client_factory)

        image_path = tmp_path / "chart.png"
        image_path.write_bytes(b"png-binary-data")

        channel = WechatChannel(bus=MessageBus(), config={"bot_token": "bot-token"})
        channel._context_tokens_by_chat["wx-user-1"] = "ctx-image-send"

        ok = await channel.send_file(
            OutboundMessage(channel_name="wechat", chat_id="wx-user-1", thread_id="thread-1", text="reply text"),
            ResolvedAttachment(
                virtual_path="/mnt/user-data/outputs/chart.png",
                actual_path=image_path,
                filename="chart.png",
                mime_type="image/png",
                size=image_path.stat().st_size,
                is_image=True,
            ),
        )

        assert ok is True
        assert len(put_calls) == 0
        assert post_calls[1]["url"] == "https://cdn.example/upload-original"

    _run(go())


def test_send_file_blocks_disallowed_regular_file(monkeypatch, tmp_path: Path):
    from app.channels.message_bus import ResolvedAttachment
    from app.channels.wechat import WechatChannel

    async def go():
        post_calls: list[dict[str, Any]] = []

        def _client_factory(*args, **kwargs):
            return _MockAsyncClient(post_calls=post_calls, **kwargs)

        monkeypatch.setattr("app.channels.wechat.httpx.AsyncClient", _client_factory)

        file_path = tmp_path / "malware.exe"
        file_path.write_bytes(b"MZ")

        channel = WechatChannel(bus=MessageBus(), config={"bot_token": "bot-token"})
        channel._context_tokens_by_chat["wx-user-1"] = "ctx-file-send"

        ok = await channel.send_file(
            OutboundMessage(channel_name="wechat", chat_id="wx-user-1", thread_id="thread-1", text="reply text"),
            ResolvedAttachment(
                virtual_path="/mnt/user-data/outputs/malware.exe",
                actual_path=file_path,
                filename="malware.exe",
                mime_type="application/octet-stream",
                size=file_path.stat().st_size,
                is_image=False,
            ),
        )

        assert ok is False
        assert post_calls == []

    _run(go())


def test_handle_update_downloads_inbound_file(monkeypatch, tmp_path: Path):
    from app.channels.wechat import WechatChannel

    async def go():
        bus = MessageBus()
        published = []

        async def capture(msg):
            published.append(msg)

        bus.publish_inbound = capture  # type: ignore[method-assign]

        plaintext = b"hello,file"
        aes_key = b"1234567890abcdef"

        channel = WechatChannel(bus=bus, config={"bot_token": "test-token", "state_dir": str(tmp_path)})
        encrypted = channel.__class__.__dict__["_extract_file_item"].__globals__["_encrypt_aes_128_ecb"](plaintext, aes_key)

        async def _fake_download(_url: str, *, timeout: float | None = None):
            return encrypted

        channel._download_cdn_bytes = _fake_download  # type: ignore[method-assign]

        await channel._handle_update(
            {
                "message_type": 1,
                "message_id": 303,
                "from_user_id": "wx-user-1",
                "context_token": "ctx-file-1",
                "item_list": [
                    {
                        "type": 4,
                        "file_item": {
                            "file_name": "report.pdf",
                            "aeskey": aes_key.hex(),
                            "media": {"full_url": "https://cdn.example/report.bin"},
                        },
                    }
                ],
            }
        )

        assert len(published) == 1
        inbound = published[0]
        assert inbound.text == ""
        assert len(inbound.files) == 1
        file_info = inbound.files[0]
        assert file_info["message_item_type"] == 4
        stored = Path(file_info["path"])
        assert stored.exists()
        assert stored.read_bytes() == plaintext

    _run(go())


def test_handle_update_downloads_inbound_file_with_media_aeskey_hex(monkeypatch, tmp_path: Path):
    from app.channels.wechat import WechatChannel

    async def go():
        bus = MessageBus()
        published = []

        async def capture(msg):
            published.append(msg)

        bus.publish_inbound = capture  # type: ignore[method-assign]

        plaintext = b"hello,file"
        aes_key = b"1234567890abcdef"

        channel = WechatChannel(bus=bus, config={"bot_token": "test-token", "state_dir": str(tmp_path)})
        encrypted = channel.__class__.__dict__["_extract_file_item"].__globals__["_encrypt_aes_128_ecb"](plaintext, aes_key)

        async def _fake_download(_url: str, *, timeout: float | None = None):
            return encrypted

        channel._download_cdn_bytes = _fake_download  # type: ignore[method-assign]

        await channel._handle_update(
            {
                "message_type": 1,
                "message_id": 304,
                "from_user_id": "wx-user-1",
                "context_token": "ctx-file-1b",
                "item_list": [
                    {
                        "type": 4,
                        "file_item": {
                            "file_name": "report.pdf",
                            "media": {
                                "full_url": "https://cdn.example/report.bin",
                                "aeskey": aes_key.hex(),
                            },
                        },
                    }
                ],
            }
        )

        assert len(published) == 1
        assert published[0].files[0]["filename"] == "report.pdf"

    _run(go())


def test_handle_update_downloads_inbound_file_with_unpadded_item_aes_key(monkeypatch, tmp_path: Path):
    from app.channels.wechat import WechatChannel

    async def go():
        bus = MessageBus()
        published = []

        async def capture(msg):
            published.append(msg)

        bus.publish_inbound = capture  # type: ignore[method-assign]

        plaintext = b"hello,file"
        aes_key = b"1234567890abcdef"
        encoded_key = base64.b64encode(aes_key).decode("utf-8").rstrip("=")

        channel = WechatChannel(bus=bus, config={"bot_token": "test-token", "state_dir": str(tmp_path)})
        encrypted = channel.__class__.__dict__["_extract_file_item"].__globals__["_encrypt_aes_128_ecb"](plaintext, aes_key)

        async def _fake_download(_url: str, *, timeout: float | None = None):
            return encrypted

        channel._download_cdn_bytes = _fake_download  # type: ignore[method-assign]

        await channel._handle_update(
            {
                "message_type": 1,
                "message_id": 305,
                "from_user_id": "wx-user-1",
                "context_token": "ctx-file-1c",
                "item_list": [
                    {
                        "type": 4,
                        "aesKey": encoded_key,
                        "file_item": {
                            "file_name": "report.pdf",
                            "media": {"full_url": "https://cdn.example/report.bin"},
                        },
                    }
                ],
            }
        )

        assert len(published) == 1
        assert published[0].files[0]["filename"] == "report.pdf"

    _run(go())


def test_handle_update_downloads_inbound_file_with_media_aes_key_base64_of_hex(monkeypatch, tmp_path: Path):
    from app.channels.wechat import WechatChannel

    async def go():
        bus = MessageBus()
        published = []

        async def capture(msg):
            published.append(msg)

        bus.publish_inbound = capture  # type: ignore[method-assign]

        plaintext = b"hello,file"
        aes_key = b"1234567890abcdef"
        encoded_hex_key = base64.b64encode(aes_key.hex().encode("utf-8")).decode("utf-8")

        channel = WechatChannel(bus=bus, config={"bot_token": "test-token", "state_dir": str(tmp_path)})
        encrypted = channel.__class__.__dict__["_extract_file_item"].__globals__["_encrypt_aes_128_ecb"](plaintext, aes_key)

        async def _fake_download(_url: str, *, timeout: float | None = None):
            return encrypted

        channel._download_cdn_bytes = _fake_download  # type: ignore[method-assign]

        await channel._handle_update(
            {
                "message_type": 1,
                "message_id": 306,
                "from_user_id": "wx-user-1",
                "context_token": "ctx-file-1d",
                "item_list": [
                    {
                        "type": 4,
                        "file_item": {
                            "file_name": "report.pdf",
                            "media": {
                                "full_url": "https://cdn.example/report.bin",
                                "aes_key": encoded_hex_key,
                            },
                        },
                    }
                ],
            }
        )

        assert len(published) == 1
        assert published[0].files[0]["filename"] == "report.pdf"

    _run(go())


def test_handle_update_skips_disallowed_inbound_file(monkeypatch, tmp_path: Path):
    from app.channels.wechat import WechatChannel

    async def go():
        bus = MessageBus()
        published = []

        async def capture(msg):
            published.append(msg)

        bus.publish_inbound = capture  # type: ignore[method-assign]

        plaintext = b"MZ"
        aes_key = b"1234567890abcdef"

        channel = WechatChannel(bus=bus, config={"bot_token": "test-token", "state_dir": str(tmp_path)})
        encrypted = channel.__class__.__dict__["_extract_file_item"].__globals__["_encrypt_aes_128_ecb"](plaintext, aes_key)

        async def _fake_download(_url: str, *, timeout: float | None = None):
            return encrypted

        channel._download_cdn_bytes = _fake_download  # type: ignore[method-assign]

        await channel._handle_update(
            {
                "message_type": 1,
                "message_id": 404,
                "from_user_id": "wx-user-1",
                "context_token": "ctx-file-2",
                "item_list": [
                    {
                        "type": 4,
                        "file_item": {
                            "file_name": "malware.exe",
                            "aeskey": aes_key.hex(),
                            "media": {"full_url": "https://cdn.example/bad.bin"},
                        },
                    }
                ],
            }
        )

        assert published == []

    _run(go())


def test_poll_loop_updates_server_timeout(monkeypatch):
    from app.channels.wechat import WechatChannel

    async def go():
        post_calls: list[dict[str, Any]] = []

        def _client_factory(*args, **kwargs):
            return _MockAsyncClient(
                post_calls=post_calls,
                post_responses=[
                    {
                        "ret": 0,
                        "msgs": [
                            {
                                "message_type": 1,
                                "from_user_id": "wx-user-1",
                                "context_token": "ctx-1",
                                "item_list": [{"type": 1, "text_item": {"text": "hello"}}],
                            }
                        ],
                        "get_updates_buf": "cursor-next",
                        "longpolling_timeout_ms": 42000,
                    }
                ],
                **kwargs,
            )

        monkeypatch.setattr("app.channels.wechat.httpx.AsyncClient", _client_factory)

        channel = WechatChannel(bus=MessageBus(), config={"bot_token": "bot-token"})
        channel._running = True

        async def _fake_handle_update(_raw):
            channel._running = False
            return None

        channel._handle_update = _fake_handle_update  # type: ignore[method-assign]

        await channel._poll_loop()

        assert channel._get_updates_buf == "cursor-next"
        assert channel._server_longpoll_timeout_seconds == 42.0
        assert post_calls[0]["url"].endswith("/ilink/bot/getupdates")

    _run(go())


def test_poll_loop_one_bad_message_does_not_permanently_lose_its_siblings(monkeypatch, tmp_path: Path, caplog):
    """A single message that fails to process must not sink the rest of its batch.

    Regression test for a permanent message-loss bug: the long-poll cursor was
    persisted for the *whole* batch before the per-message loop ran, and the loop
    had no per-message error isolation, so one bad message (e.g. an attachment
    that fails to decrypt) aborted processing of every message after it in the
    same batch. Because the cursor had already advanced past the whole batch,
    the next poll would never re-fetch the unprocessed tail -- silent, permanent
    loss of every message after the first failure in a batch.

    This test sends a real 3-message batch through the *real* (unstubbed)
    ``_handle_update`` -- message 1 is fine, message 2 is a WeChat image item
    whose "encrypted" bytes are deliberately not a multiple of the AES block
    size, so ``_decrypt_aes_128_ecb`` raises a genuine ``cryptography`` library
    ``ValueError`` (matching how a real corrupt/undecryptable attachment would
    fail), and message 3 is fine again. The fix must:
      - still deliver message 1 and message 3 to the bus despite message 2's
        failure (per-message isolation instead of one bad apple aborting the
        for loop), and
      - log message 2's failure instead of swallowing it silently, and
      - only advance/persist the cursor once the whole batch has been
        attempted (so a crash mid-batch re-delivers rather than silently
        drops).
    """
    from app.channels.wechat import WechatChannel

    async def go():
        bus = MessageBus()
        published: list[Any] = []

        async def capture(msg):
            published.append(msg)

        bus.publish_inbound = capture  # type: ignore[method-assign]

        aes_key = b"1234567890abcdef"
        non_block_aligned_ciphertext = b"\x01\x02\x03\x04\x05"  # 5 bytes: not a multiple of 16

        msg_good_1 = {
            "message_type": 1,
            "message_id": "msg-1-good",
            "from_user_id": "wx-user-1",
            "context_token": "ctx-1",
            "item_list": [{"type": 1, "text_item": {"text": "message one"}}],
        }
        msg_bad_2 = {
            "message_type": 1,
            "message_id": "msg-2-bad",
            "from_user_id": "wx-user-1",
            "context_token": "ctx-2",
            "item_list": [
                {
                    "type": 2,
                    "image_item": {
                        "aeskey": aes_key.hex(),
                        "media": {"full_url": "https://cdn.example/corrupt-attachment.bin"},
                    },
                }
            ],
        }
        msg_good_3 = {
            "message_type": 1,
            "message_id": "msg-3-good",
            "from_user_id": "wx-user-1",
            "context_token": "ctx-3",
            "item_list": [{"type": 1, "text_item": {"text": "message three"}}],
        }

        state_dir = tmp_path / "wechat-state"

        def _client_factory(*args, **kwargs):
            return _MockAsyncClient(
                post_responses=[
                    {
                        "ret": 0,
                        "msgs": [msg_good_1, msg_bad_2, msg_good_3],
                        "get_updates_buf": "cursor-after-batch",
                    }
                ],
                **kwargs,
            )

        monkeypatch.setattr("app.channels.wechat.httpx.AsyncClient", _client_factory)

        channel = WechatChannel(
            bus=bus,
            config={"bot_token": "test-token", "state_dir": str(state_dir), "polling_retry_delay": 0.001},
        )

        async def _fake_download(_url: str, *, timeout: float | None = None) -> bytes:
            return non_block_aligned_ciphertext

        channel._download_cdn_bytes = _fake_download  # type: ignore[method-assign]

        # _handle_update is intentionally left as the REAL implementation so
        # message 2 hits the genuine cryptography ValueError. To keep the test
        # deterministic without depending on the bug/fix under test, force the
        # poll loop to stop after exactly one getupdates cycle via
        # _ensure_authenticated (called at the top of every iteration, before
        # any message is processed) rather than via message content.
        real_ensure_authenticated = channel._ensure_authenticated
        auth_calls = {"n": 0}

        async def _ensure_auth_then_stop() -> bool:
            auth_calls["n"] += 1
            if auth_calls["n"] > 1:
                channel._running = False
                return False
            return await real_ensure_authenticated()

        channel._ensure_authenticated = _ensure_auth_then_stop  # type: ignore[method-assign]
        channel._running = True

        with caplog.at_level(logging.INFO, logger="app.channels.wechat"):
            await channel._poll_loop()

        # Message 1 and message 3 must both survive message 2's failure.
        assert [m.text for m in published] == ["message one", "message three"]

        # Message 2's failure must be logged, not silently swallowed.
        messages = [record.getMessage() for record in caplog.records]
        assert any("msg-2-bad" in message for message in messages)

        # The cursor must reflect that the whole batch was attempted -- both
        # in memory and in the persisted state file used to resume polling.
        assert channel._get_updates_buf == "cursor-after-batch"
        persisted = json.loads((state_dir / "wechat-getupdates.json").read_text(encoding="utf-8"))
        assert persisted["get_updates_buf"] == "cursor-after-batch"

    _run(go())


def test_state_cursor_is_loaded_from_disk(tmp_path: Path):
    from app.channels.wechat import WechatChannel

    state_dir = tmp_path / "wechat-state"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "wechat-getupdates.json").write_text(
        json.dumps({"get_updates_buf": "cursor-123"}, ensure_ascii=False),
        encoding="utf-8",
    )

    channel = WechatChannel(
        bus=MessageBus(),
        config={"bot_token": "bot-token", "state_dir": str(state_dir)},
    )
    # State load moved out of __init__ (it does filesystem IO that would block
    # the async path); mirror start() by loading explicitly here.
    channel._load_state()

    assert channel._get_updates_buf == "cursor-123"


def test_auth_state_is_loaded_from_disk(tmp_path: Path):
    from app.channels.wechat import WechatChannel

    state_dir = tmp_path / "wechat-state"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "wechat-auth.json").write_text(
        json.dumps({"status": "confirmed", "bot_token": "saved-token", "ilink_bot_id": "bot-1"}, ensure_ascii=False),
        encoding="utf-8",
    )

    channel = WechatChannel(
        bus=MessageBus(),
        config={"state_dir": str(state_dir), "qrcode_login_enabled": True},
    )
    # State load moved out of __init__ (it does filesystem IO that would block
    # the async path); mirror start() by loading explicitly here.
    channel._load_state()

    assert channel._bot_token == "saved-token"
    assert channel._ilink_bot_id == "bot-1"


def test_qrcode_login_binds_and_persists_auth_state(monkeypatch, tmp_path: Path):
    from app.channels.wechat import WechatChannel

    async def go():
        get_calls: list[dict[str, Any]] = []

        def _client_factory(*args, **kwargs):
            return _MockAsyncClient(
                get_calls=get_calls,
                get_responses=[
                    {"qrcode": "qr-123", "qrcode_img_content": "https://example.com/qr.png"},
                    {"status": "confirmed", "bot_token": "bound-token", "ilink_bot_id": "bot-99"},
                ],
                **kwargs,
            )

        monkeypatch.setattr("app.channels.wechat.httpx.AsyncClient", _client_factory)

        state_dir = tmp_path / "wechat-state"
        channel = WechatChannel(
            bus=MessageBus(),
            config={
                "state_dir": str(state_dir),
                "qrcode_login_enabled": True,
                "qrcode_poll_interval": 0.01,
                "qrcode_poll_timeout": 1,
            },
        )

        ok = await channel._ensure_authenticated()

        assert ok is True
        assert channel._bot_token == "bound-token"
        assert channel._ilink_bot_id == "bot-99"
        assert get_calls[0]["url"].endswith("/ilink/bot/get_bot_qrcode")
        assert get_calls[1]["url"].endswith("/ilink/bot/get_qrcode_status")

        auth_state = json.loads((state_dir / "wechat-auth.json").read_text(encoding="utf-8"))
        assert auth_state["status"] == "confirmed"
        assert auth_state["bot_token"] == "bound-token"
        assert auth_state["ilink_bot_id"] == "bot-99"
        assert ((state_dir / "wechat-auth.json").stat().st_mode & 0o777) == 0o600

    _run(go())


def test_save_auth_state_tightens_preexisting_loose_file(tmp_path: Path):
    """A world-readable auth file is replaced by an owner-only one, atomically.

    The bot_token must never be observable at loose permissions: the atomic
    0o600-temp + ``Path.replace`` path swaps in a fresh owner-only inode rather
    than truncating the existing 0o644 file in place. Seeding the destination at
    0o644 first means a regression back to ``write_text`` + late ``chmod`` would
    leave a detectable window (and, here, the temp-file artifact behind).
    """
    from app.channels.wechat import WechatChannel

    state_dir = tmp_path / "wechat-state"
    state_dir.mkdir(parents=True, exist_ok=True)
    auth_path = state_dir / "wechat-auth.json"
    auth_path.write_text(json.dumps({"status": "pending"}), encoding="utf-8")
    auth_path.chmod(0o644)

    channel = WechatChannel(
        bus=MessageBus(),
        config={"state_dir": str(state_dir), "qrcode_login_enabled": True},
    )
    channel._save_auth_state(status="confirmed", bot_token="bound-token", ilink_bot_id="bot-1")

    assert (auth_path.stat().st_mode & 0o777) == 0o600
    assert json.loads(auth_path.read_text(encoding="utf-8"))["bot_token"] == "bound-token"
    # Atomic write leaves no temp-file residue behind.
    assert list(state_dir.glob("*.tmp")) == []


def test_save_auth_state_chmod_failure_is_logged_not_warned(tmp_path: Path, caplog):
    """A chmod failure on a perms-less filesystem must not look like a persist failure.

    With the post-replace chmod split into its own try/except, a chmod ``OSError``
    is logged at debug while the JSON is genuinely on disk — operators must not see
    the misleading ``failed to persist`` warning that the shared try/except produced.
    """
    from app.channels.wechat import WechatChannel

    state_dir = tmp_path / "wechat-state"
    channel = WechatChannel(
        bus=MessageBus(),
        config={"state_dir": str(state_dir), "qrcode_login_enabled": True},
    )

    real_chmod = Path.chmod

    def chmod_spy(self: Path, mode: int, *args, **kwargs):
        if self.suffix == ".json":
            raise OSError("chmod unsupported on this filesystem")
        return real_chmod(self, mode, *args, **kwargs)

    with caplog.at_level(logging.DEBUG, logger="app.channels.wechat"), mock.patch.object(Path, "chmod", chmod_spy):
        channel._save_auth_state(status="confirmed", bot_token="bound-token")

    auth_path = state_dir / "wechat-auth.json"
    assert json.loads(auth_path.read_text(encoding="utf-8"))["bot_token"] == "bound-token"
    messages = [record.getMessage() for record in caplog.records]
    assert any("unable to chmod auth state" in message for message in messages)
    assert not any("failed to persist auth state" in message for message in messages)
