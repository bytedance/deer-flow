"""Comprehensive tests for DingTalk channel functionality.

This test module covers:
- Token management (access token retrieval and caching)
- Message parsing (text, rich text, images, files)
- User authorization
- Message sending with retry logic
- File upload handling
- Running reply mechanism
- Stream Push event handling
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.channels.base import Channel
from app.channels.dingtalk import DINGTALK_API_BASE, DINGTALK_AUTH_BASE, DingTalkChannel
from app.channels.message_bus import InboundMessage, InboundMessageType, MessageBus, OutboundMessage, ResolvedAttachment


def _run(coro):
    """Run an async coroutine synchronously."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# DingTalk Channel - Initialization tests
# ---------------------------------------------------------------------------


class TestDingTalkChannelInit:
    """Test DingTalk channel initialization."""

    def test_init_with_config(self):
        """Channel initializes with provided configuration."""
        bus = MessageBus()
        config = {
            "app_key": "test_key",
            "app_secret": "test_secret",
            "allowed_users": ["user1", "user2"],
        }
        ch = DingTalkChannel(bus, config)

        assert ch.name == "dingtalk"
        assert ch.bus == bus
        assert ch.config == config
        assert ch._allowed_users == {"user1", "user2"}

    def test_init_empty_allowed_users(self):
        """Empty allowed_users means all users are allowed."""
        bus = MessageBus()
        config = {"app_key": "key", "app_secret": "secret"}
        ch = DingTalkChannel(bus, config)

        assert ch._allowed_users == set()

    def test_init_missing_credentials(self):
        """Channel can be initialized without credentials."""
        bus = MessageBus()
        ch = DingTalkChannel(bus, config={})

        assert ch.config == {}


# ---------------------------------------------------------------------------
# DingTalk Channel - Token Management tests
# ---------------------------------------------------------------------------


class TestDingTalkTokenManagement:
    """Test access token retrieval and caching."""

    def test_get_access_token_success(self):
        """Successfully retrieve access token from DingTalk API."""
        bus = MessageBus()
        ch = DingTalkChannel(bus, config={"app_key": "key", "app_secret": "secret"})
        ch._app_key = "key"
        ch._app_secret = "secret"

        async def go():
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "errcode": 0,
                "access_token": "test_token_123",
                "expires_in": 7200,
            }
            mock_response.raise_for_status = MagicMock()

            with patch("httpx.AsyncClient") as mock_client_class:
                mock_client = AsyncMock()
                mock_client.__aenter__.return_value = mock_client
                mock_client.__aexit__.return_value = None
                mock_client.post = AsyncMock(return_value=mock_response)
                mock_client_class.return_value = mock_client

                token = await ch._get_access_token()

            assert token == "test_token_123"
            assert ch._access_token == "test_token_123"
            assert ch._token_expires_at > 0

        _run(go())

    def test_get_access_token_cached(self):
        """Return cached token if not expired."""
        bus = MessageBus()
        ch = DingTalkChannel(bus, config={})
        ch._access_token = "cached_token"
        ch._token_expires_at = 9999999999.0  # Far future
        ch._app_key = "key"
        ch._app_secret = "secret"

        async def go():
            # Should not make any HTTP request
            token = await ch._get_access_token()
            assert token == "cached_token"

        _run(go())

    def test_get_access_token_refresh_when_expiring_soon(self):
        """Refresh token when it's about to expire (within 5 minutes)."""
        import time

        bus = MessageBus()
        ch = DingTalkChannel(bus, config={})
        ch._access_token = "old_token"
        ch._token_expires_at = time.time() + 100  # Expires in ~1.5 minutes
        ch._app_key = "key"
        ch._app_secret = "secret"

        async def go():
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "errcode": 0,
                "access_token": "new_token",
                "expires_in": 7200,
            }
            mock_response.raise_for_status = MagicMock()

            with patch("httpx.AsyncClient") as mock_client_class:
                mock_client = AsyncMock()
                mock_client.__aenter__.return_value = mock_client
                mock_client.__aexit__.return_value = None
                mock_client.post = AsyncMock(return_value=mock_response)
                mock_client_class.return_value = mock_client

                token = await ch._get_access_token()

            assert token == "new_token"
            assert ch._access_token == "new_token"

        _run(go())

    def test_get_access_token_api_error(self):
        """Handle API error when getting access token."""
        bus = MessageBus()
        ch = DingTalkChannel(bus, config={})
        ch._app_key = "key"
        ch._app_secret = "secret"

        async def go():
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "errcode": 40014,
                "errmsg": "invalid appkey",
            }
            mock_response.raise_for_status = MagicMock()

            with patch("httpx.AsyncClient") as mock_client_class:
                mock_client = AsyncMock()
                mock_client.__aenter__.return_value = mock_client
                mock_client.__aexit__.return_value = None
                mock_client.post = AsyncMock(return_value=mock_response)
                mock_client_class.return_value = mock_client

                token = await ch._get_access_token()

            assert token is None

        _run(go())

    def test_get_access_token_network_error(self):
        """Handle network error when getting access token."""
        bus = MessageBus()
        ch = DingTalkChannel(bus, config={})
        ch._app_key = "key"
        ch._app_secret = "secret"

        async def go():
            with patch("httpx.AsyncClient") as mock_client_class:
                mock_client = AsyncMock()
                mock_client.__aenter__.return_value = mock_client
                mock_client.__aexit__.return_value = None
                mock_client.post = AsyncMock(side_effect=Exception("Network error"))
                mock_client_class.return_value = mock_client

                token = await ch._get_access_token()

            assert token is None

        _run(go())


# ---------------------------------------------------------------------------
# DingTalk Channel - Message Parsing tests
# ---------------------------------------------------------------------------


class TestDingTalkMessageParsing:
    """Test message parsing from DingTalk events."""

    def test_parse_text_message(self):
        """Parse a simple text message event."""
        bus = MessageBus()
        ch = DingTalkChannel(bus, config={})

        event_data = {
            "message": {
                "messageId": "msg123",
                "msgType": "text",
                "content": {"content": "Hello, bot!"},
            },
            "sender": {"userId": "user1"},
            "chat": {"chatId": "chat1", "chatType": "single"},
        }

        async def go():
            await ch._handle_message_event_raw(event_data)

            msg = await asyncio.wait_for(bus.get_inbound(), timeout=2)

            assert msg.channel_name == "dingtalk"
            assert msg.chat_id == "chat1"
            assert msg.user_id == "user1"
            assert msg.text == "Hello, bot!"
            assert msg.msg_type == InboundMessageType.CHAT
            assert msg.topic_id == "chat1"

        _run(go())

    def test_parse_command_message(self):
        """Parse a command message (starts with /)."""
        bus = MessageBus()
        ch = DingTalkChannel(bus, config={})
        ch._app_key = "key"
        ch._app_secret = "secret"

        event_data = {
            "message": {
                "messageId": "msg124",
                "msgType": "text",
                "content": {"content": "/help"},
            },
            "sender": {"userId": "user1"},
            "chat": {"chatId": "chat1", "chatType": "single"},
        }

        async def go():
            # Mock token retrieval
            with patch.object(ch, "_get_access_token", return_value="token"):
                with patch.object(ch, "_send_running_reply", new_callable=AsyncMock):
                    await ch._handle_message_event_raw(event_data)

                    msg = await asyncio.wait_for(bus.get_inbound(), timeout=2)

                    assert msg.msg_type == InboundMessageType.COMMAND
                    assert msg.text == "/help"

        _run(go())

    def test_parse_rich_text_message(self):
        """Parse a rich text message."""
        bus = MessageBus()
        ch = DingTalkChannel(bus, config={})
        ch._app_key = "key"
        ch._app_secret = "secret"

        event_data = {
            "message": {
                "messageId": "msg125",
                "msgType": "richText",
                "content": {
                    "richTextContent": [
                        {"type": "text", "text": "Hello "},
                        {"type": "mention", "text": "@user"},
                        {"type": "text", "text": " check this out"},
                    ]
                },
            },
            "sender": {"userId": "user1"},
            "chat": {"chatId": "chat1", "chatType": "group"},
        }

        async def go():
            with patch.object(ch, "_get_access_token", return_value="token"):
                with patch.object(ch, "_send_running_reply", new_callable=AsyncMock):
                    await ch._handle_message_event_raw(event_data)

                    msg = await asyncio.wait_for(bus.get_inbound(), timeout=2)

                    assert msg.text == "Hello  @user  check this out"

        _run(go())

    def test_parse_picture_message(self):
        """Parse a picture message."""
        bus = MessageBus()
        ch = DingTalkChannel(bus, config={})
        ch._app_key = "key"
        ch._app_secret = "secret"

        event_data = {
            "message": {
                "messageId": "msg126",
                "msgType": "picture",
                "content": {"downloadCode": "abc123"},
            },
            "sender": {"userId": "user1"},
            "chat": {"chatId": "chat1", "chatType": "single"},
        }

        async def go():
            with patch.object(ch, "_get_access_token", return_value="token"):
                with patch.object(ch, "_send_running_reply", new_callable=AsyncMock):
                    await ch._handle_message_event_raw(event_data)

                    msg = await asyncio.wait_for(bus.get_inbound(), timeout=2)

                    assert msg.text == "[Image]"

        _run(go())

    def test_parse_file_message(self):
        """Parse a file message."""
        bus = MessageBus()
        ch = DingTalkChannel(bus, config={})
        ch._app_key = "key"
        ch._app_secret = "secret"

        event_data = {
            "message": {
                "messageId": "msg127",
                "msgType": "file",
                "content": {"fileName": "report.pdf"},
            },
            "sender": {"userId": "user1"},
            "chat": {"chatId": "chat1", "chatType": "single"},
        }

        async def go():
            with patch.object(ch, "_get_access_token", return_value="token"):
                with patch.object(ch, "_send_running_reply", new_callable=AsyncMock):
                    await ch._handle_message_event_raw(event_data)

                    msg = await asyncio.wait_for(bus.get_inbound(), timeout=2)

                    assert msg.text == "[File: report.pdf]"

        _run(go())

    def test_parse_unknown_message_type(self):
        """Parse an unknown message type."""
        bus = MessageBus()
        ch = DingTalkChannel(bus, config={})
        ch._app_key = "key"
        ch._app_secret = "secret"

        event_data = {
            "message": {
                "messageId": "msg128",
                "msgType": "audio",
                "content": {},
            },
            "sender": {"userId": "user1"},
            "chat": {"chatId": "chat1", "chatType": "single"},
        }

        async def go():
            with patch.object(ch, "_get_access_token", return_value="token"):
                with patch.object(ch, "_send_running_reply", new_callable=AsyncMock):
                    await ch._handle_message_event_raw(event_data)

                    msg = await asyncio.wait_for(bus.get_inbound(), timeout=2)

                    assert msg.text == "[audio]"

        _run(go())

    def test_parse_empty_text_ignored(self):
        """Empty text messages are ignored."""
        bus = MessageBus()
        ch = DingTalkChannel(bus, config={})
        ch._app_key = "key"
        ch._app_secret = "secret"

        event_data = {
            "message": {
                "messageId": "msg129",
                "msgType": "text",
                "content": {"content": "   "},  # Whitespace only
            },
            "sender": {"userId": "user1"},
            "chat": {"chatId": "chat1", "chatType": "single"},
        }

        async def go():
            with patch.object(ch, "_get_access_token", return_value="token"):
                with patch.object(ch, "_send_running_reply", new_callable=AsyncMock):
                    await ch._handle_message_event_raw(event_data)

                    # No message should be published
                    with pytest.raises(asyncio.TimeoutError):
                        await asyncio.wait_for(bus.get_inbound(), timeout=0.5)

        _run(go())


# ---------------------------------------------------------------------------
# DingTalk Channel - User Authorization tests
# ---------------------------------------------------------------------------


class TestDingTalkUserAuthorization:
    """Test user authorization filtering."""

    def test_allowed_user_can_send_message(self):
        """Allowed user can send messages."""
        bus = MessageBus()
        ch = DingTalkChannel(bus, config={"allowed_users": ["user1", "user2"]})
        ch._app_key = "key"
        ch._app_secret = "secret"

        event_data = {
            "message": {
                "messageId": "msg130",
                "msgType": "text",
                "content": {"content": "Hello"},
            },
            "sender": {"userId": "user1"},
            "chat": {"chatId": "chat1", "chatType": "single"},
        }

        async def go():
            with patch.object(ch, "_get_access_token", return_value="token"):
                with patch.object(ch, "_send_running_reply", new_callable=AsyncMock):
                    await ch._handle_message_event_raw(event_data)

                    msg = await asyncio.wait_for(bus.get_inbound(), timeout=2)
                    assert msg.text == "Hello"

        _run(go())

    def test_non_allowed_user_message_ignored(self):
        """Messages from non-allowed users are ignored."""
        bus = MessageBus()
        ch = DingTalkChannel(bus, config={"allowed_users": ["user1"]})
        ch._app_key = "key"
        ch._app_secret = "secret"

        event_data = {
            "message": {
                "messageId": "msg131",
                "msgType": "text",
                "content": {"content": "Hello"},
            },
            "sender": {"userId": "user3"},  # Not in allowed list
            "chat": {"chatId": "chat1", "chatType": "single"},
        }

        async def go():
            await ch._handle_message_event_raw(event_data)

            # No message should be published
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(bus.get_inbound(), timeout=0.5)

        _run(go())

    def test_empty_allowed_users_allows_all(self):
        """Empty allowed_users list allows all users."""
        bus = MessageBus()
        ch = DingTalkChannel(bus, config={"allowed_users": []})
        ch._app_key = "key"
        ch._app_secret = "secret"

        event_data = {
            "message": {
                "messageId": "msg132",
                "msgType": "text",
                "content": {"content": "Hello"},
            },
            "sender": {"userId": "any_user"},
            "chat": {"chatId": "chat1", "chatType": "single"},
        }

        async def go():
            with patch.object(ch, "_get_access_token", return_value="token"):
                with patch.object(ch, "_send_running_reply", new_callable=AsyncMock):
                    await ch._handle_message_event_raw(event_data)

                    msg = await asyncio.wait_for(bus.get_inbound(), timeout=2)
                    assert msg.user_id == "any_user"

        _run(go())


# ---------------------------------------------------------------------------
# DingTalk Channel - Send Message tests
# ---------------------------------------------------------------------------


class TestDingTalkSendMessage:
    """Test message sending functionality."""

    def test_send_message_success(self):
        """Successfully send a message to DingTalk."""
        bus = MessageBus()
        ch = DingTalkChannel(bus, config={})
        ch._app_key = "key"
        ch._app_secret = "secret"

        async def go():
            mock_response = MagicMock()
            mock_response.json.return_value = {"code": "0"}
            mock_response.raise_for_status = MagicMock()

            with patch.object(ch, "_get_access_token", return_value="test_token"):
                with patch("httpx.AsyncClient") as mock_client_class:
                    mock_client = AsyncMock()
                    mock_client.__aenter__.return_value = mock_client
                    mock_client.__aexit__.return_value = None
                    mock_client.post = AsyncMock(return_value=mock_response)
                    mock_client_class.return_value = mock_client

                    msg = OutboundMessage(
                        channel_name="dingtalk",
                        chat_id="chat1",
                        thread_id="t1",
                        text="Hello from bot!",
                    )
                    await ch.send(msg)

                    # Verify the API call was made
                    mock_client.post.assert_called_once()

        _run(go())

    def test_send_message_with_thread_ts(self):
        """Send a threaded reply."""
        bus = MessageBus()
        ch = DingTalkChannel(bus, config={})
        ch._app_key = "key"
        ch._app_secret = "secret"

        async def go():
            mock_response = MagicMock()
            mock_response.json.return_value = {"code": "0"}
            mock_response.raise_for_status = MagicMock()

            with patch.object(ch, "_get_access_token", return_value="test_token"):
                with patch("httpx.AsyncClient") as mock_client_class:
                    mock_client = AsyncMock()
                    mock_client.__aenter__.return_value = mock_client
                    mock_client.__aexit__.return_value = None
                    mock_client.post = AsyncMock(return_value=mock_response)
                    mock_client_class.return_value = mock_client

                    msg = OutboundMessage(
                        channel_name="dingtalk",
                        chat_id="chat1",
                        thread_id="t1",
                        text="Reply",
                        thread_ts="msg123",
                    )
                    await ch.send(msg)

                    mock_client.post.assert_called_once()
                    call_args = mock_client.post.call_args
                    body = call_args[1]["json"]
                    assert body["replyToMsgId"] == "msg123"

        _run(go())

    def test_send_message_retry_on_failure(self):
        """Retry sending on transient errors."""
        bus = MessageBus()
        ch = DingTalkChannel(bus, config={})
        ch._app_key = "key"
        ch._app_secret = "secret"

        async def go():
            call_count = 0

            def mock_post(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count < 3:
                    raise Exception("Network error")
                return MagicMock(json=lambda: {"code": "0"}, raise_for_status=MagicMock())

            with patch.object(ch, "_get_access_token", return_value="test_token"):
                with patch("httpx.AsyncClient") as mock_client_class:
                    mock_client = AsyncMock()
                    mock_client.__aenter__.return_value = mock_client
                    mock_client.__aexit__.return_value = None
                    mock_client.post = AsyncMock(side_effect=mock_post)
                    mock_client_class.return_value = mock_client

                    msg = OutboundMessage(
                        channel_name="dingtalk",
                        chat_id="chat1",
                        thread_id="t1",
                        text="Hello",
                    )
                    await ch.send(msg)

                    assert call_count == 3  # 2 failures + 1 success

        _run(go())

    def test_send_message_fails_after_all_retries(self):
        """Raise error after all retries exhausted."""
        bus = MessageBus()
        ch = DingTalkChannel(bus, config={})
        ch._app_key = "key"
        ch._app_secret = "secret"

        async def go():
            with patch.object(ch, "_get_access_token", return_value="test_token"):
                with patch("httpx.AsyncClient") as mock_client_class:
                    mock_client = AsyncMock()
                    mock_client.__aenter__.return_value = mock_client
                    mock_client.__aexit__.return_value = None
                    mock_client.post = AsyncMock(side_effect=Exception("Permanent error"))
                    mock_client_class.return_value = mock_client

                    msg = OutboundMessage(
                        channel_name="dingtalk",
                        chat_id="chat1",
                        thread_id="t1",
                        text="Hello",
                    )
                    with pytest.raises(Exception, match="Permanent error"):
                        await ch.send(msg)

                    assert mock_client.post.call_count == 3

        _run(go())

    def test_send_message_no_token(self):
        """Handle missing access token gracefully."""
        bus = MessageBus()
        ch = DingTalkChannel(bus, config={})
        ch._access_token = None
        ch._app_key = "key"
        ch._app_secret = "secret"

        async def go():
            with patch.object(ch, "_get_access_token", return_value=None):
                msg = OutboundMessage(
                    channel_name="dingtalk",
                    chat_id="chat1",
                    thread_id="t1",
                    text="Hello",
                )
                # Should not raise, just return early
                await ch.send(msg)

        _run(go())

    def test_send_message_empty_text(self):
        """Skip sending when text is empty."""
        bus = MessageBus()
        ch = DingTalkChannel(bus, config={})
        ch._access_token = "test_token"

        async def go():
            msg = OutboundMessage(
                channel_name="dingtalk",
                chat_id="chat1",
                thread_id="t1",
                text="",
            )
            await ch.send(msg)
            # Should not make any API call

        _run(go())


# ---------------------------------------------------------------------------
# DingTalk Channel - File Upload tests
# ---------------------------------------------------------------------------


class TestDingTalkFileUpload:
    """Test file upload functionality."""

    def test_send_file_success(self, tmp_path):
        """Successfully upload and send a file."""
        bus = MessageBus()
        ch = DingTalkChannel(bus, config={})
        ch._app_key = "key"
        ch._app_secret = "secret"

        # Create a test file
        test_file = tmp_path / "document.pdf"
        test_file.write_bytes(b"%PDF-1.4 fake content")

        attachment = ResolvedAttachment(
            virtual_path="/mnt/user-data/outputs/document.pdf",
            actual_path=test_file,
            filename="document.pdf",
            mime_type="application/pdf",
            size=test_file.stat().st_size,
            is_image=False,
        )

        async def go():
            mock_upload_response = MagicMock()
            mock_upload_response.json.return_value = {"mediaId": "media123"}
            mock_upload_response.raise_for_status = MagicMock()

            mock_send_response = MagicMock()
            mock_send_response.json.return_value = {"code": "0"}
            mock_send_response.raise_for_status = MagicMock()

            call_count = 0

            def mock_post(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return mock_upload_response
                return mock_send_response

            with patch.object(ch, "_get_access_token", return_value="test_token"):
                with patch("httpx.AsyncClient") as mock_client_class:
                    mock_client = AsyncMock()
                    mock_client.__aenter__.return_value = mock_client
                    mock_client.__aexit__.return_value = None
                    mock_client.post = AsyncMock(side_effect=mock_post)
                    mock_client_class.return_value = mock_client

                    msg = OutboundMessage(
                        channel_name="dingtalk",
                        chat_id="chat1",
                        thread_id="t1",
                        text="Here's the file",
                    )
                    result = await ch.send_file(msg, attachment)

                    assert result is True

        _run(go())

    def test_send_image_file(self, tmp_path):
        """Successfully upload and send an image."""
        bus = MessageBus()
        ch = DingTalkChannel(bus, config={})
        ch._app_key = "key"
        ch._app_secret = "secret"

        # Create a test image
        test_file = tmp_path / "photo.png"
        test_file.write_bytes(b"\x89PNG fake image data")

        attachment = ResolvedAttachment(
            virtual_path="/mnt/user-data/outputs/photo.png",
            actual_path=test_file,
            filename="photo.png",
            mime_type="image/png",
            size=test_file.stat().st_size,
            is_image=True,
        )

        async def go():
            mock_upload_response = MagicMock()
            mock_upload_response.json.return_value = {"mediaId": "media456"}
            mock_upload_response.raise_for_status = MagicMock()

            mock_send_response = MagicMock()
            mock_send_response.json.return_value = {"code": "0"}
            mock_send_response.raise_for_status = MagicMock()

            call_count = 0

            def mock_post(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return mock_upload_response
                return mock_send_response

            with patch.object(ch, "_get_access_token", return_value="test_token"):
                with patch("httpx.AsyncClient") as mock_client_class:
                    mock_client = AsyncMock()
                    mock_client.__aenter__.return_value = mock_client
                    mock_client.__aexit__.return_value = None
                    mock_client.post = AsyncMock(side_effect=mock_post)
                    mock_client_class.return_value = mock_client

                    msg = OutboundMessage(
                        channel_name="dingtalk",
                        chat_id="chat1",
                        thread_id="t1",
                        text="Here's the image",
                    )
                    result = await ch.send_file(msg, attachment)

                    assert result is True

        _run(go())

    def test_send_file_too_large(self, tmp_path):
        """Reject files larger than 20MB."""
        bus = MessageBus()
        ch = DingTalkChannel(bus, config={})
        ch._access_token = "test_token"

        attachment = ResolvedAttachment(
            virtual_path="/mnt/user-data/outputs/large.zip",
            actual_path=tmp_path / "large.zip",
            filename="large.zip",
            mime_type="application/zip",
            size=25 * 1024 * 1024,  # 25MB
            is_image=False,
        )

        async def go():
            msg = OutboundMessage(
                channel_name="dingtalk",
                chat_id="chat1",
                thread_id="t1",
                text="File",
            )
            result = await ch.send_file(msg, attachment)

            assert result is False

        _run(go())

    def test_send_file_no_token(self, tmp_path):
        """Handle missing token during file upload."""
        bus = MessageBus()
        ch = DingTalkChannel(bus, config={})
        ch._access_token = None
        ch._app_key = "key"
        ch._app_secret = "secret"

        test_file = tmp_path / "doc.txt"
        test_file.write_text("content")

        attachment = ResolvedAttachment(
            virtual_path="/mnt/user-data/outputs/doc.txt",
            actual_path=test_file,
            filename="doc.txt",
            mime_type="text/plain",
            size=7,
            is_image=False,
        )

        async def go():
            with patch.object(ch, "_get_access_token", return_value=None):
                msg = OutboundMessage(
                    channel_name="dingtalk",
                    chat_id="chat1",
                    thread_id="t1",
                    text="File",
                )
                result = await ch.send_file(msg, attachment)

                assert result is False

        _run(go())


# ---------------------------------------------------------------------------
# DingTalk Channel - Running Reply tests
# ---------------------------------------------------------------------------


class TestDingTalkRunningReply:
    """Test the 'Working on it...' reply mechanism."""

    def test_send_running_reply_success(self):
        """Successfully send a running reply."""
        bus = MessageBus()
        ch = DingTalkChannel(bus, config={})
        ch._app_key = "key"
        ch._app_secret = "secret"

        async def go():
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "code": "0",
                "processQueryKeys": ["running_msg_123"],
            }
            mock_response.raise_for_status = MagicMock()

            with patch.object(ch, "_get_access_token", return_value="test_token"):
                with patch("httpx.AsyncClient") as mock_client_class:
                    mock_client = AsyncMock()
                    mock_client.__aenter__.return_value = mock_client
                    mock_client.__aexit__.return_value = None
                    mock_client.post = AsyncMock(return_value=mock_response)
                    mock_client_class.return_value = mock_client

                    await ch._send_running_reply("chat1", "msg123")

                    assert ch._running_messages.get("msg123") == "running_msg_123"

        _run(go())

    def test_send_running_reply_failure(self):
        """Handle failure when sending running reply."""
        bus = MessageBus()
        ch = DingTalkChannel(bus, config={})
        ch._app_key = "key"
        ch._app_secret = "secret"

        async def go():
            with patch.object(ch, "_get_access_token", return_value="test_token"):
                with patch("httpx.AsyncClient") as mock_client_class:
                    mock_client = AsyncMock()
                    mock_client.__aenter__.return_value = mock_client
                    mock_client.__aexit__.return_value = None
                    mock_client.post = AsyncMock(side_effect=Exception("Network error"))
                    mock_client_class.return_value = mock_client

                    # Should not raise, just log the error
                    await ch._send_running_reply("chat1", "msg123")

                    assert "msg123" not in ch._running_messages

        _run(go())


# ---------------------------------------------------------------------------
# DingTalk Channel - Rich Text Parsing tests
# ---------------------------------------------------------------------------


class TestDingTalkRichTextParsing:
    """Test rich text content parsing."""

    def test_parse_rich_text_mixed_content(self):
        """Parse rich text with mixed content types."""
        bus = MessageBus()
        ch = DingTalkChannel(bus, config={})

        content = {
            "richTextContent": [
                {"type": "text", "text": "Check out "},
                {"type": "link", "text": "this link"},
                {"type": "text", "text": " and "},
                {"type": "mention", "text": "@someone"},
            ]
        }

        result = ch._parse_rich_text(content)
        assert result == "Check out  this link  and  @someone"

    def test_parse_rich_text_empty(self):
        """Parse empty rich text content."""
        bus = MessageBus()
        ch = DingTalkChannel(bus, config={})

        result = ch._parse_rich_text({"richTextContent": []})
        assert result == ""

    def test_parse_rich_text_unknown_type(self):
        """Parse rich text with unknown content types (skipped)."""
        bus = MessageBus()
        ch = DingTalkChannel(bus, config={})

        content = {
            "richTextContent": [
                {"type": "text", "text": "Hello"},
                {"type": "unknown", "data": "ignored"},
                {"type": "text", "text": "World"},
            ]
        }

        result = ch._parse_rich_text(content)
        # Unknown types are skipped, so we get "Hello World"
        assert result == "Hello World"


# ---------------------------------------------------------------------------
# DingTalk Channel - Lifecycle tests
# ---------------------------------------------------------------------------


class TestDingTalkChannelLifecycle:
    """Test channel start/stop lifecycle."""

    def test_start_missing_credentials(self):
        """Channel does not start without credentials."""
        bus = MessageBus()
        ch = DingTalkChannel(bus, config={})

        async def go():
            await ch.start()
            assert not ch._running

        _run(go())

    def test_start_with_credentials(self):
        """Channel starts with valid credentials."""
        bus = MessageBus()
        ch = DingTalkChannel(bus, config={"app_key": "key", "app_secret": "secret"})

        async def go():
            # Mock the thread to prevent actual WebSocket connection
            with patch("threading.Thread") as mock_thread:
                mock_thread_instance = MagicMock()
                mock_thread.return_value = mock_thread_instance

                await ch.start()

                assert ch._running
                assert ch._app_key == "key"
                assert ch._app_secret == "secret"
                mock_thread_instance.start.assert_called_once()

        _run(go())

    def test_stop_cleans_up(self):
        """Stop cleans up resources."""
        bus = MessageBus()
        ch = DingTalkChannel(bus, config={"app_key": "key", "app_secret": "secret"})
        ch._running = True
        mock_thread = MagicMock()
        ch._thread = mock_thread

        async def go():
            await ch.stop()

            assert not ch._running
            assert ch._thread is None  # Thread is set to None after join
            mock_thread.join.assert_called_once_with(timeout=5)

        _run(go())

    def test_is_running_property(self):
        """is_running property reflects _running state."""
        bus = MessageBus()
        ch = DingTalkChannel(bus, config={})

        assert not ch.is_running
        ch._running = True
        assert ch.is_running


# ---------------------------------------------------------------------------
# DingTalk Channel - WebSocket Message Handling tests
# ---------------------------------------------------------------------------


class TestDingTalkWebSocketHandling:
    """Test WebSocket message handling."""

    def test_handle_ws_message_event(self):
        """Handle EVENT type WebSocket message."""
        bus = MessageBus()
        ch = DingTalkChannel(bus, config={})
        ch._app_key = "key"
        ch._app_secret = "secret"
        ch._access_token = "token"

        ws = AsyncMock()

        data = {
            "type": "EVENT",
            "id": "event123",
            "data": {
                "message": {
                    "messageId": "msg140",
                    "msgType": "text",
                    "content": {"content": "Test"},
                },
                "sender": {"userId": "user1"},
                "chat": {"chatId": "chat1", "chatType": "single"},
            },
        }

        async def go():
            with patch.object(ch, "_get_access_token", return_value="token"):
                with patch.object(ch, "_send_running_reply", new_callable=AsyncMock):
                    await ch._handle_ws_message(data, ws)

                    # Should receive ACK
                    ws.send.assert_called_once()
                    ack = json.loads(ws.send.call_args[0][0])
                    assert ack["type"] == "ACK"
                    assert ack["id"] == "event123"

                    # Message should be published
                    msg = await asyncio.wait_for(bus.get_inbound(), timeout=2)
                    assert msg.text == "Test"

        _run(go())

    def test_handle_ws_non_event_ignored(self):
        """Non-EVENT messages are ignored."""
        bus = MessageBus()
        ch = DingTalkChannel(bus, config={})

        ws = AsyncMock()
        data = {"type": "PING", "id": "ping123"}

        async def go():
            await ch._handle_ws_message(data, ws)

            # No message should be published
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(bus.get_inbound(), timeout=0.5)

        _run(go())


# ---------------------------------------------------------------------------
# DingTalk Channel - Background Task Tracking tests
# ---------------------------------------------------------------------------


class TestDingTalkBackgroundTasks:
    """Test background task tracking utilities."""

    def test_track_background_task(self):
        """Tasks are tracked and cleaned up."""
        bus = MessageBus()
        ch = DingTalkChannel(bus, config={})

        async def go():
            task = asyncio.create_task(asyncio.sleep(0.1))
            ch._track_background_task(task, name="test_task", msg_id="msg123")

            assert task in ch._background_tasks
            await task
            assert task not in ch._background_tasks

        _run(go())

    def test_log_task_error(self):
        """Task errors are logged."""
        bus = MessageBus()
        ch = DingTalkChannel(bus, config={})

        async def failing_task():
            raise ValueError("Task failed")

        async def go():
            task = asyncio.create_task(failing_task())
            ch._track_background_task(task, name="failing_task", msg_id="msg124")

            await asyncio.sleep(0.1)
            # Task should be removed from tracking
            assert task not in ch._background_tasks

        _run(go())


# ---------------------------------------------------------------------------
# DingTalk Channel - Metadata tests
# ---------------------------------------------------------------------------


class TestDingTalkMetadata:
    """Test metadata handling in messages."""

    def test_message_metadata_includes_message_id(self):
        """Inbound messages include message_id in metadata."""
        bus = MessageBus()
        ch = DingTalkChannel(bus, config={})
        ch._app_key = "key"
        ch._app_secret = "secret"

        event_data = {
            "message": {
                "messageId": "msg150",
                "msgType": "text",
                "content": {"content": "Test"},
            },
            "sender": {"userId": "user1"},
            "chat": {"chatId": "chat1", "chatType": "group"},
        }

        async def go():
            with patch.object(ch, "_get_access_token", return_value="token"):
                with patch.object(ch, "_send_running_reply", new_callable=AsyncMock):
                    await ch._handle_message_event_raw(event_data)

                    msg = await asyncio.wait_for(bus.get_inbound(), timeout=2)
                    assert msg.metadata["message_id"] == "msg150"
                    assert msg.metadata["chat_type"] == "group"

        _run(go())