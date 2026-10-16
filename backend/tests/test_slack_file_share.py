"""Slack file_share / subtype handling for inbound uploads."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.channels.message_bus import INBOUND_FILE_CONTENT_KEY, InboundMessage, MessageBus


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _immediate_loop():
    loop = MagicMock()
    loop.is_running.return_value = True
    loop.call_soon_threadsafe.side_effect = lambda callback, *args: callback(*args)
    return loop


def _submit_coro(coro, loop, **_kwargs):
    coro.close()
    return True


def _file_share_event(**overrides):
    event = {
        "type": "message",
        "subtype": "file_share",
        "user": "U123456",
        "text": "please review",
        "channel": "C123",
        "ts": "1710000000.000100",
        "files": [
            {
                "id": "FABC",
                "name": "report.pdf",
                "title": "report.pdf",
                "mimetype": "application/pdf",
                "filetype": "pdf",
                "size": 4,
                "url_private": "https://files.slack.com/files-pri/T-F/report.pdf",
                "url_private_download": "https://files.slack.com/files-pri/T-F/download/report.pdf",
            }
        ],
    }
    event.update(overrides)
    return event


class TestSlackFileShareSubtype:
    def _channel(self):
        from app.channels.slack import SlackChannel

        bus = MessageBus()
        bus.publish_inbound = AsyncMock()
        channel = SlackChannel(bus=bus, config={"bot_user_id": "UBOT"})
        channel._loop = _immediate_loop()
        channel._add_reaction = MagicMock()
        channel._send_running_reply = MagicMock()
        return bus, channel

    def test_file_share_with_caption_publishes_inbound_files(self):
        bus, channel = self._channel()
        with patch("app.channels.slack.asyncio.run_coroutine_threadsafe", side_effect=_submit_coro):
            channel._handle_message_event(_file_share_event())

        channel._add_reaction.assert_called_once()
        inbound = bus.get_inbound_nowait()
        assert inbound.text == "please review"
        assert len(inbound.files) == 1
        assert inbound.files[0]["filename"] == "report.pdf"
        assert inbound.files[0]["type"] == "file"
        assert inbound.files[0]["url_private_download"].endswith("/download/report.pdf")

    def test_file_share_without_caption_still_publishes(self):
        bus, channel = self._channel()
        with patch("app.channels.slack.asyncio.run_coroutine_threadsafe", side_effect=_submit_coro):
            channel._handle_message_event(_file_share_event(text=""))

        inbound = bus.get_inbound_nowait()
        assert inbound.text == ""
        assert inbound.files[0]["filename"] == "report.pdf"

    @pytest.mark.parametrize(
        "subtype",
        ["message_changed", "message_deleted", "channel_join", "bot_message", "thread_broadcast"],
    )
    def test_non_file_share_subtypes_are_still_dropped(self, subtype):
        bus, channel = self._channel()
        with patch("app.channels.slack.asyncio.run_coroutine_threadsafe", side_effect=_submit_coro):
            channel._handle_message_event(
                {
                    "type": "message",
                    "subtype": subtype,
                    "user": "U123456",
                    "text": "should not publish",
                    "channel": "C123",
                    "ts": "1710000000.000100",
                }
            )

        channel._add_reaction.assert_not_called()
        assert bus.inbound_queue.empty()

    def test_bot_id_still_dropped_even_for_file_share(self):
        bus, channel = self._channel()
        with patch("app.channels.slack.asyncio.run_coroutine_threadsafe", side_effect=_submit_coro):
            channel._handle_message_event(_file_share_event(bot_id="B123"))

        channel._add_reaction.assert_not_called()
        assert bus.inbound_queue.empty()

    def test_plain_message_without_subtype_still_works(self):
        bus, channel = self._channel()
        with patch("app.channels.slack.asyncio.run_coroutine_threadsafe", side_effect=_submit_coro):
            channel._handle_message_event(
                {
                    "user": "U123456",
                    "text": "hello",
                    "channel": "C123",
                    "ts": "1710000000.000100",
                }
            )

        inbound = bus.get_inbound_nowait()
        assert inbound.text == "hello"
        assert inbound.files == []


class TestSlackExtractInboundFiles:
    def test_extracts_image_and_document_descriptors(self):
        from app.channels.slack import SlackChannel

        files = SlackChannel._extract_inbound_files(
            {
                "files": [
                    {
                        "id": "FIMG",
                        "name": "photo.png",
                        "mimetype": "image/png",
                        "filetype": "png",
                        "size": 8,
                        "url_private_download": "https://files.slack.com/files-pri/T-F/download/photo.png",
                    },
                    {
                        "id": "FDOC",
                        "name": "notes.txt",
                        "mimetype": "text/plain",
                        "size": 2,
                        "url_private_download": "https://files.slack.com/files-pri/T-F/download/notes.txt",
                    },
                    {
                        "id": "FBAD",
                        "name": "missing-url.bin",
                        "mimetype": "application/octet-stream",
                    },
                ]
            }
        )

        assert [item["filename"] for item in files] == ["photo.png", "notes.txt"]
        assert files[0]["type"] == "image"
        assert files[1]["type"] == "file"

    def test_rejects_upload_staging_filename(self):
        from app.channels.slack import SlackChannel

        files = SlackChannel._extract_inbound_files(
            {
                "files": [
                    {
                        "id": "F1",
                        "name": ".upload-hidden.part",
                        "mimetype": "application/pdf",
                        "url_private_download": "https://files.slack.com/files-pri/T-F/download/x",
                    }
                ]
            }
        )

        assert files[0]["filename"] == "slack-file-F1.bin"


class TestSlackReceiveFile:
    def test_downloads_bytes_with_bearer_token_and_strips_url(self, monkeypatch):
        from app.channels import slack as slack_mod
        from app.channels.slack import SlackChannel

        seen: dict[str, str] = {}

        class _FakeStreamResponse:
            def __init__(self):
                self.headers = {"content-encoding": "identity"}

            def raise_for_status(self) -> None:
                return None

            async def aiter_raw(self):
                yield b"da"
                yield b"ta"

        class _FakeStreamContext:
            async def __aenter__(self):
                return _FakeStreamResponse()

            async def __aexit__(self, *exc_info):
                return False

        class _FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc_info):
                return False

            def stream(self, method: str, url: str, **kwargs):
                seen["method"] = method
                seen["url"] = url
                seen["authorization"] = kwargs.get("headers", {}).get("Authorization", "")
                seen["accept_encoding"] = kwargs.get("headers", {}).get("Accept-Encoding", "")
                return _FakeStreamContext()

        monkeypatch.setattr(slack_mod.httpx, "AsyncClient", _FakeAsyncClient)

        async def go():
            channel = SlackChannel(MessageBus(), {"bot_token": "xoxb-test"})
            channel._web_client = SimpleNamespace(token="xoxb-test")
            content = await channel._download_private_file(
                "https://files.slack.com/files-pri/T-F/download/report.pdf",
                "xoxb-test",
            )
            assert content == b"data"
            assert seen["method"] == "GET"
            assert seen["authorization"] == "Bearer xoxb-test"
            assert seen["accept_encoding"] == "identity"

            channel2 = SlackChannel(MessageBus(), {"bot_token": "xoxb-test"})
            channel2._web_client = SimpleNamespace(token="xoxb-test")

            async def fake_download(url: str, token: str, *, max_bytes: int = 0) -> bytes | None:
                assert token == "xoxb-test"
                assert url.endswith("/download/report.pdf")
                assert max_bytes > 0
                return b"data"

            channel2._download_private_file = fake_download  # type: ignore[method-assign]
            msg = InboundMessage(
                channel_name="slack",
                chat_id="C123",
                user_id="U123",
                text="caption",
                files=[
                    {
                        "type": "file",
                        "file_id": "FABC",
                        "filename": "report.pdf",
                        "mime_type": "application/pdf",
                        "size": 4,
                        "url_private_download": "https://files.slack.com/files-pri/T-F/download/report.pdf",
                    }
                ],
            )
            result = await channel2.receive_file(msg, "thread-1")
            assert result.text == "caption"
            assert result.files == [
                {
                    "type": "file",
                    "filename": "report.pdf",
                    "mime_type": "application/pdf",
                    "size": 4,
                    INBOUND_FILE_CONTENT_KEY: b"data",
                }
            ]

        _run(go())

    def test_missing_token_clears_files_and_notices(self):
        from app.channels.slack import SlackChannel

        channel = SlackChannel(MessageBus(), {})
        channel._web_client = None
        msg = InboundMessage(
            channel_name="slack",
            chat_id="C123",
            user_id="U123",
            text="caption",
            files=[
                {
                    "type": "file",
                    "filename": "report.pdf",
                    "mime_type": "application/pdf",
                    "url_private_download": "https://files.slack.com/files-pri/T-F/download/report.pdf",
                }
            ],
        )

        result = _run(channel.receive_file(msg, "thread-1"))

        assert result.files == []
        assert "bot token missing" in result.text

    def test_rejects_non_slack_host_without_fetching(self):
        from app.channels.slack import SlackChannel

        channel = SlackChannel(MessageBus(), {"bot_token": "xoxb-test"})
        channel._web_client = SimpleNamespace(token="xoxb-test")
        called = {"download": False}

        async def fake_download(url: str, token: str, *, max_bytes: int = 0) -> bytes | None:
            called["download"] = True
            return b"nope"

        channel._download_private_file = fake_download  # type: ignore[method-assign]
        msg = InboundMessage(
            channel_name="slack",
            chat_id="C123",
            user_id="U123",
            text="caption",
            files=[
                {
                    "type": "file",
                    "filename": "evil.pdf",
                    "mime_type": "application/pdf",
                    "size": 4,
                    "url_private_download": "https://evil.example/report.pdf",
                }
            ],
        )
        result = _run(channel.receive_file(msg, "thread-1"))
        assert called["download"] is False
        assert result.files == []
        assert "download unavailable" in result.text

    def test_content_encoding_refusal_is_download_failed(self, monkeypatch):
        from app.channels import slack as slack_mod
        from app.channels.slack import SlackChannel

        class _FakeStreamResponse:
            def __init__(self):
                self.headers = {"content-encoding": "gzip"}

            def raise_for_status(self) -> None:
                return None

            async def aiter_raw(self):
                if False:
                    yield b""

        class _FakeStreamContext:
            async def __aenter__(self):
                return _FakeStreamResponse()

            async def __aexit__(self, *exc_info):
                return False

        class _FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc_info):
                return False

            def stream(self, method: str, url: str, **kwargs):
                return _FakeStreamContext()

        monkeypatch.setattr(slack_mod.httpx, "AsyncClient", _FakeAsyncClient)

        channel = SlackChannel(MessageBus(), {"bot_token": "xoxb-test"})
        channel._web_client = SimpleNamespace(token="xoxb-test")
        msg = InboundMessage(
            channel_name="slack",
            chat_id="C123",
            user_id="U123",
            text="caption",
            files=[
                {
                    "type": "file",
                    "filename": "report.pdf",
                    "mime_type": "application/pdf",
                    "size": 4,
                    "url_private_download": "https://files.slack.com/files-pri/T-F/download/report.pdf",
                }
            ],
        )
        result = _run(channel.receive_file(msg, "thread-1"))
        assert result.files == []
        assert "download failed" in result.text
        assert "exceeds the download limit" not in result.text

    def test_aggregate_message_byte_cap(self):
        from app.channels import slack as slack_mod
        from app.channels.slack import SlackChannel

        channel = SlackChannel(MessageBus(), {"bot_token": "xoxb-test"})
        channel._web_client = SimpleNamespace(token="xoxb-test")
        payloads = {
            "https://files.slack.com/a.bin": b"a" * 10,
            "https://files.slack.com/b.bin": b"b" * 10,
        }

        async def fake_download(url: str, token: str, *, max_bytes: int = 0) -> bytes | None:
            body = payloads[url]
            if len(body) > max_bytes:
                return None
            return body

        channel._download_private_file = fake_download  # type: ignore[method-assign]
        # Shrink aggregate so two tiny files exceed it.
        monkey_limit = 15
        original = slack_mod.SLACK_MAX_INBOUND_MESSAGE_BYTES
        slack_mod.SLACK_MAX_INBOUND_MESSAGE_BYTES = monkey_limit
        try:
            msg = InboundMessage(
                channel_name="slack",
                chat_id="C123",
                user_id="U123",
                text="caption",
                files=[
                    {
                        "type": "file",
                        "filename": "a.bin",
                        "mime_type": "application/octet-stream",
                        "size": 10,
                        "url_private_download": "https://files.slack.com/a.bin",
                    },
                    {
                        "type": "file",
                        "filename": "b.bin",
                        "mime_type": "application/octet-stream",
                        "size": 10,
                        "url_private_download": "https://files.slack.com/b.bin",
                    },
                ],
            )
            result = _run(channel.receive_file(msg, "thread-1"))
        finally:
            slack_mod.SLACK_MAX_INBOUND_MESSAGE_BYTES = original

        assert len(result.files) == 1
        assert result.files[0]["filename"] == "a.bin"
        assert "message download limit" in result.text


class TestSlackPrivateFileUrlAllowlist:
    def test_allows_files_slack_com_https(self):
        from app.channels.slack import SlackChannel

        assert SlackChannel._is_allowed_private_file_url("https://files.slack.com/files-pri/T-F/download/x")
        assert SlackChannel._is_allowed_private_file_url("https://cdn.files.slack.com/files-pri/T-F/download/x")

    def test_rejects_http_and_foreign_hosts(self):
        from app.channels.slack import SlackChannel

        assert not SlackChannel._is_allowed_private_file_url("http://files.slack.com/files-pri/T-F/download/x")
        assert not SlackChannel._is_allowed_private_file_url("https://evil.example/x")
        assert not SlackChannel._is_allowed_private_file_url("https://notfiles.slack.com.evil.io/x")
