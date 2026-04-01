import json
import sys
from unittest.mock import MagicMock

import pytest

from app.channels.feishu import FeishuChannel
from app.channels.message_bus import InboundMessageType, MessageBus, is_slash_command


def test_feishu_on_message_plain_text():
    bus = MessageBus()
    config = {"app_id": "test", "app_secret": "test"}
    channel = FeishuChannel(bus, config)

    # Create mock event
    event = MagicMock()
    event.event.message.chat_id = "chat_1"
    event.event.message.message_id = "msg_1"
    event.event.message.root_id = None
    event.event.sender.sender_id.open_id = "user_1"

    # Plain text content
    content_dict = {"text": "Hello world"}
    event.event.message.content = json.dumps(content_dict)

    # Call _on_message
    channel._on_message(event)

    # Since main_loop isn't running in this synchronous test, we can't easily assert on bus,
    # but we can intercept _make_inbound to check the parsed text.
    with pytest.MonkeyPatch.context() as m:
        mock_make_inbound = MagicMock()
        m.setattr(channel, "_make_inbound", mock_make_inbound)
        channel._on_message(event)

        mock_make_inbound.assert_called_once()
        assert mock_make_inbound.call_args[1]["text"] == "Hello world"


def test_feishu_on_message_rich_text():
    bus = MessageBus()
    config = {"app_id": "test", "app_secret": "test"}
    channel = FeishuChannel(bus, config)

    # Create mock event
    event = MagicMock()
    event.event.message.chat_id = "chat_1"
    event.event.message.message_id = "msg_1"
    event.event.message.root_id = None
    event.event.sender.sender_id.open_id = "user_1"

    # Rich text content (topic group / post)
    content_dict = {"content": [[{"tag": "text", "text": "Paragraph 1, part 1."}, {"tag": "text", "text": "Paragraph 1, part 2."}], [{"tag": "at", "text": "@bot"}, {"tag": "text", "text": " Paragraph 2."}]]}
    event.event.message.content = json.dumps(content_dict)

    with pytest.MonkeyPatch.context() as m:
        mock_make_inbound = MagicMock()
        m.setattr(channel, "_make_inbound", mock_make_inbound)
        channel._on_message(event)

        mock_make_inbound.assert_called_once()
        parsed_text = mock_make_inbound.call_args[1]["text"]

        # Expected text:
        # Paragraph 1, part 1. Paragraph 1, part 2.
        #
        # @bot  Paragraph 2.
        assert "Paragraph 1, part 1. Paragraph 1, part 2." in parsed_text
        assert "@bot  Paragraph 2." in parsed_text
        assert "\n\n" in parsed_text


def test_feishu_on_message_path_treated_as_chat():
    bus = MessageBus()
    config = {"app_id": "test", "app_secret": "test"}
    channel = FeishuChannel(bus, config)

    event = MagicMock()
    event.event.message.chat_id = "chat_1"
    event.event.message.message_id = "msg_1"
    event.event.message.root_id = None
    event.event.sender.sender_id.open_id = "user_1"
    content_dict = {"text": "/home/user/file.txt"}
    event.event.message.content = json.dumps(content_dict)

    with pytest.MonkeyPatch.context() as m:
        mock_make_inbound = MagicMock()
        m.setattr(channel, "_make_inbound", mock_make_inbound)
        channel._on_message(event)

        mock_make_inbound.assert_called_once()
        assert mock_make_inbound.call_args[1]["msg_type"] == InboundMessageType.CHAT


def test_feishu_on_message_slash_new_treated_as_command():
    bus = MessageBus()
    config = {"app_id": "test", "app_secret": "test"}
    channel = FeishuChannel(bus, config)

    event = MagicMock()
    event.event.message.chat_id = "chat_1"
    event.event.message.message_id = "msg_1"
    event.event.message.root_id = None
    event.event.sender.sender_id.open_id = "user_1"
    content_dict = {"text": "/new"}
    event.event.message.content = json.dumps(content_dict)

    with pytest.MonkeyPatch.context() as m:
        mock_make_inbound = MagicMock()
        m.setattr(channel, "_make_inbound", mock_make_inbound)
        channel._on_message(event)

        mock_make_inbound.assert_called_once()
        assert mock_make_inbound.call_args[1]["msg_type"] == InboundMessageType.COMMAND


# ---------------------------------------------------------------------------
# is_slash_command unit tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["/new", "/status", "/models", "/memory", "/bootstrap", "/help"])
def test_is_slash_command_recognises_known_commands(text):
    assert is_slash_command(text) is True


@pytest.mark.parametrize("text", ["/home/user/file.txt", "/etc/config", "/usr/bin/python"])
def test_is_slash_command_rejects_paths(text):
    assert is_slash_command(text) is False


def test_is_slash_command_rejects_plain_text():
    assert is_slash_command("hello world") is False


# ---------------------------------------------------------------------------
# Slack command classification tests
# ---------------------------------------------------------------------------


def _make_slack_channel():
    """Create a SlackChannel instance with mocked SDK imports."""
    # Ensure slack_sdk is importable even when not installed
    if "slack_sdk" not in sys.modules:
        sys.modules.setdefault("slack_sdk", MagicMock())
        sys.modules.setdefault("slack_sdk.socket_mode", MagicMock())
        sys.modules.setdefault("slack_sdk.socket_mode.response", MagicMock())
    if "markdown_to_mrkdwn" not in sys.modules:
        sys.modules.setdefault("markdown_to_mrkdwn", MagicMock())

    from app.channels.slack import SlackChannel

    bus = MessageBus()
    config = {"bot_token": "xoxb-test", "app_token": "xapp-test"}
    return SlackChannel(bus, config)


def test_slack_path_treated_as_chat():
    channel = _make_slack_channel()
    event = {
        "user": "U123",
        "text": "/home/user/file.txt",
        "channel": "C123",
        "ts": "1234567890.123456",
    }

    with pytest.MonkeyPatch.context() as m:
        mock_make_inbound = MagicMock()
        m.setattr(channel, "_make_inbound", mock_make_inbound)
        m.setattr(channel, "_loop", None)  # prevent asyncio scheduling
        channel._handle_message_event(event)

        mock_make_inbound.assert_called_once()
        assert mock_make_inbound.call_args[1]["msg_type"] == InboundMessageType.CHAT


def test_slack_slash_new_treated_as_command():
    channel = _make_slack_channel()
    event = {
        "user": "U123",
        "text": "/new",
        "channel": "C123",
        "ts": "1234567890.123456",
    }

    with pytest.MonkeyPatch.context() as m:
        mock_make_inbound = MagicMock()
        m.setattr(channel, "_make_inbound", mock_make_inbound)
        m.setattr(channel, "_loop", None)
        channel._handle_message_event(event)

        mock_make_inbound.assert_called_once()
        assert mock_make_inbound.call_args[1]["msg_type"] == InboundMessageType.COMMAND
