"""Tests for the DingTalk channel implementation."""

from __future__ import annotations

import asyncio
import logging
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
from deerflow.config.paths import VIRTUAL_PATH_PREFIX


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _take_inbound(bus: MessageBus):
    inbound = await asyncio.wait_for(bus.get_inbound(), timeout=1)
    bus.inbound_task_done()
    return inbound


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

            inbound = await _take_inbound(bus)
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

            inbound = await _take_inbound(bus)
            assert inbound.channel_name == "dingtalk"
            assert inbound.chat_id == "conv_group_001"
            assert inbound.user_id == "user_002"
            assert inbound.text == "hello group"
            assert inbound.topic_id == "msg_group_001"
            assert inbound.metadata["conversation_type"] == _CONVERSATION_TYPE_GROUP
            assert inbound.metadata["conversation_id"] == "conv_group_001"

        _run(go())

    @pytest.mark.parametrize("text", ["@bot /new", "@_user_1 /help", "@bot /goal ship it"])
    def test_leading_mention_before_command_classifies_and_strips(self, text):
        """DingTalk group chats leave "@bot /new" in the text; classify as COMMAND
        and strip the mention so ChannelManager receives the bare command."""

        async def go():
            bus = MessageBus()
            bus.publish_inbound = AsyncMock()
            channel = DingTalkChannel(bus, config={})
            channel._client_id = "test_key"
            channel._main_loop = asyncio.get_event_loop()
            channel._running = True

            msg = _make_chatbot_message(
                text=text,
                conversation_type=_CONVERSATION_TYPE_GROUP,
                sender_staff_id="user_002",
                conversation_id="conv_group_001",
                message_id="msg_mention_cmd",
            )

            channel._send_running_reply = AsyncMock()
            channel._on_chatbot_message(msg)

            await asyncio.sleep(0.1)

            inbound = await _take_inbound(bus)
            assert inbound.msg_type == InboundMessageType.COMMAND, f"{text!r} should be COMMAND"
            assert not inbound.text.startswith("@"), "leading mention must be stripped for dispatch"
            assert inbound.text.split(maxsplit=1)[0] in KNOWN_CHANNEL_COMMANDS

        _run(go())

    def test_leading_mention_before_chat_keeps_mention(self):
        """A mentioned non-command stays CHAT and keeps the mention for the agent."""

        async def go():
            bus = MessageBus()
            bus.publish_inbound = AsyncMock()
            channel = DingTalkChannel(bus, config={})
            channel._client_id = "test_key"
            channel._main_loop = asyncio.get_event_loop()
            channel._running = True

            msg = _make_chatbot_message(
                text="@bot please summarise this",
                conversation_type=_CONVERSATION_TYPE_GROUP,
                sender_staff_id="user_002",
                conversation_id="conv_group_001",
                message_id="msg_mention_chat",
            )

            channel._send_running_reply = AsyncMock()
            channel._on_chatbot_message(msg)

            await asyncio.sleep(0.1)

            inbound = await _take_inbound(bus)
            assert inbound.msg_type == InboundMessageType.CHAT
            assert inbound.text == "@bot please summarise this"

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

            inbound = await _take_inbound(bus)
            assert inbound.chat_id == "conv_group_001"
            assert inbound.topic_id == "msg_group_002"
            assert inbound.metadata["conversation_type"] == _CONVERSATION_TYPE_GROUP

        _run(go())

    @pytest.mark.parametrize("sender_staff_id", ["", None])
    def test_p2p_message_without_sender_is_dropped(self, sender_staff_id):
        """A P2P chat_id *is* the sender, so an empty one keys every user to one thread.

        ``ChannelStore._key`` builds ``f"{channel}:{chat_id}"`` for a topic-less conversation,
        so publishing this would put every senderless P2P message under the literal
        ``"dingtalk:"`` — one shared thread, one shared history, across users.
        """

        async def go():
            bus = MessageBus()
            bus.publish_inbound = AsyncMock()
            channel = DingTalkChannel(bus, config={})
            channel._client_id = "test_key"
            channel._main_loop = asyncio.get_event_loop()
            channel._running = True

            msg = _make_chatbot_message(
                text="hello",
                conversation_type=_CONVERSATION_TYPE_P2P,
                sender_staff_id=sender_staff_id,
                message_id="msg_no_sender",
            )

            channel._send_running_reply = AsyncMock()
            channel._on_chatbot_message(msg)

            await asyncio.sleep(0.1)

            bus.publish_inbound.assert_not_awaited()
            assert bus.inbound_queue.empty()

        _run(go())

    def test_group_message_without_conversation_id_is_dropped(self):
        """The group route reaches the same degenerate key from the other side."""

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
                conversation_id="",
                message_id="msg_no_conv",
            )

            channel._send_running_reply = AsyncMock()
            channel._on_chatbot_message(msg)

            await asyncio.sleep(0.1)

            bus.publish_inbound.assert_not_awaited()
            assert bus.inbound_queue.empty()

        _run(go())

    def test_group_message_with_unknown_sender_is_still_delivered(self):
        """Reverse anchor: the guard is on the conversation identity, not on the sender.

        A group message identifies its conversation through ``conversation_id``, so an
        unknown sender must not cost the whole message.
        """

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
                sender_staff_id="",
                conversation_id="conv_group_003",
                message_id="msg_group_003",
            )

            channel._send_running_reply = AsyncMock()
            channel._on_chatbot_message(msg)

            await asyncio.sleep(0.1)

            inbound = await _take_inbound(bus)
            assert inbound.chat_id == "conv_group_003"
            assert inbound.topic_id == "msg_group_003"

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

            inbound = await _take_inbound(bus)
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

            inbound = await _take_inbound(bus)
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
            assert bus.inbound_queue.empty()

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
            await _take_inbound(bus)

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
            assert bus.inbound_queue.empty()

        _run(go())

    def test_non_allowed_user_message_content_not_logged(self, caplog):
        import logging

        async def go():
            bus = MessageBus()
            bus.publish_inbound = AsyncMock()
            channel = DingTalkChannel(bus, config={"allowed_users": ["user_001"]})
            channel._client_id = "test_key"
            channel._main_loop = asyncio.get_event_loop()
            channel._running = True

            msg = _make_chatbot_message(sender_staff_id="user_blocked", text="secret blocked content")
            with caplog.at_level(logging.INFO, logger="app.channels.dingtalk"):
                channel._on_chatbot_message(msg)
                await asyncio.sleep(0.1)

            bus.publish_inbound.assert_not_awaited()
            assert bus.inbound_queue.empty()
            # The parsed-message INFO log (with message content) must not fire for
            # a blocked sender — allowed_users still acts as a privacy/noise filter.
            assert "parsed message" not in caplog.text
            assert "secret blocked content" not in caplog.text

        _run(go())

    def test_connect_code_bypasses_allowed_users_filter(self):
        async def go():
            bus = MessageBus()
            bus.publish_inbound = AsyncMock()
            channel = DingTalkChannel(bus, config={"allowed_users": ["user_001"], "connection_repo": object()})
            channel._client_id = "test_key"
            channel._main_loop = asyncio.get_event_loop()
            channel._running = True
            channel._bind_connection_from_connect_code = AsyncMock(return_value=True)

            msg = _make_chatbot_message(sender_staff_id="user_blocked", text="/connect dingtalk-bind-code")
            channel._on_chatbot_message(msg)

            await asyncio.sleep(0.1)
            channel._bind_connection_from_connect_code.assert_awaited_once()
            bus.publish_inbound.assert_not_awaited()
            assert bus.inbound_queue.empty()

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
            await _take_inbound(bus)

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
            inbound = await _take_inbound(bus)
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
            inbound = await _take_inbound(bus)
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
        async def go():
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

            channel._main_loop = asyncio.get_running_loop()
            channel._allowed_users = set()
            channel._running = True
            channel._send_running_reply = AsyncMock()

            channel._on_chatbot_message(mock_message)
            await asyncio.sleep(0.1)

            assert len(channel._incoming_messages) == 1
            stored_msg = list(channel._incoming_messages.values())[0]
            assert stored_msg is mock_message
            await _take_inbound(bus)

        _run(go())

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


# ---------------------------------------------------------------------------
# Inbound file support
# ---------------------------------------------------------------------------


def _make_picture_message(*, download_code: str = "dc_img", **kwargs):
    """Build a mock DingTalk ``picture`` message carrying an ImageContent."""
    msg = _make_chatbot_message(text="", message_type="picture", **kwargs)
    msg.image_content = SimpleNamespace(download_code=download_code)
    return msg


def _make_file_message(*, download_code: str = "dc_file", file_name: str | None = "report.xlsx", **kwargs):
    """Build a mock DingTalk ``file`` (document) message.

    dingtalk_stream does not parse ``file`` messages, so the descriptor lives on
    the raw callback payload the handler stashes as ``_df_raw_data``.
    """
    msg = _make_chatbot_message(text="", message_type="file", **kwargs)
    content: dict = {"downloadCode": download_code}
    if file_name is not None:
        content["fileName"] = file_name
    msg._df_raw_data = {"msgtype": "file", "content": content}
    return msg


def _patch_uploads(monkeypatch, uploads_dir, *, sandbox_id="local", sandbox=None):
    monkeypatch.setattr(
        "app.channels.dingtalk.get_paths",
        lambda: SimpleNamespace(
            ensure_thread_dirs=lambda thread_id, user_id=None: None,
            sandbox_uploads_dir=lambda thread_id, user_id=None: uploads_dir,
        ),
    )
    monkeypatch.setattr("app.channels.dingtalk.get_effective_user_id", lambda: "default")

    async def _acquire_async(thread_id, user_id=None):
        return sandbox_id

    monkeypatch.setattr(
        "app.channels.dingtalk.get_sandbox_provider",
        lambda: SimpleNamespace(acquire_async=_acquire_async, get=lambda sid: sandbox),
    )


class TestExtractFiles:
    def test_text_message_has_no_files(self):
        assert DingTalkChannel._extract_files(_make_chatbot_message(text="hi")) == []

    def test_picture_message(self):
        files = DingTalkChannel._extract_files(_make_picture_message(download_code="dc_1"))
        assert files == [{"type": "image", "download_code": "dc_1", "filename": "image.png"}]

    def test_picture_message_missing_download_code_ignored(self):
        msg = _make_chatbot_message(text="", message_type="picture")
        msg.image_content = SimpleNamespace(download_code=None)
        assert DingTalkChannel._extract_files(msg) == []

    def test_rich_text_images(self):
        msg = _make_chatbot_message(text="", message_type="richText")
        msg.get_image_list = lambda: ["dc_a", "dc_b"]
        files = DingTalkChannel._extract_files(msg)
        assert files == [
            {"type": "image", "download_code": "dc_a", "filename": "image_0.png"},
            {"type": "image", "download_code": "dc_b", "filename": "image_1.png"},
        ]

    def test_rich_text_get_image_list_failure_is_logged_not_silent(self, caplog):
        """An SDK parse failure must be distinguishable from "no inline images"."""
        msg = _make_chatbot_message(text="", message_type="richText")

        def _boom():
            raise RuntimeError("sdk failure")

        msg.get_image_list = _boom
        with caplog.at_level(logging.WARNING, logger="app.channels.dingtalk"):
            assert DingTalkChannel._extract_files(msg) == []

        assert any("failed to read inline images" in r.message for r in caplog.records)

    def test_file_message_from_raw_data(self):
        files = DingTalkChannel._extract_files(_make_file_message(download_code="dc_doc", file_name="报价.xlsx"))
        assert files == [{"type": "file", "download_code": "dc_doc", "filename": "报价.xlsx"}]

    def test_file_message_default_filename(self):
        files = DingTalkChannel._extract_files(_make_file_message(download_code="dc_doc", file_name=None))
        assert files == [{"type": "file", "download_code": "dc_doc", "filename": "file.bin"}]

    def test_file_message_without_raw_data_ignored(self):
        msg = _make_chatbot_message(text="", message_type="file")
        assert DingTalkChannel._extract_files(msg) == []


class TestOnChatbotMessageFiles:
    def test_picture_message_publishes_inbound_with_files(self):
        async def go():
            bus = MessageBus()
            bus.publish_inbound = AsyncMock()
            channel = DingTalkChannel(bus, config={})
            channel._client_id = "test_key"
            channel._main_loop = asyncio.get_event_loop()
            channel._running = True
            channel._send_running_reply = AsyncMock()

            channel._on_chatbot_message(_make_picture_message(download_code="dc_pic", sender_staff_id="u1", message_id="m1"))
            await asyncio.sleep(0.1)

            inbound = await _take_inbound(bus)
            assert inbound.msg_type == InboundMessageType.CHAT
            assert inbound.files == [{"type": "image", "download_code": "dc_pic", "filename": "image.png"}]

        _run(go())

    def test_file_message_publishes_inbound_with_files(self):
        async def go():
            bus = MessageBus()
            bus.publish_inbound = AsyncMock()
            channel = DingTalkChannel(bus, config={})
            channel._client_id = "test_key"
            channel._main_loop = asyncio.get_event_loop()
            channel._running = True
            channel._send_running_reply = AsyncMock()

            channel._on_chatbot_message(_make_file_message(download_code="dc_doc", file_name="data.csv", sender_staff_id="u1", message_id="m1"))
            await asyncio.sleep(0.1)

            inbound = await _take_inbound(bus)
            assert inbound.files == [{"type": "file", "download_code": "dc_doc", "filename": "data.csv"}]

        _run(go())

    def test_message_without_text_or_files_dropped(self):
        async def go():
            bus = MessageBus()
            bus.publish_inbound = AsyncMock()
            channel = DingTalkChannel(bus, config={})
            channel._client_id = "test_key"
            channel._main_loop = asyncio.get_event_loop()
            channel._running = True

            # picture message whose image carries no download_code -> no files, no text
            msg = _make_chatbot_message(text="", message_type="picture")
            msg.image_content = SimpleNamespace(download_code=None)
            channel._on_chatbot_message(msg)
            await asyncio.sleep(0.1)

            bus.publish_inbound.assert_not_awaited()
            assert bus.inbound_queue.empty()

        _run(go())


class TestReceiveFile:
    def test_no_files_is_noop(self):
        async def go():
            channel = DingTalkChannel(MessageBus(), config={})
            msg = channel._make_inbound(chat_id="c", user_id="u", text="hi", thread_ts="m")
            out = await channel.receive_file(msg, "t1")
            assert out is msg
            assert out.text == "hi"

        _run(go())

    def test_downloads_persists_and_prepends_path(self, tmp_path, monkeypatch):
        async def go():
            channel = DingTalkChannel(MessageBus(), config={})
            channel._client_id = "robot"
            channel._download_by_code = AsyncMock(return_value=b"XLSXDATA")
            uploads = tmp_path / "uploads"
            uploads.mkdir()
            _patch_uploads(monkeypatch, uploads)

            msg = channel._make_inbound(
                chat_id="c",
                user_id="u",
                text="please translate",
                thread_ts="m",
                files=[{"type": "file", "download_code": "dc1", "filename": "quote.xlsx"}],
            )
            out = await channel.receive_file(msg, "thread-1", user_id="default")

            assert out.files == []
            assert (uploads / "quote.xlsx").read_bytes() == b"XLSXDATA"
            assert f"{VIRTUAL_PATH_PREFIX}/uploads/quote.xlsx" in out.text
            assert out.text.endswith("please translate")
            channel._download_by_code.assert_awaited_once_with("dc1")

        _run(go())

    def test_pure_file_message_text_is_only_the_path(self, tmp_path, monkeypatch):
        async def go():
            channel = DingTalkChannel(MessageBus(), config={})
            channel._download_by_code = AsyncMock(return_value=b"IMG")
            uploads = tmp_path / "uploads"
            uploads.mkdir()
            _patch_uploads(monkeypatch, uploads)

            msg = channel._make_inbound(
                chat_id="c",
                user_id="u",
                text="",
                thread_ts="m",
                files=[{"type": "image", "download_code": "dc_i", "filename": "image.png"}],
            )
            out = await channel.receive_file(msg, "t1", user_id="default")

            assert out.text == f"{VIRTUAL_PATH_PREFIX}/uploads/image.png"

        _run(go())

    def test_download_failure_surfaces_marker(self):
        """A failed download must stay visible to the agent, not vanish silently."""

        async def go():
            channel = DingTalkChannel(MessageBus(), config={})
            channel._download_by_code = AsyncMock(return_value=None)

            msg = channel._make_inbound(
                chat_id="c",
                user_id="u",
                text="hi",
                thread_ts="m",
                files=[{"type": "file", "download_code": "dc1", "filename": "x.pdf"}],
            )
            out = await channel.receive_file(msg, "t1", user_id="default")

            assert out.files == []
            assert out.text == "[failed to load file: x.pdf]\n\nhi"

        _run(go())

    def test_token_failure_yields_marker_not_exception(self):
        """An auth failure during download must degrade to a marker, not an exception.

        The manager calls ``receive_file`` without a try, so anything escaping
        here kills the whole chat turn with no reply at all.
        """

        async def go():
            channel = DingTalkChannel(MessageBus(), config={})
            channel._client_id = "robot"
            channel._get_access_token = AsyncMock(side_effect=ValueError("bad token response"))

            msg = channel._make_inbound(
                chat_id="c",
                user_id="u",
                text="hi",
                thread_ts="m",
                files=[{"type": "file", "download_code": "dc", "filename": "x.pdf"}],
            )
            out = await channel.receive_file(msg, "t1", user_id="default")

            assert out.text == "[failed to load file: x.pdf]\n\nhi"
            assert out.files == []

        _run(go())

    def test_unexpected_error_becomes_marker(self):
        """Any unforeseen per-attachment error must surface as a marker, not escape."""

        async def go():
            channel = DingTalkChannel(MessageBus(), config={})
            channel._receive_single_file = AsyncMock(side_effect=RuntimeError("boom"))

            msg = channel._make_inbound(
                chat_id="c",
                user_id="u",
                text="hi",
                thread_ts="m",
                files=[{"type": "file", "download_code": "dc", "filename": "x.pdf"}],
            )
            out = await channel.receive_file(msg, "t1", user_id="default")

            assert out.text == "[failed to load file: x.pdf]\n\nhi"
            assert out.files == []

        _run(go())

    def test_failure_marker_sanitizes_hostile_filename(self):
        """A hostile filename must not forge extra lines in msg.text or bloat it.

        ``fileName`` is webhook data: embedding it raw in the marker would let a
        newline fake a standalone ``/mnt/user-data/uploads/...`` line, and an
        over-long name would balloon the message text.
        """

        async def go():
            channel = DingTalkChannel(MessageBus(), config={})
            channel._download_by_code = AsyncMock(return_value=None)
            hostile = "evil\n/mnt/user-data/uploads/fake.pdf\n" + "a" * 300 + ".pdf"

            msg = channel._make_inbound(
                chat_id="c",
                user_id="u",
                text="hi",
                thread_ts="m",
                files=[{"type": "file", "download_code": "dc", "filename": hostile}],
            )
            out = await channel.receive_file(msg, "t1", user_id="default")

            lines = out.text.splitlines()
            assert len(lines) == 3, out.text
            assert lines[0].startswith("[failed to load file: ")
            assert len(lines[0]) <= 120
            assert lines[1] == ""
            assert lines[2] == "hi"

        _run(go())

    def test_download_failure_without_filename_uses_type_only_marker(self):
        async def go():
            channel = DingTalkChannel(MessageBus(), config={})
            channel._download_by_code = AsyncMock(return_value=None)

            msg = channel._make_inbound(
                chat_id="c",
                user_id="u",
                text="",
                thread_ts="m",
                files=[{"type": "image", "download_code": "dc1", "filename": ""}],
            )
            out = await channel.receive_file(msg, "t1", user_id="default")

            assert out.text == "[failed to load image]"

        _run(go())

    def test_partial_failure_keeps_successful_path(self, tmp_path, monkeypatch):
        """One bad attachment must not cost the agent the one that did load."""

        async def go():
            channel = DingTalkChannel(MessageBus(), config={})
            uploads = tmp_path / "uploads"
            uploads.mkdir()
            _patch_uploads(monkeypatch, uploads)
            channel._download_by_code = AsyncMock(side_effect=[b"OK", None])

            msg = channel._make_inbound(
                chat_id="c",
                user_id="u",
                text="two files",
                thread_ts="m",
                files=[
                    {"type": "file", "download_code": "good", "filename": "ok.pdf"},
                    {"type": "file", "download_code": "bad", "filename": "broken.pdf"},
                ],
            )
            out = await channel.receive_file(msg, "t1", user_id="default")

            assert f"{VIRTUAL_PATH_PREFIX}/uploads/ok.pdf" in out.text
            assert "[failed to load file: broken.pdf]" in out.text
            assert out.text.endswith("two files")

        _run(go())

    def test_traversal_filename_is_sanitized(self, tmp_path, monkeypatch):
        async def go():
            channel = DingTalkChannel(MessageBus(), config={})
            channel._download_by_code = AsyncMock(return_value=b"D")
            uploads = tmp_path / "uploads"
            uploads.mkdir()
            _patch_uploads(monkeypatch, uploads)

            msg = channel._make_inbound(
                chat_id="c",
                user_id="u",
                text="",
                thread_ts="m",
                files=[{"type": "file", "download_code": "dc", "filename": "../../etc/passwd"}],
            )
            out = await channel.receive_file(msg, "t1", user_id="default")

            written = list(uploads.iterdir())
            assert len(written) == 1
            assert written[0].name == "passwd"
            assert out.text == f"{VIRTUAL_PATH_PREFIX}/uploads/passwd"

        _run(go())

    def test_rejected_filename_falls_back_to_generated_name(self, tmp_path, monkeypatch):
        """A filename normalize_filename rejects must land on the generated name.

        ``".."`` raises inside ``normalize_filename`` (unlike ``../../etc/passwd``,
        whose basename ``passwd`` is accepted), so this exercises the except branch.
        """

        async def go():
            channel = DingTalkChannel(MessageBus(), config={})
            channel._download_by_code = AsyncMock(return_value=b"D")
            uploads = tmp_path / "uploads"
            uploads.mkdir()
            _patch_uploads(monkeypatch, uploads)

            msg = channel._make_inbound(
                chat_id="c",
                user_id="u",
                text="",
                thread_ts="m",
                files=[{"type": "file", "download_code": "abc123456789", "filename": ".."}],
            )
            out = await channel.receive_file(msg, "t1", user_id="default")

            written = list(uploads.iterdir())
            assert len(written) == 1
            assert written[0].name == "dingtalk_abc123456789.bin"
            assert out.text == f"{VIRTUAL_PATH_PREFIX}/uploads/dingtalk_abc123456789.bin"

        _run(go())

    def test_fallback_name_sanitizes_download_code(self, tmp_path, monkeypatch):
        """download_code is webhook data: it must not inject path separators."""

        async def go():
            channel = DingTalkChannel(MessageBus(), config={})
            channel._download_by_code = AsyncMock(return_value=b"D")
            uploads = tmp_path / "uploads"
            uploads.mkdir()
            _patch_uploads(monkeypatch, uploads)

            msg = channel._make_inbound(
                chat_id="c",
                user_id="u",
                text="",
                thread_ts="m",
                files=[{"type": "image", "download_code": "../../evil", "filename": ".."}],
            )
            out = await channel.receive_file(msg, "t1", user_id="default")

            written = list(uploads.iterdir())
            assert len(written) == 1
            assert "/" not in written[0].name
            assert written[0].name == "dingtalk_evil.png"
            assert out.text == f"{VIRTUAL_PATH_PREFIX}/uploads/dingtalk_evil.png"

        _run(go())

    def test_second_picture_does_not_overwrite_first(self, tmp_path, monkeypatch):
        """Two picture messages both generate "image.png" and must not collide.

        The path handed to the agent must still hold the bytes it referred to.
        """

        async def go():
            channel = DingTalkChannel(MessageBus(), config={})
            uploads = tmp_path / "uploads"
            uploads.mkdir()
            _patch_uploads(monkeypatch, uploads)

            channel._download_by_code = AsyncMock(return_value=b"FIRST")
            first = channel._make_inbound(
                chat_id="c",
                user_id="u",
                text="",
                thread_ts="m1",
                files=[{"type": "image", "download_code": "dc1", "filename": "image.png"}],
            )
            out_first = await channel.receive_file(first, "t1", user_id="default")

            channel._download_by_code = AsyncMock(return_value=b"SECOND")
            second = channel._make_inbound(
                chat_id="c",
                user_id="u",
                text="",
                thread_ts="m2",
                files=[{"type": "image", "download_code": "dc2", "filename": "image.png"}],
            )
            out_second = await channel.receive_file(second, "t1", user_id="default")

            assert out_first.text != out_second.text
            first_name = out_first.text.rsplit("/", 1)[-1]
            second_name = out_second.text.rsplit("/", 1)[-1]
            # Each advertised path must still resolve to its own bytes.
            assert (uploads / first_name).read_bytes() == b"FIRST"
            assert (uploads / second_name).read_bytes() == b"SECOND"

        _run(go())

    def test_multiple_images_in_one_message_get_distinct_paths(self, tmp_path, monkeypatch):
        async def go():
            channel = DingTalkChannel(MessageBus(), config={})
            uploads = tmp_path / "uploads"
            uploads.mkdir()
            _patch_uploads(monkeypatch, uploads)
            channel._download_by_code = AsyncMock(side_effect=[b"A", b"B"])

            msg = channel._make_inbound(
                chat_id="c",
                user_id="u",
                text="",
                thread_ts="m",
                files=[
                    {"type": "image", "download_code": "dc1", "filename": "image_0.png"},
                    {"type": "image", "download_code": "dc2", "filename": "image_0.png"},
                ],
            )
            out = await channel.receive_file(msg, "t1", user_id="default")

            paths = out.text.split("\n")
            assert len(paths) == 2
            assert paths[0] != paths[1]
            assert len(list(uploads.iterdir())) == 2
            assert {p.read_bytes() for p in uploads.iterdir()} == {b"A", b"B"}

        _run(go())

    def test_duplicate_document_names_do_not_collide(self, tmp_path, monkeypatch):
        """The same real filename sent twice must not clobber the earlier upload."""

        async def go():
            channel = DingTalkChannel(MessageBus(), config={})
            uploads = tmp_path / "uploads"
            uploads.mkdir()
            _patch_uploads(monkeypatch, uploads)

            channel._download_by_code = AsyncMock(return_value=b"V1")
            m1 = channel._make_inbound(chat_id="c", user_id="u", text="", thread_ts="m1", files=[{"type": "file", "download_code": "d1", "filename": "quote.xlsx"}])
            await channel.receive_file(m1, "t1", user_id="default")

            channel._download_by_code = AsyncMock(return_value=b"V2")
            m2 = channel._make_inbound(chat_id="c", user_id="u", text="", thread_ts="m2", files=[{"type": "file", "download_code": "d2", "filename": "quote.xlsx"}])
            await channel.receive_file(m2, "t1", user_id="default")

            assert (uploads / "quote.xlsx").read_bytes() == b"V1"
            assert len(list(uploads.iterdir())) == 2

        _run(go())

    def test_write_does_not_follow_planted_symlink(self, tmp_path, monkeypatch):
        """A symlink planted at the destination must not be written through.

        Upload dirs can be mounted into local sandboxes, so a sandbox process can
        leave a symlink at a future upload name; following it would let a
        gateway-privileged write land outside the bucket.
        """

        async def go():
            channel = DingTalkChannel(MessageBus(), config={})
            uploads = tmp_path / "uploads"
            uploads.mkdir()
            outside = tmp_path / "outside.txt"
            (uploads / "image.png").symlink_to(outside)
            _patch_uploads(monkeypatch, uploads)
            channel._download_by_code = AsyncMock(return_value=b"PWNED")

            msg = channel._make_inbound(
                chat_id="c",
                user_id="u",
                text="",
                thread_ts="m",
                files=[{"type": "image", "download_code": "dc", "filename": "image.png"}],
            )
            out = await channel.receive_file(msg, "t1", user_id="default")

            assert not outside.exists()
            assert "[failed to load image: image.png]" in out.text

        _run(go())

    def test_missing_sandbox_after_acquire_yields_marker(self, tmp_path, monkeypatch):
        """A non-local sandbox that cannot be resolved must not yield a path.

        The agent's sandbox cannot see the file in that case, so handing it the
        virtual path would point at nothing readable; mirror Feishu and surface
        a failed-load marker instead.
        """

        async def go():
            channel = DingTalkChannel(MessageBus(), config={})
            channel._download_by_code = AsyncMock(return_value=b"BYTES")
            uploads = tmp_path / "uploads"
            uploads.mkdir()
            _patch_uploads(monkeypatch, uploads, sandbox_id="aio:box1", sandbox=None)

            msg = channel._make_inbound(
                chat_id="c",
                user_id="u",
                text="hi",
                thread_ts="m",
                files=[{"type": "file", "download_code": "dc", "filename": "a.pdf"}],
            )
            out = await channel.receive_file(msg, "t1", user_id="default")

            assert out.text == "[failed to load file: a.pdf]\n\nhi"

        _run(go())

    def test_update_file_failure_yields_marker(self, tmp_path, monkeypatch):
        """A failed non-local sandbox sync must not yield a path either.

        Same failure mode as the missing-sandbox case: the bytes never reached
        the agent's sandbox, so the virtual path would read as nothing. Mirrors
        Feishu, whose sync except-branch returns the failure marker.
        """

        async def go():
            channel = DingTalkChannel(MessageBus(), config={})
            channel._download_by_code = AsyncMock(return_value=b"BYTES")
            uploads = tmp_path / "uploads"
            uploads.mkdir()
            broken_sandbox = MagicMock()
            broken_sandbox.update_file.side_effect = RuntimeError("sandbox transport down")
            _patch_uploads(monkeypatch, uploads, sandbox_id="aio:box1", sandbox=broken_sandbox)

            msg = channel._make_inbound(
                chat_id="c",
                user_id="u",
                text="hi",
                thread_ts="m",
                files=[{"type": "file", "download_code": "dc", "filename": "a.pdf"}],
            )
            out = await channel.receive_file(msg, "t1", user_id="default")

            assert out.text == "[failed to load file: a.pdf]\n\nhi"

        _run(go())

    def test_non_local_sandbox_is_synced(self, tmp_path, monkeypatch):
        async def go():
            channel = DingTalkChannel(MessageBus(), config={})
            channel._download_by_code = AsyncMock(return_value=b"BYTES")
            uploads = tmp_path / "uploads"
            uploads.mkdir()
            fake_sandbox = MagicMock()
            _patch_uploads(monkeypatch, uploads, sandbox_id="aio:box1", sandbox=fake_sandbox)

            msg = channel._make_inbound(
                chat_id="c",
                user_id="u",
                text="",
                thread_ts="m",
                files=[{"type": "file", "download_code": "dc", "filename": "a.pdf"}],
            )
            await channel.receive_file(msg, "t1", user_id="default")

            fake_sandbox.update_file.assert_called_once_with(f"{VIRTUAL_PATH_PREFIX}/uploads/a.pdf", b"BYTES")

        _run(go())


class TestDownloadByCode:
    def test_two_step_download(self):
        async def go():
            from unittest.mock import patch

            channel = DingTalkChannel(MessageBus(), config={})
            channel._client_id = "robot_x"
            channel._get_access_token = AsyncMock(return_value="tok")

            class PostResponse:
                status_code = 200

                @staticmethod
                def json():
                    return {"downloadUrl": "https://dl.dingtalk/xyz"}

            captured: dict = {}

            class FakeStream:
                async def __aenter__(self):
                    return self

                async def __aexit__(self, *a):
                    pass

                def raise_for_status(self):
                    pass

                async def aiter_bytes(self):
                    yield b"FILE"
                    yield b"BYTES"

            class FakeClient:
                async def __aenter__(self):
                    return self

                async def __aexit__(self, *a):
                    pass

                async def post(self, url, **kwargs):
                    captured["post_url"] = url
                    captured["json"] = kwargs.get("json")
                    return PostResponse()

                def stream(self, method, url, **kwargs):
                    captured["get_url"] = url
                    return FakeStream()

            with patch("app.channels.dingtalk.httpx.AsyncClient", return_value=FakeClient()):
                data = await channel._download_by_code("dl_code")

            assert data == b"FILEBYTES"
            assert captured["post_url"].endswith("/v1.0/robot/messageFiles/download")
            assert captured["json"] == {"downloadCode": "dl_code", "robotCode": "robot_x"}
            assert captured["get_url"] == "https://dl.dingtalk/xyz"

        _run(go())

    def test_oversized_download_is_dropped(self, monkeypatch):
        """Inbound bytes are buffered in memory; a file over the cap must be refused.

        Outbound uploads already enforce a size cap — without an inbound one, a
        single large chat attachment balloons gateway memory.
        """

        async def go():
            from unittest.mock import patch

            channel = DingTalkChannel(MessageBus(), config={})
            channel._client_id = "robot_x"
            channel._get_access_token = AsyncMock(return_value="tok")
            monkeypatch.setattr("app.channels.dingtalk._MAX_INBOUND_FILE_SIZE_BYTES", 10)

            class PostResponse:
                status_code = 200

                @staticmethod
                def json():
                    return {"downloadUrl": "https://dl.dingtalk/big"}

            class FakeStream:
                async def __aenter__(self):
                    return self

                async def __aexit__(self, *a):
                    pass

                def raise_for_status(self):
                    pass

                async def aiter_bytes(self):
                    for _ in range(4):
                        yield b"x" * 8

            class FakeClient:
                async def __aenter__(self):
                    return self

                async def __aexit__(self, *a):
                    pass

                async def post(self, url, **kwargs):
                    return PostResponse()

                def stream(self, method, url, **kwargs):
                    return FakeStream()

            with patch("app.channels.dingtalk.httpx.AsyncClient", return_value=FakeClient()):
                assert await channel._download_by_code("dl") is None

        _run(go())

    def test_post_non_200_returns_none(self):
        async def go():
            from unittest.mock import patch

            channel = DingTalkChannel(MessageBus(), config={})
            channel._client_id = "robot_x"
            channel._get_access_token = AsyncMock(return_value="tok")

            class PostResponse:
                status_code = 403
                text = "forbidden"

            class FakeClient:
                async def __aenter__(self):
                    return self

                async def __aexit__(self, *a):
                    pass

                async def post(self, url, **kwargs):
                    return PostResponse()

            with patch("app.channels.dingtalk.httpx.AsyncClient", return_value=FakeClient()):
                assert await channel._download_by_code("dl") is None

        _run(go())

    def test_missing_download_url_returns_none(self):
        async def go():
            from unittest.mock import patch

            channel = DingTalkChannel(MessageBus(), config={})
            channel._client_id = "robot_x"
            channel._get_access_token = AsyncMock(return_value="tok")

            class PostResponse:
                status_code = 200

                @staticmethod
                def json():
                    return {}

            class FakeClient:
                async def __aenter__(self):
                    return self

                async def __aexit__(self, *a):
                    pass

                async def post(self, url, **kwargs):
                    return PostResponse()

            with patch("app.channels.dingtalk.httpx.AsyncClient", return_value=FakeClient()):
                assert await channel._download_by_code("dl") is None

        _run(go())


class TestHandlerStashesRawData:
    def test_process_stashes_raw_callback_payload(self):
        pytest.importorskip("dingtalk_stream")

        async def go():
            bus = MessageBus()
            channel = DingTalkChannel(bus, config={})
            captured: dict = {}
            channel._on_chatbot_message = lambda m: captured.update(msg=m)
            handler = _DingTalkMessageHandler(channel)
            cb = MagicMock()
            cb.data = {
                "msgtype": "file",
                "content": {"downloadCode": "dc_doc", "fileName": "a.xlsx"},
                "senderStaffId": "u1",
                "conversationType": "1",
                "msgId": "m1",
            }
            await handler.process(cb)

            msg = captured["msg"]
            assert getattr(msg, "_df_raw_data", None) == cb.data
            # _extract_files can now read the document descriptor from the stash.
            assert DingTalkChannel._extract_files(msg) == [{"type": "file", "download_code": "dc_doc", "filename": "a.xlsx"}]

        _run(go())
