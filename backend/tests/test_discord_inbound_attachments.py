"""Discord inbound attachment handling (file-only messages + receive_file)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.channels.discord import DiscordChannel
from app.channels.message_bus import INBOUND_FILE_CONTENT_KEY, InboundMessage, InboundMessageType, MessageBus


def _attachment(**overrides):
    base = SimpleNamespace(
        id=9001,
        filename="report.pdf",
        url="https://cdn.discordapp.com/attachments/1/2/report.pdf?ex=abc",
        content_type="application/pdf",
        size=4,
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def _make_discord_message(text: str = "", *, attachments=None):
    return SimpleNamespace(
        id=111,
        content=text,
        author=SimpleNamespace(id=123, bot=False, display_name="alice"),
        guild=SimpleNamespace(id=321),
        channel=SimpleNamespace(id=456),
        attachments=attachments if attachments is not None else [],
        add_reaction=AsyncMock(),
    )


async def _noop(*_args, **_kwargs):
    return None


def _ready_channel(bus: MessageBus | None = None) -> DiscordChannel:
    channel = DiscordChannel(bus=bus or MessageBus(), config={"bot_token": "discord-bot-token"})
    channel._running = True
    channel._client = SimpleNamespace(user=SimpleNamespace(id=999, mention="<@999>"))
    channel._discord_module = SimpleNamespace(Thread=type("FakeThread", (), {}))
    channel._main_loop = asyncio.get_running_loop()
    channel._start_typing = _noop
    channel._add_reaction = _noop
    return channel


@pytest.mark.asyncio
async def test_file_only_message_publishes_inbound_files() -> None:
    bus = MessageBus()
    channel = _ready_channel(bus)

    await channel._on_message(_make_discord_message("", attachments=[_attachment()]))

    inbound = await asyncio.wait_for(bus.get_inbound(), timeout=5)
    bus.inbound_task_done()
    assert inbound.text == ""
    assert inbound.msg_type == InboundMessageType.CHAT
    assert len(inbound.files) == 1
    assert inbound.files[0]["filename"] == "report.pdf"
    assert inbound.files[0]["type"] == "file"
    assert inbound.files[0]["url"].startswith("https://cdn.discordapp.com/")


@pytest.mark.asyncio
async def test_captioned_attachment_publishes_text_and_files() -> None:
    bus = MessageBus()
    channel = _ready_channel(bus)

    await channel._on_message(_make_discord_message("please review", attachments=[_attachment(filename="photo.png", content_type="image/png")]))

    inbound = await asyncio.wait_for(bus.get_inbound(), timeout=5)
    bus.inbound_task_done()
    assert inbound.text == "please review"
    assert inbound.files[0]["filename"] == "photo.png"
    assert inbound.files[0]["type"] == "image"


@pytest.mark.asyncio
async def test_empty_message_without_attachments_still_dropped() -> None:
    bus = MessageBus()
    channel = _ready_channel(bus)

    await channel._on_message(_make_discord_message(""))

    assert bus.inbound_queue.empty()


@pytest.mark.asyncio
async def test_mention_only_skips_file_without_mention() -> None:
    bus = MessageBus()
    channel = _ready_channel(bus)
    channel._mention_only = True

    await channel._on_message(_make_discord_message("", attachments=[_attachment()]))

    assert bus.inbound_queue.empty()


@pytest.mark.asyncio
async def test_mention_with_file_only_caption_still_publishes() -> None:
    bus = MessageBus()
    channel = _ready_channel(bus)
    channel._mention_only = True
    # Avoid discord.py ChannelType / HTTPException stubs: fall back to channel replies.
    channel._create_thread = AsyncMock(return_value=None)

    await channel._on_message(_make_discord_message("<@999>", attachments=[_attachment()]))

    inbound = await asyncio.wait_for(bus.get_inbound(), timeout=5)
    bus.inbound_task_done()
    assert inbound.text == ""
    assert inbound.files[0]["filename"] == "report.pdf"


class TestDiscordExtractInboundFiles:
    def test_extracts_image_and_document_descriptors(self):
        message = _make_discord_message(
            "x",
            attachments=[
                _attachment(id=1, filename="photo.png", content_type="image/png", size=8),
                _attachment(id=2, filename="notes.txt", content_type="text/plain", size=2, url="https://cdn.discordapp.com/attachments/1/2/notes.txt"),
                _attachment(id=3, filename="missing-url.bin", url=""),
            ],
        )
        files = DiscordChannel._extract_inbound_files(message)
        assert [item["filename"] for item in files] == ["photo.png", "notes.txt"]
        assert files[0]["type"] == "image"
        assert files[1]["type"] == "file"

    def test_rejects_upload_staging_filename(self):
        files = DiscordChannel._extract_inbound_files(_make_discord_message("", attachments=[_attachment(id=7, filename=".upload-hidden.part")]))
        assert files[0]["filename"] == "discord-file-7.bin"


class TestDiscordReceiveFile:
    @pytest.mark.asyncio
    async def test_downloads_bytes_with_bot_token_and_strips_url(self, monkeypatch):
        from app.channels import discord as discord_mod

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

        monkeypatch.setattr(discord_mod.httpx, "AsyncClient", _FakeAsyncClient)

        channel = DiscordChannel(MessageBus(), {"bot_token": "discord-bot-token"})
        content = await channel._download_attachment(
            "https://cdn.discordapp.com/attachments/1/2/report.pdf",
            "discord-bot-token",
        )
        assert content == b"data"
        assert seen["method"] == "GET"
        assert seen["authorization"] == "Bot discord-bot-token"
        assert seen["accept_encoding"] == "identity"

        channel2 = DiscordChannel(MessageBus(), {"bot_token": "discord-bot-token"})

        async def fake_download(url: str, token: str | None) -> bytes | None:
            assert token == "discord-bot-token"
            assert "report.pdf" in url
            return b"data"

        channel2._download_attachment = fake_download  # type: ignore[method-assign]
        msg = InboundMessage(
            channel_name="discord",
            chat_id="456",
            user_id="123",
            text="caption",
            files=[
                {
                    "type": "file",
                    "file_id": "9001",
                    "filename": "report.pdf",
                    "mime_type": "application/pdf",
                    "size": 4,
                    "url": "https://cdn.discordapp.com/attachments/1/2/report.pdf",
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

    @pytest.mark.asyncio
    async def test_missing_url_clears_file_and_notices(self):
        channel = DiscordChannel(MessageBus(), {"bot_token": "discord-bot-token"})
        msg = InboundMessage(
            channel_name="discord",
            chat_id="456",
            user_id="123",
            text="caption",
            files=[
                {
                    "type": "file",
                    "filename": "report.pdf",
                    "mime_type": "application/pdf",
                }
            ],
        )
        result = await channel.receive_file(msg, "thread-1")
        assert result.files == []
        assert "download unavailable" in result.text

    @pytest.mark.asyncio
    async def test_bot_token_not_sent_to_foreign_host(self, monkeypatch):
        from app.channels import discord as discord_mod

        seen: dict[str, str] = {}

        class _FakeStreamResponse:
            def __init__(self):
                self.headers = {"content-encoding": "identity"}

            def raise_for_status(self) -> None:
                return None

            async def aiter_raw(self):
                yield b"ok"

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
                seen["authorization"] = kwargs.get("headers", {}).get("Authorization", "")
                return _FakeStreamContext()

        monkeypatch.setattr(discord_mod.httpx, "AsyncClient", _FakeAsyncClient)
        channel = DiscordChannel(MessageBus(), {"bot_token": "discord-bot-token"})
        content = await channel._download_attachment(
            "https://evil.example/attachments/1/2/report.pdf",
            "discord-bot-token",
        )
        assert content == b"ok"
        assert seen["authorization"] == ""

    @pytest.mark.asyncio
    async def test_content_encoding_refusal_is_download_failed(self, monkeypatch):
        from app.channels import discord as discord_mod

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

        monkeypatch.setattr(discord_mod.httpx, "AsyncClient", _FakeAsyncClient)
        channel = DiscordChannel(MessageBus(), {"bot_token": "discord-bot-token"})
        msg = InboundMessage(
            channel_name="discord",
            chat_id="456",
            user_id="123",
            text="caption",
            files=[
                {
                    "type": "file",
                    "filename": "report.pdf",
                    "mime_type": "application/pdf",
                    "size": 4,
                    "url": "https://cdn.discordapp.com/attachments/1/2/report.pdf",
                }
            ],
        )
        result = await channel.receive_file(msg, "thread-1")
        assert result.files == []
        assert "download failed" in result.text
        assert "download limit" not in result.text


class TestDiscordCdnHostGate:
    def test_allows_discord_cdn_hosts(self):
        assert DiscordChannel._is_discord_cdn_url("https://cdn.discordapp.com/attachments/1/2/x")
        assert DiscordChannel._is_discord_cdn_url("https://media.discordapp.net/attachments/1/2/x")
        assert DiscordChannel._is_discord_cdn_url("https://discord.com/api/attachments/1")

    def test_rejects_lookalike_hosts(self):
        assert not DiscordChannel._is_discord_cdn_url("https://evil.example/x")
        assert not DiscordChannel._is_discord_cdn_url("https://cdn.discordapp.com.evil.io/x")
        assert DiscordChannel._is_discord_cdn_url("http://cdn.discordapp.com/x")  # host-only gate


@pytest.mark.asyncio
@pytest.mark.parametrize("rejection", ["declared", "stream", "returned"])
async def test_size_limit_notice_tracks_enforced_cap(monkeypatch, rejection):
    from app.channels import discord as discord_mod

    limit = 2 * 1024 * 1024
    monkeypatch.setattr(discord_mod, "DISCORD_MAX_INBOUND_FILE_BYTES", limit)
    channel = DiscordChannel(MessageBus(), {"bot_token": "discord-bot-token"})
    download = AsyncMock(return_value=None if rejection == "stream" else b"x" * (limit + 1))
    monkeypatch.setattr(channel, "_download_attachment", download)
    msg = InboundMessage(
        channel_name="discord",
        chat_id="456",
        user_id="123",
        text="caption",
        files=[{"filename": "report.pdf", "size": limit + 1 if rejection == "declared" else 4, "url": "https://cdn.discordapp.com/report.pdf"}],
    )

    result = await channel.receive_file(msg, "thread-1")

    assert result.files == []
    assert result.text == "caption\n\n[Discord attachment unavailable: report.pdf (exceeds the 2 MiB download limit)]"
    if rejection == "declared":
        download.assert_not_awaited()
    else:
        download.assert_awaited_once()


@pytest.mark.asyncio
async def test_default_size_limit_notice_shows_25_mib(monkeypatch):
    channel = DiscordChannel(MessageBus(), {"bot_token": "discord-bot-token"})
    download = AsyncMock()
    monkeypatch.setattr(channel, "_download_attachment", download)
    msg = InboundMessage(
        channel_name="discord",
        chat_id="456",
        user_id="123",
        text="",
        files=[{"filename": "large.pdf", "size": 26 * 1024 * 1024, "url": "https://cdn.discordapp.com/large.pdf"}],
    )

    result = await channel.receive_file(msg, "thread-1")

    assert result.text == "[Discord attachment unavailable: large.pdf (exceeds the 25 MiB download limit)]"
    assert result.files == []
    download.assert_not_awaited()
