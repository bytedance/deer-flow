"""Tests for the DingTalk channel implementation."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.channels.commands import KNOWN_CHANNEL_COMMANDS
from app.channels.dingtalk import (
    _CONVERSATION_TYPE_GROUP,
    _CONVERSATION_TYPE_P2P,
    DingTalkChannel,
    _adapt_markdown_for_dingtalk,
    _convert_markdown_table,
    _DingTalkMessageHandler,
    _extract_text_from_rich_text,
    _is_dingtalk_command,
    _normalize_allowed_users,
    _normalize_conversation_type,
)
from app.channels.message_bus import InboundMessageType, MessageBus, OutboundMessage


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Helper: build mock ChatbotMessage
# ---------------------------------------------------------------------------


def _make_chatbot_message(
    *,
    text: str = "hello",
    message_type: str = "text",
    conversation_type: str | int = _CONVERSATION_TYPE_P2P,
    sender_staff_id: str = "user_001",
    sender_nick: str = "Test User",
    conversation_id: str = "conv_001",
    message_id: str = "msg_001",
    rich_text_list: list | None = None,
):
    """Build a minimal mock object mimicking dingtalk_stream.ChatbotMessage."""
    msg = SimpleNamespace()
    msg.message_type = message_type
    msg.conversation_type = conversation_type
    msg.sender_staff_id = sender_staff_id
    msg.sender_nick = sender_nick
    msg.conversation_id = conversation_id
    msg.message_id = message_id

    if message_type == "text":
        msg.text = SimpleNamespace(content=text)
        msg.rich_text_content = None
    elif message_type == "richText":
        msg.text = None
        msg.rich_text_content = SimpleNamespace(rich_text_list=rich_text_list or [])
    else:
        msg.text = None
        msg.rich_text_content = None

    return msg


# ---------------------------------------------------------------------------
# _DingTalkMessageHandler SDK contract
# ---------------------------------------------------------------------------


class TestDingTalkMessageHandlerSdkContract:
    def test_pre_start_exists_and_noop(self):
        bus = MessageBus()
        channel = DingTalkChannel(bus, config={})
        handler = _DingTalkMessageHandler(channel)
        handler.pre_start()

    def test_raw_process_returns_ack(self):
        pytest.importorskip("dingtalk_stream")

        async def go():
            bus = MessageBus()
            channel = DingTalkChannel(bus, config={})
            channel._on_chatbot_message = MagicMock()
            handler = _DingTalkMessageHandler(channel)
            cb = MagicMock()
            cb.headers.message_id = "mid-1"
            cb.data = {
                "msgtype": "text",
                "text": {"content": "hi"},
                "senderStaffId": "u1",
                "conversationType": "1",
                "msgId": "m1",
            }
            ack = await handler.raw_process(cb)
            assert ack.code == 200
            assert ack.headers.message_id == "mid-1"
            assert ack.data == {"response": "OK"}
            channel._on_chatbot_message.assert_called_once()

        _run(go())


# ---------------------------------------------------------------------------
# _normalize_allowed_users tests
# ---------------------------------------------------------------------------


class TestNormalizeAllowedUsers:
    def test_none_returns_empty(self):
        assert _normalize_allowed_users(None) == set()

    def test_empty_list_returns_empty(self):
        assert _normalize_allowed_users([]) == set()

    def test_list_of_strings(self):
        result = _normalize_allowed_users(["user1", "user2"])
        assert result == {"user1", "user2"}

    def test_single_string(self):
        result = _normalize_allowed_users("user1")
        assert result == {"user1"}

    def test_numeric_values_converted_to_string(self):
        result = _normalize_allowed_users([123, 456])
        assert result == {"123", "456"}

    def test_scalar_treated_as_single_value(self):
        result = _normalize_allowed_users(12345)
        assert result == {"12345"}


# ---------------------------------------------------------------------------
# _normalize_conversation_type tests
# ---------------------------------------------------------------------------


class TestNormalizeConversationType:
    def test_group_int_or_str(self):
        assert _normalize_conversation_type(2) == _CONVERSATION_TYPE_GROUP
        assert _normalize_conversation_type("2") == _CONVERSATION_TYPE_GROUP

    def test_p2p_or_none(self):
        assert _normalize_conversation_type(1) == _CONVERSATION_TYPE_P2P
        assert _normalize_conversation_type(None) == _CONVERSATION_TYPE_P2P


# ---------------------------------------------------------------------------
# _is_dingtalk_command tests
# ---------------------------------------------------------------------------


class TestIsDingTalkCommand:
    @pytest.mark.parametrize("command", sorted(KNOWN_CHANNEL_COMMANDS))
    def test_known_commands_recognized(self, command):
        assert _is_dingtalk_command(command) is True

    @pytest.mark.parametrize(
        "text",
        [
            "/unknown",
            "/mnt/user-data/outputs/report.md",
            "hello",
            "",
            "not a command",
        ],
    )
    def test_non_commands_rejected(self, text):
        assert _is_dingtalk_command(text) is False


# ---------------------------------------------------------------------------
# _extract_text_from_rich_text tests
# ---------------------------------------------------------------------------


class TestExtractTextFromRichText:
    def test_single_text_item(self):
        result = _extract_text_from_rich_text([{"text": "hello"}])
        assert result == "hello"

    def test_multiple_text_items(self):
        result = _extract_text_from_rich_text([{"text": "hello"}, {"text": "world"}])
        assert result == "hello world"

    def test_non_text_items_ignored(self):
        result = _extract_text_from_rich_text(
            [
                {"downloadCode": "abc123"},
                {"text": "caption"},
            ]
        )
        assert result == "caption"

    def test_empty_list(self):
        assert _extract_text_from_rich_text([]) == ""


# ---------------------------------------------------------------------------
# DingTalkChannel._extract_text tests
# ---------------------------------------------------------------------------


class TestExtractText:
    def test_plain_text(self):
        msg = _make_chatbot_message(text="Hello World")
        assert DingTalkChannel._extract_text(msg) == "Hello World"

    def test_plain_text_stripped(self):
        msg = _make_chatbot_message(text="  Hello  ")
        assert DingTalkChannel._extract_text(msg) == "Hello"

    def test_rich_text(self):
        msg = _make_chatbot_message(
            message_type="richText",
            rich_text_list=[{"text": "Part 1"}, {"text": "Part 2"}],
        )
        assert DingTalkChannel._extract_text(msg) == "Part 1 Part 2"

    def test_unknown_type_returns_empty(self):
        msg = _make_chatbot_message(message_type="picture")
        assert DingTalkChannel._extract_text(msg) == ""


# ---------------------------------------------------------------------------
# DingTalkChannel._on_chatbot_message tests (inbound parsing)
# ---------------------------------------------------------------------------


class TestOnChatbotMessage:
    def test_p2p_message_produces_correct_inbound(self):
        async def go():
            bus = MessageBus()
            bus.publish_inbound = AsyncMock()
            channel = DingTalkChannel(bus, config={})
            channel._client_id = "test_key"
            channel._main_loop = asyncio.get_event_loop()
            channel._running = True

            msg = _make_chatbot_message(
                text="hello from dingtalk",
                conversation_type=_CONVERSATION_TYPE_P2P,
                sender_staff_id="user_001",
                message_id="msg_001",
            )

            channel._send_running_reply = AsyncMock()
            channel._on_chatbot_message(msg)

            await asyncio.sleep(0.1)

            bus.publish_inbound.assert_awaited_once()
            inbound = bus.publish_inbound.await_args.args[0]
            assert inbound.channel_name == "dingtalk"
            assert inbound.chat_id == "user_001"
            assert inbound.user_id == "user_001"
            assert inbound.text == "hello from dingtalk"
            assert inbound.topic_id is None
            assert inbound.metadata["conversation_type"] == _CONVERSATION_TYPE_P2P
            assert inbound.metadata["sender_staff_id"] == "user_001"

        _run(go())

    def test_group_message_produces_correct_inbound(self):
        async def go():
            bus = MessageBus()
            bus.publish_inbound = AsyncMock()
            channel = DingTalkChannel(bus, config={})
            channel._client_id = "test_key"
            channel._main_loop = asyncio.get_event_loop()
            channel._running = True

            msg = _make_chatbot_message(
                text="hello group",
                conversation_type=_CONVERSATION_TYPE_GROUP,
                sender_staff_id="user_002",
                conversation_id="conv_group_001",
                message_id="msg_group_001",
            )

            channel._send_running_reply = AsyncMock()
            channel._on_chatbot_message(msg)

            await asyncio.sleep(0.1)

            bus.publish_inbound.assert_awaited_once()
            inbound = bus.publish_inbound.await_args.args[0]
            assert inbound.channel_name == "dingtalk"
            assert inbound.chat_id == "conv_group_001"
            assert inbound.user_id == "user_002"
            assert inbound.text == "hello group"
            assert inbound.topic_id == "msg_group_001"
            assert inbound.metadata["conversation_type"] == _CONVERSATION_TYPE_GROUP
            assert inbound.metadata["conversation_id"] == "conv_group_001"

        _run(go())

    def test_group_message_integer_conversation_type_normalized(self):
        """SDK may deliver conversationType as int 2 — must still route as group."""

        async def go():
            bus = MessageBus()
            bus.publish_inbound = AsyncMock()
            channel = DingTalkChannel(bus, config={})
            channel._client_id = "test_key"
            channel._main_loop = asyncio.get_event_loop()
            channel._running = True

            msg = _make_chatbot_message(
                text="hello group",
                conversation_type=2,
                sender_staff_id="user_002",
                conversation_id="conv_group_001",
                message_id="msg_group_002",
            )

            channel._send_running_reply = AsyncMock()
            channel._on_chatbot_message(msg)

            await asyncio.sleep(0.1)

            bus.publish_inbound.assert_awaited_once()
            inbound = bus.publish_inbound.await_args.args[0]
            assert inbound.chat_id == "conv_group_001"
            assert inbound.topic_id == "msg_group_002"
            assert inbound.metadata["conversation_type"] == _CONVERSATION_TYPE_GROUP

        _run(go())

    def test_command_classified_correctly(self):
        async def go():
            bus = MessageBus()
            bus.publish_inbound = AsyncMock()
            channel = DingTalkChannel(bus, config={})
            channel._client_id = "test_key"
            channel._main_loop = asyncio.get_event_loop()
            channel._running = True

            msg = _make_chatbot_message(text="/help")
            channel._send_running_reply = AsyncMock()
            channel._on_chatbot_message(msg)

            await asyncio.sleep(0.1)

            bus.publish_inbound.assert_awaited_once()
            inbound = bus.publish_inbound.await_args.args[0]
            assert inbound.msg_type == InboundMessageType.COMMAND

        _run(go())

    def test_non_command_classified_as_chat(self):
        async def go():
            bus = MessageBus()
            bus.publish_inbound = AsyncMock()
            channel = DingTalkChannel(bus, config={})
            channel._client_id = "test_key"
            channel._main_loop = asyncio.get_event_loop()
            channel._running = True

            msg = _make_chatbot_message(text="just chatting")
            channel._send_running_reply = AsyncMock()
            channel._on_chatbot_message(msg)

            await asyncio.sleep(0.1)

            bus.publish_inbound.assert_awaited_once()
            inbound = bus.publish_inbound.await_args.args[0]
            assert inbound.msg_type == InboundMessageType.CHAT

        _run(go())

    def test_empty_text_ignored(self):
        async def go():
            bus = MessageBus()
            bus.publish_inbound = AsyncMock()
            channel = DingTalkChannel(bus, config={})
            channel._client_id = "test_key"
            channel._main_loop = asyncio.get_event_loop()
            channel._running = True

            msg = _make_chatbot_message(text="   ")
            channel._on_chatbot_message(msg)

            await asyncio.sleep(0.1)
            bus.publish_inbound.assert_not_awaited()

        _run(go())


# ---------------------------------------------------------------------------
# allowed_users filtering tests
# ---------------------------------------------------------------------------


class TestAllowedUsersFiltering:
    def test_allowed_user_passes(self):
        async def go():
            bus = MessageBus()
            bus.publish_inbound = AsyncMock()
            channel = DingTalkChannel(bus, config={"allowed_users": ["user_001"]})
            channel._client_id = "test_key"
            channel._main_loop = asyncio.get_event_loop()
            channel._running = True

            msg = _make_chatbot_message(sender_staff_id="user_001")
            channel._send_running_reply = AsyncMock()
            channel._on_chatbot_message(msg)

            await asyncio.sleep(0.1)
            bus.publish_inbound.assert_awaited_once()

        _run(go())

    def test_non_allowed_user_blocked(self):
        async def go():
            bus = MessageBus()
            bus.publish_inbound = AsyncMock()
            channel = DingTalkChannel(bus, config={"allowed_users": ["user_001"]})
            channel._client_id = "test_key"
            channel._main_loop = asyncio.get_event_loop()
            channel._running = True

            msg = _make_chatbot_message(sender_staff_id="user_blocked")
            channel._on_chatbot_message(msg)

            await asyncio.sleep(0.1)
            bus.publish_inbound.assert_not_awaited()

        _run(go())

    def test_empty_allowed_users_allows_all(self):
        async def go():
            bus = MessageBus()
            bus.publish_inbound = AsyncMock()
            channel = DingTalkChannel(bus, config={"allowed_users": []})
            channel._client_id = "test_key"
            channel._main_loop = asyncio.get_event_loop()
            channel._running = True

            msg = _make_chatbot_message(sender_staff_id="anyone")
            channel._send_running_reply = AsyncMock()
            channel._on_chatbot_message(msg)

            await asyncio.sleep(0.1)
            bus.publish_inbound.assert_awaited_once()

        _run(go())


# ---------------------------------------------------------------------------
# send routing tests (P2P vs Group)
# ---------------------------------------------------------------------------


class TestMarkdownFallbackPropagation:
    def test_fallback_raises_on_failure(self):
        async def go():
            bus = MessageBus()
            channel = DingTalkChannel(bus, config={})
            channel._client_id = "test_key"
            channel._cached_token = "tok"
            channel._token_expires_at = float("inf")

            channel._send_p2p_message = AsyncMock(side_effect=ConnectionError("send failed"))

            with pytest.raises(ConnectionError, match="send failed"):
                await channel._send_markdown_fallback("test_key", _CONVERSATION_TYPE_P2P, "user_001", "", "hello")

        _run(go())


class TestSendRouting:
    def test_p2p_send_uses_oto_endpoint(self):
        async def go():
            bus = MessageBus()
            channel = DingTalkChannel(bus, config={})
            channel._client_id = "test_key"
            channel._client_secret = "test_secret"

            channel._send_p2p_message = AsyncMock()
            channel._send_group_message = AsyncMock()

            msg = OutboundMessage(
                channel_name="dingtalk",
                chat_id="user_001",
                thread_id="thread_001",
                text="Hello P2P",
                metadata={
                    "conversation_type": _CONVERSATION_TYPE_P2P,
                    "sender_staff_id": "user_001",
                    "conversation_id": "",
                },
            )

            await channel.send(msg)

            channel._send_p2p_message.assert_awaited_once_with("test_key", "user_001", "Hello P2P")
            channel._send_group_message.assert_not_awaited()

        _run(go())

    def test_group_send_uses_group_endpoint(self):
        async def go():
            bus = MessageBus()
            channel = DingTalkChannel(bus, config={})
            channel._client_id = "test_key"
            channel._client_secret = "test_secret"

            channel._send_p2p_message = AsyncMock()
            channel._send_group_message = AsyncMock()

            msg = OutboundMessage(
                channel_name="dingtalk",
                chat_id="conv_001",
                thread_id="thread_001",
                text="Hello Group",
                metadata={
                    "conversation_type": _CONVERSATION_TYPE_GROUP,
                    "sender_staff_id": "user_001",
                    "conversation_id": "conv_001",
                },
            )

            await channel.send(msg)

            channel._send_group_message.assert_awaited_once_with("test_key", "conv_001", "Hello Group", at_user_ids=["user_001"])
            channel._send_p2p_message.assert_not_awaited()

        _run(go())

    def test_default_metadata_uses_p2p(self):
        async def go():
            bus = MessageBus()
            channel = DingTalkChannel(bus, config={})
            channel._client_id = "test_key"
            channel._client_secret = "test_secret"

            channel._send_p2p_message = AsyncMock()
            channel._send_group_message = AsyncMock()

            msg = OutboundMessage(
                channel_name="dingtalk",
                chat_id="user_001",
                thread_id="thread_001",
                text="Hello",
                metadata={},
            )

            await channel.send(msg)

            channel._send_p2p_message.assert_awaited_once()
            channel._send_group_message.assert_not_awaited()

        _run(go())


# ---------------------------------------------------------------------------
# send retry tests
# ---------------------------------------------------------------------------


class TestSendRetry:
    def test_retries_on_failure_then_succeeds(self):
        async def go():
            bus = MessageBus()
            channel = DingTalkChannel(bus, config={})
            channel._client_id = "test_key"
            channel._client_secret = "test_secret"

            call_count = 0

            async def flaky_send(robot_code, user_id, text):
                nonlocal call_count
                call_count += 1
                if call_count < 3:
                    raise ConnectionError("network error")

            channel._send_p2p_message = AsyncMock(side_effect=flaky_send)

            msg = OutboundMessage(
                channel_name="dingtalk",
                chat_id="user_001",
                thread_id="thread_001",
                text="hello",
                metadata={"conversation_type": _CONVERSATION_TYPE_P2P, "sender_staff_id": "user_001"},
            )

            await channel.send(msg)
            assert call_count == 3

        _run(go())

    def test_raises_after_all_retries_exhausted(self):
        async def go():
            bus = MessageBus()
            channel = DingTalkChannel(bus, config={})
            channel._client_id = "test_key"
            channel._client_secret = "test_secret"

            channel._send_p2p_message = AsyncMock(side_effect=ConnectionError("fail"))

            msg = OutboundMessage(
                channel_name="dingtalk",
                chat_id="user_001",
                thread_id="thread_001",
                text="hello",
                metadata={"conversation_type": _CONVERSATION_TYPE_P2P, "sender_staff_id": "user_001"},
            )

            with pytest.raises(ConnectionError):
                await channel.send(msg)

            assert channel._send_p2p_message.await_count == 3

        _run(go())

    def test_raises_runtime_error_when_no_attempts_configured(self):
        async def go():
            bus = MessageBus()
            channel = DingTalkChannel(bus, config={})
            channel._client_id = "test_key"
            channel._client_secret = "test_secret"

            msg = OutboundMessage(
                channel_name="dingtalk",
                chat_id="user_001",
                thread_id="thread_001",
                text="hello",
                metadata={"conversation_type": _CONVERSATION_TYPE_P2P, "sender_staff_id": "user_001"},
            )

            with pytest.raises(RuntimeError, match="without an exception"):
                await channel.send(msg, _max_retries=0)

        _run(go())


# ---------------------------------------------------------------------------
# topic_id mapping tests
# ---------------------------------------------------------------------------


class TestTopicIdMapping:
    def test_p2p_topic_is_none(self):
        async def go():
            bus = MessageBus()
            bus.publish_inbound = AsyncMock()
            channel = DingTalkChannel(bus, config={})
            channel._client_id = "test_key"
            channel._main_loop = asyncio.get_event_loop()
            channel._running = True

            msg = _make_chatbot_message(
                conversation_type=_CONVERSATION_TYPE_P2P,
                message_id="msg_p2p_001",
            )
            channel._send_running_reply = AsyncMock()
            channel._on_chatbot_message(msg)

            await asyncio.sleep(0.1)
            inbound = bus.publish_inbound.await_args.args[0]
            assert inbound.topic_id is None

        _run(go())

    def test_group_topic_is_message_id(self):
        async def go():
            bus = MessageBus()
            bus.publish_inbound = AsyncMock()
            channel = DingTalkChannel(bus, config={})
            channel._client_id = "test_key"
            channel._main_loop = asyncio.get_event_loop()
            channel._running = True

            msg = _make_chatbot_message(
                conversation_type=_CONVERSATION_TYPE_GROUP,
                message_id="msg_group_001",
                conversation_id="conv_001",
            )
            channel._send_running_reply = AsyncMock()
            channel._on_chatbot_message(msg)

            await asyncio.sleep(0.1)
            inbound = bus.publish_inbound.await_args.args[0]
            assert inbound.topic_id == "msg_group_001"

        _run(go())


# ---------------------------------------------------------------------------
# Token caching tests
# ---------------------------------------------------------------------------


class TestAccessTokenValidation:
    def test_rejects_non_dict_response(self):
        async def go():
            from unittest.mock import patch

            bus = MessageBus()
            channel = DingTalkChannel(bus, config={})
            channel._client_id = "k"
            channel._client_secret = "s"

            class FakeResponse:
                def raise_for_status(self):
                    pass

                def json(self):
                    return "not a dict"

            class FakeClient:
                async def __aenter__(self):
                    return self

                async def __aexit__(self, *a):
                    pass

                async def post(self, url, **kwargs):
                    return FakeResponse()

            with patch("app.channels.dingtalk.httpx.AsyncClient", return_value=FakeClient()):
                with pytest.raises(ValueError, match="JSON object"):
                    await channel._get_access_token()

        _run(go())

    def test_rejects_empty_access_token(self):
        async def go():
            from unittest.mock import patch

            bus = MessageBus()
            channel = DingTalkChannel(bus, config={})
            channel._client_id = "k"
            channel._client_secret = "s"

            class FakeResponse:
                def raise_for_status(self):
                    pass

                def json(self):
                    return {"accessToken": "", "expireIn": 7200}

            class FakeClient:
                async def __aenter__(self):
                    return self

                async def __aexit__(self, *a):
                    pass

                async def post(self, url, **kwargs):
                    return FakeResponse()

            with patch("app.channels.dingtalk.httpx.AsyncClient", return_value=FakeClient()):
                with pytest.raises(ValueError, match="usable accessToken"):
                    await channel._get_access_token()

        _run(go())

    def test_invalid_expire_in_uses_default(self):
        async def go():
            import time
            from unittest.mock import patch

            bus = MessageBus()
            channel = DingTalkChannel(bus, config={})
            channel._client_id = "k"
            channel._client_secret = "s"

            class FakeResponse:
                def raise_for_status(self):
                    pass

                def json(self):
                    return {"accessToken": "tok_ok", "expireIn": "invalid"}

            class FakeClient:
                async def __aenter__(self):
                    return self

                async def __aexit__(self, *a):
                    pass

                async def post(self, url, **kwargs):
                    return FakeResponse()

            before = time.monotonic()
            with patch("app.channels.dingtalk.httpx.AsyncClient", return_value=FakeClient()):
                token = await channel._get_access_token()

            assert token == "tok_ok"
            assert channel._token_expires_at > before

        _run(go())


class TestTokenCaching:
    def test_token_is_cached_across_calls(self):
        async def go():
            from unittest.mock import patch

            bus = MessageBus()
            channel = DingTalkChannel(bus, config={})
            channel._client_id = "test_key"
            channel._client_secret = "test_secret"

            call_count = 0

            class FakeResponse:
                def raise_for_status(self):
                    pass

                def json(self):
                    return {"accessToken": "tok_abc", "expireIn": 7200}

            class FakeClient:
                async def __aenter__(self):
                    return self

                async def __aexit__(self, *a):
                    pass

                async def post(self, url, **kwargs):
                    nonlocal call_count
                    call_count += 1
                    return FakeResponse()

            with patch("app.channels.dingtalk.httpx.AsyncClient", return_value=FakeClient()):
                t1 = await channel._get_access_token()
                t2 = await channel._get_access_token()

            assert t1 == "tok_abc"
            assert t2 == "tok_abc"
            assert call_count == 1

        _run(go())


# ---------------------------------------------------------------------------
# Group message @ mention format tests
# ---------------------------------------------------------------------------


class TestGroupMessageMarkdownFormat:
    def test_at_user_ids_still_use_markdown(self):
        """groupMessages/send uses sampleMarkdown; @{userId} in body returns 400 so at_user_ids is ignored."""

        async def go():
            from unittest.mock import patch

            bus = MessageBus()
            channel = DingTalkChannel(bus, config={})
            channel._client_id = "test_key"
            channel._client_secret = "test_secret"
            channel._cached_token = "tok_test"
            channel._token_expires_at = float("inf")

            captured_json: list[dict] = []

            class FakeResponse:
                def raise_for_status(self):
                    pass

                def json(self):
                    return {"processQueryKey": "ok"}

            class FakeClient:
                async def __aenter__(self):
                    return self

                async def __aexit__(self, *a):
                    pass

                async def post(self, url, **kwargs):
                    captured_json.append(kwargs.get("json", {}))
                    return FakeResponse()

            with patch("app.channels.dingtalk.httpx.AsyncClient", return_value=FakeClient()):
                await channel._send_group_message("bot", "conv1", "hello", at_user_ids=["staff_001"])

            assert len(captured_json) == 1
            payload = captured_json[0]
            assert payload["msgKey"] == "sampleMarkdown"
            import json

            param = json.loads(payload["msgParam"])
            assert param["text"] == "hello"
            assert "@" not in json.dumps(param)

        _run(go())

    def test_no_at_user_ids_uses_markdown(self):
        async def go():
            from unittest.mock import patch

            bus = MessageBus()
            channel = DingTalkChannel(bus, config={})
            channel._client_id = "test_key"
            channel._client_secret = "test_secret"
            channel._cached_token = "tok_test"
            channel._token_expires_at = float("inf")

            captured_json: list[dict] = []

            class FakeResponse:
                def raise_for_status(self):
                    pass

                def json(self):
                    return {"processQueryKey": "ok"}

            class FakeClient:
                async def __aenter__(self):
                    return self

                async def __aexit__(self, *a):
                    pass

                async def post(self, url, **kwargs):
                    captured_json.append(kwargs.get("json", {}))
                    return FakeResponse()

            with patch("app.channels.dingtalk.httpx.AsyncClient", return_value=FakeClient()):
                await channel._send_group_message("bot", "conv1", "hello")

            assert len(captured_json) == 1
            payload = captured_json[0]
            assert payload["msgKey"] == "sampleMarkdown"

        _run(go())


class TestAdaptMarkdownForDingtalk:
    def test_fenced_code_block_to_blockquote(self):
        text = "Hello\n```python\ndef foo():\n    return 1\n```\nDone"
        result = _adapt_markdown_for_dingtalk(text)
        assert "```" not in result
        assert "> **python**" in result
        assert "> def foo():" in result
        assert ">     return 1" in result

    def test_fenced_code_block_no_language(self):
        text = "```\nplain code\n```"
        result = _adapt_markdown_for_dingtalk(text)
        assert "```" not in result
        assert "> plain code" in result

    def test_inline_code_to_bold(self):
        text = "Use `pip install` to install"
        result = _adapt_markdown_for_dingtalk(text)
        assert result == "Use **pip install** to install"

    def test_horizontal_rule_to_unicode(self):
        text = "Above\n---\nBelow"
        result = _adapt_markdown_for_dingtalk(text)
        assert "───────────" in result
        assert "---" not in result

    def test_supported_markdown_preserved(self):
        text = "# Title\n**bold** and *italic*\n- list item\n> quote\n[link](http://example.com)"
        result = _adapt_markdown_for_dingtalk(text)
        assert result == text

    def test_plain_text_unchanged(self):
        text = "Hello world, no markdown here."
        assert _adapt_markdown_for_dingtalk(text) == text

    def test_combined_elements(self):
        text = "# Report\n\nRun `make test` then:\n\n```bash\npytest -v\n```\n\n---\n\nDone."
        result = _adapt_markdown_for_dingtalk(text)
        assert "# Report" in result
        assert "**make test**" in result
        assert "> **bash**" in result
        assert "> pytest -v" in result
        assert "───────────" in result
        assert "Done." in result


class TestConvertMarkdownTable:
    def test_simple_table(self):
        text = "| Name | Age |\n|------|-----|\n| Alice | 30 |\n| Bob | 25 |"
        result = _convert_markdown_table(text)
        assert "> **Name**: Alice" in result
        assert "> **Age**: 30" in result
        assert "> **Name**: Bob" in result
        assert "> **Age**: 25" in result
        assert "|" not in result

    def test_table_with_surrounding_text(self):
        text = "Results:\n\n| Key | Value |\n|-----|-------|\n| a | 1 |\n\nEnd."
        result = _convert_markdown_table(text)
        assert "Results:" in result
        assert "> **Key**: a" in result
        assert "> **Value**: 1" in result
        assert "End." in result

    def test_no_table(self):
        text = "Just plain text\nwith lines"
        assert _convert_markdown_table(text) == text

    def test_alignment_separators(self):
        text = "| Left | Center | Right |\n|:-----|:------:|------:|\n| a | b | c |"
        result = _convert_markdown_table(text)
        assert "> **Left**: a" in result
        assert "> **Center**: b" in result
        assert "> **Right**: c" in result


class TestUploadMediaValidation:
    def test_non_dict_response_returns_none(self):
        async def go():
            from unittest.mock import patch

            bus = MessageBus()
            channel = DingTalkChannel(bus, config={})
            channel._client_id = "k"
            channel._client_secret = "s"
            channel._cached_token = "tok"
            channel._token_expires_at = float("inf")

            class FakeResponse:
                def raise_for_status(self):
                    pass

                def json(self):
                    return ["not", "a", "dict"]

            class FakeClient:
                async def __aenter__(self):
                    return self

                async def __aexit__(self, *a):
                    pass

                async def post(self, url, **kwargs):
                    return FakeResponse()

            with patch("app.channels.dingtalk.httpx.AsyncClient", return_value=FakeClient()):
                result = await channel._upload_media("/tmp/test.png", "image")

            assert result is None

        _run(go())

    def test_json_decode_error_returns_none(self):
        async def go():
            import json as json_mod
            from unittest.mock import patch

            bus = MessageBus()
            channel = DingTalkChannel(bus, config={})
            channel._client_id = "k"
            channel._client_secret = "s"
            channel._cached_token = "tok"
            channel._token_expires_at = float("inf")

            class FakeResponse:
                def raise_for_status(self):
                    pass

                def json(self):
                    raise json_mod.JSONDecodeError("err", "", 0)

            class FakeClient:
                async def __aenter__(self):
                    return self

                async def __aexit__(self, *a):
                    pass

                async def post(self, url, **kwargs):
                    return FakeResponse()

            with patch("app.channels.dingtalk.httpx.AsyncClient", return_value=FakeClient()):
                result = await channel._upload_media("/tmp/test.png", "image")

            assert result is None

        _run(go())


class TestChannelRegistration:
    def test_dingtalk_in_channel_registry(self):
        from app.channels.service import _CHANNEL_REGISTRY

        assert "dingtalk" in _CHANNEL_REGISTRY
        assert _CHANNEL_REGISTRY["dingtalk"] == "app.channels.dingtalk:DingTalkChannel"

    def test_dingtalk_in_credential_keys(self):
        from app.channels.service import _CHANNEL_CREDENTIAL_KEYS

        assert "dingtalk" in _CHANNEL_CREDENTIAL_KEYS
        assert "client_id" in _CHANNEL_CREDENTIAL_KEYS["dingtalk"]
        assert "client_secret" in _CHANNEL_CREDENTIAL_KEYS["dingtalk"]

    def test_dingtalk_in_channel_capabilities(self):
        from app.channels.manager import CHANNEL_CAPABILITIES

        assert "dingtalk" in CHANNEL_CAPABILITIES
        assert CHANNEL_CAPABILITIES["dingtalk"]["supports_streaming"] is False


# ---------------------------------------------------------------------------
# AI Card streaming mode tests
# ---------------------------------------------------------------------------


class TestCardMode:
    def test_card_mode_enabled_supports_streaming(self):
        bus = MessageBus()
        channel = DingTalkChannel(bus, config={"card_template_id": "tpl_123"})
        assert channel.supports_streaming is True

    def test_non_card_mode_no_streaming(self):
        bus = MessageBus()
        channel = DingTalkChannel(bus, config={})
        assert channel.supports_streaming is False

    def test_non_card_mode_unchanged(self):
        bus = MessageBus()
        channel = DingTalkChannel(bus, config={})
        assert channel._card_template_id == ""
        assert channel._card_track_ids == {}
        assert channel._card_repliers == {}
        assert channel._incoming_messages == {}
        assert channel._dingtalk_client is None

    def test_card_source_key_matches_inbound_using_message_id_metadata(self):
        """Outbound correlation must match inbound ``message_id`` even if ``thread_ts`` drifts."""

        async def go():
            bus = MessageBus()
            channel = DingTalkChannel(bus, config={})
            inbound = channel._make_inbound(
                chat_id="x",
                user_id="u",
                text="hi",
                thread_ts="ts_fallback",
                metadata={
                    "conversation_type": _CONVERSATION_TYPE_P2P,
                    "sender_staff_id": "user_001",
                    "conversation_id": "",
                    "message_id": "msg_real",
                },
            )
            out = OutboundMessage(
                channel_name="dingtalk",
                chat_id="x",
                thread_id="t",
                text="ok",
                thread_ts="wrong_ts",
                metadata=dict(inbound.metadata),
            )
            assert channel._make_card_source_key(inbound) == channel._make_card_source_key_from_outbound(out)

        _run(go())

    def test_running_reply_creates_card(self):
        async def go():
            bus = MessageBus()
            channel = DingTalkChannel(bus, config={"card_template_id": "tpl_123"})
            channel._client_id = "test_key"

            channel._create_and_deliver_card = AsyncMock(return_value="track_001")

            inbound = channel._make_inbound(
                chat_id="user_001",
                user_id="user_001",
                text="hello",
                metadata={
                    "conversation_type": _CONVERSATION_TYPE_P2P,
                    "sender_staff_id": "user_001",
                    "conversation_id": "",
                    "message_id": "msg_001",
                },
            )

            mock_chatbot_msg = MagicMock()
            source_key = channel._make_card_source_key(inbound)
            channel._incoming_messages[source_key] = mock_chatbot_msg

            await channel._send_running_reply("user_001", inbound)

            channel._create_and_deliver_card.assert_awaited_once_with(
                "\u23f3 Working on it...",
                chatbot_message=mock_chatbot_msg,
            )
            assert channel._card_track_ids[source_key] == "track_001"

        _run(go())

    def test_send_streams_to_card(self):
        async def go():
            bus = MessageBus()
            channel = DingTalkChannel(bus, config={"card_template_id": "tpl_123"})
            channel._client_id = "test_key"

            channel._stream_update_card = AsyncMock()

            # Pre-populate card tracking
            source_key = f"{_CONVERSATION_TYPE_P2P}:user_001::msg_001"
            channel._card_track_ids[source_key] = "track_001"

            msg = OutboundMessage(
                channel_name="dingtalk",
                chat_id="user_001",
                thread_id="thread_001",
                text="Partial response...",
                is_final=False,
                thread_ts="msg_001",
                metadata={
                    "conversation_type": _CONVERSATION_TYPE_P2P,
                    "sender_staff_id": "user_001",
                    "conversation_id": "",
                },
            )

            await channel.send(msg)

            channel._stream_update_card.assert_awaited_once_with(
                "track_001",
                "Partial response...",
                is_finalize=False,
            )
            # Track ID should still exist (not final)
            assert source_key in channel._card_track_ids

        _run(go())

    def test_send_finalizes_card(self):
        async def go():
            bus = MessageBus()
            channel = DingTalkChannel(bus, config={"card_template_id": "tpl_123"})
            channel._client_id = "test_key"

            channel._stream_update_card = AsyncMock()

            source_key = f"{_CONVERSATION_TYPE_P2P}:user_001::msg_001"
            channel._card_track_ids[source_key] = "track_001"

            msg = OutboundMessage(
                channel_name="dingtalk",
                chat_id="user_001",
                thread_id="thread_001",
                text="Final answer.",
                is_final=True,
                thread_ts="msg_001",
                metadata={
                    "conversation_type": _CONVERSATION_TYPE_P2P,
                    "sender_staff_id": "user_001",
                    "conversation_id": "",
                },
            )

            await channel.send(msg)

            channel._stream_update_card.assert_awaited_once_with(
                "track_001",
                "Final answer.",
                is_finalize=True,
            )
            # Track ID should be cleaned up after final
            assert source_key not in channel._card_track_ids

        _run(go())

    def test_card_mode_skips_markdown_adaptation(self):
        async def go():
            bus = MessageBus()
            channel = DingTalkChannel(bus, config={"card_template_id": "tpl_123"})
            channel._client_id = "test_key"

            raw_markdown = "```python\ndef foo():\n    pass\n```"
            captured_content: list[str] = []

            async def capture_stream(out_track_id, content, *, is_finalize=False, is_error=False):
                captured_content.append(content)

            channel._stream_update_card = AsyncMock(side_effect=capture_stream)

            source_key = f"{_CONVERSATION_TYPE_P2P}:user_001::msg_001"
            channel._card_track_ids[source_key] = "track_001"

            msg = OutboundMessage(
                channel_name="dingtalk",
                chat_id="user_001",
                thread_id="thread_001",
                text=raw_markdown,
                is_final=True,
                thread_ts="msg_001",
                metadata={
                    "conversation_type": _CONVERSATION_TYPE_P2P,
                    "sender_staff_id": "user_001",
                    "conversation_id": "",
                },
            )

            await channel.send(msg)

            # Raw markdown should be passed through without adaptation
            assert captured_content[0] == raw_markdown

        _run(go())

    def test_card_fallback_on_creation_failure(self):
        async def go():
            bus = MessageBus()
            channel = DingTalkChannel(bus, config={"card_template_id": "tpl_123"})
            channel._client_id = "test_key"

            # Card creation returns None (failure)
            channel._create_and_deliver_card = AsyncMock(return_value=None)
            channel._send_text_message_to_user = AsyncMock()

            inbound = channel._make_inbound(
                chat_id="user_001",
                user_id="user_001",
                text="hello",
                metadata={
                    "conversation_type": _CONVERSATION_TYPE_P2P,
                    "sender_staff_id": "user_001",
                    "conversation_id": "",
                    "message_id": "msg_001",
                },
            )

            source_key = channel._make_card_source_key(inbound)
            channel._incoming_messages[source_key] = MagicMock()

            await channel._send_running_reply("user_001", inbound)

            # Should fall through to text message
            channel._send_text_message_to_user.assert_awaited_once()
            assert len(channel._card_track_ids) == 0

        _run(go())

    def test_send_skips_non_final_without_card_track_when_template_configured(self):
        """Without a live card track, Manager streaming would duplicate sampleMarkdown sends."""

        async def go():
            bus = MessageBus()
            channel = DingTalkChannel(bus, config={"card_template_id": "tpl_123"})
            channel._client_id = "test_key"
            channel._send_group_message = AsyncMock()
            channel._send_p2p_message = AsyncMock()

            meta = {
                "conversation_type": _CONVERSATION_TYPE_P2P,
                "sender_staff_id": "user_001",
                "conversation_id": "",
            }
            await channel.send(
                OutboundMessage(
                    channel_name="dingtalk",
                    chat_id="user_001",
                    thread_id="t1",
                    text="partial",
                    is_final=False,
                    thread_ts="msg_001",
                    metadata=meta,
                )
            )
            channel._send_p2p_message.assert_not_called()
            channel._send_group_message.assert_not_called()

            await channel.send(
                OutboundMessage(
                    channel_name="dingtalk",
                    chat_id="user_001",
                    thread_id="t1",
                    text="final answer",
                    is_final=True,
                    thread_ts="msg_001",
                    metadata=meta,
                )
            )
            channel._send_p2p_message.assert_awaited_once()

        _run(go())

    def test_card_fallback_on_stream_failure(self):
        async def go():
            bus = MessageBus()
            channel = DingTalkChannel(bus, config={"card_template_id": "tpl_123"})
            channel._client_id = "test_key"

            channel._stream_update_card = AsyncMock(side_effect=ConnectionError("stream failed"))
            channel._send_markdown_fallback = AsyncMock()

            source_key = f"{_CONVERSATION_TYPE_P2P}:user_001::msg_001"
            channel._card_track_ids[source_key] = "track_001"

            msg = OutboundMessage(
                channel_name="dingtalk",
                chat_id="user_001",
                thread_id="thread_001",
                text="Final answer.",
                is_final=True,
                thread_ts="msg_001",
                metadata={
                    "conversation_type": _CONVERSATION_TYPE_P2P,
                    "sender_staff_id": "user_001",
                    "conversation_id": "",
                },
            )

            await channel.send(msg)

            # Should fallback to markdown
            channel._send_markdown_fallback.assert_awaited_once_with(
                "test_key",
                _CONVERSATION_TYPE_P2P,
                "user_001",
                "",
                "Final answer.",
            )
            # Track ID should be cleaned up
            assert source_key not in channel._card_track_ids

        _run(go())

    def test_pre_start_stores_dingtalk_client(self):
        bus = MessageBus()
        channel = DingTalkChannel(bus, config={})
        handler = _DingTalkMessageHandler(channel)

        mock_client = MagicMock()
        handler.dingtalk_client = mock_client
        handler.pre_start()

        assert channel._dingtalk_client is mock_client

    def test_chatbot_message_stored_for_card_mode(self):
        bus = MessageBus()
        channel = DingTalkChannel(bus, config={"card_template_id": "tpl_123"})

        mock_message = MagicMock()
        mock_message.sender_staff_id = "user_001"
        mock_message.conversation_type = "1"
        mock_message.conversation_id = ""
        mock_message.message_id = "msg_001"
        mock_message.sender_nick = "TestUser"
        mock_message.message_type = "text"
        mock_message.text = MagicMock(content="hello")
        mock_message.rich_text_content = None

        channel._main_loop = MagicMock()
        channel._main_loop.is_running.return_value = False
        channel._allowed_users = set()
        channel._running = True

        channel._on_chatbot_message(mock_message)

        assert len(channel._incoming_messages) == 1
        stored_msg = list(channel._incoming_messages.values())[0]
        assert stored_msg is mock_message

    def test_card_replier_cleanup_on_final(self):
        async def go():
            bus = MessageBus()
            channel = DingTalkChannel(bus, config={"card_template_id": "tpl_123"})
            channel._client_id = "test_key"

            channel._stream_update_card = AsyncMock()

            source_key = f"{_CONVERSATION_TYPE_P2P}:user_001::msg_001"
            channel._card_track_ids[source_key] = "track_001"
            channel._card_repliers["track_001"] = MagicMock()

            msg = OutboundMessage(
                channel_name="dingtalk",
                chat_id="user_001",
                thread_id="thread_001",
                text="Final answer.",
                is_final=True,
                thread_ts="msg_001",
                metadata={
                    "conversation_type": _CONVERSATION_TYPE_P2P,
                    "sender_staff_id": "user_001",
                    "conversation_id": "",
                },
            )

            await channel.send(msg)

            assert source_key not in channel._card_track_ids
            assert "track_001" not in channel._card_repliers

        _run(go())

    def test_card_creation_without_sdk_client_returns_none(self):
        async def go():
            bus = MessageBus()
            channel = DingTalkChannel(bus, config={"card_template_id": "tpl_123"})
            channel._dingtalk_client = None

            result = await channel._create_and_deliver_card(
                "test",
                chatbot_message=MagicMock(),
            )
            assert result is None

        _run(go())

    def test_card_creation_without_chatbot_message_returns_none(self):
        async def go():
            bus = MessageBus()
            channel = DingTalkChannel(bus, config={"card_template_id": "tpl_123"})
            channel._dingtalk_client = MagicMock()

            result = await channel._create_and_deliver_card(
                "test",
                chatbot_message=None,
            )
            assert result is None

        _run(go())

    def test_stream_update_card_raises_without_replier(self):
        async def go():
            bus = MessageBus()
            channel = DingTalkChannel(bus, config={"card_template_id": "tpl_123"})

            with pytest.raises(RuntimeError, match="No AICardReplier found"):
                await channel._stream_update_card("nonexistent_track", "content")

        _run(go())

    def test_stop_clears_card_state(self):
        async def go():
            bus = MessageBus()
            channel = DingTalkChannel(bus, config={"card_template_id": "tpl_123"})
            channel._running = True
            channel._dingtalk_client = MagicMock()
            channel._incoming_messages["key"] = MagicMock()
            channel._card_repliers["track"] = MagicMock()
            channel._card_track_ids["source"] = "track"

            await channel.stop()

            assert channel._dingtalk_client is None
            assert channel._incoming_messages == {}
            assert channel._card_repliers == {}
            assert channel._card_track_ids == {}

        _run(go())
