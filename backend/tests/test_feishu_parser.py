import json
from unittest.mock import MagicMock

import pytest

from app.channels.feishu import FeishuChannel
from app.channels.message_bus import InboundMessageType, MessageBus


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


@pytest.mark.parametrize(
    ("text", "expected_type"),
    [
        ("/new project kickoff", InboundMessageType.COMMAND),
        ("/mnt/user-data/project-plan.md", InboundMessageType.CHAT),
    ],
)
def test_feishu_command_detection_only_matches_supported_commands(text, expected_type):
    bus = MessageBus()
    config = {"app_id": "test", "app_secret": "test"}
    channel = FeishuChannel(bus, config)

    event = MagicMock()
    event.event.message.chat_id = "chat_1"
    event.event.message.message_id = "msg_1"
    event.event.message.root_id = None
    event.event.sender.sender_id.open_id = "user_1"
    event.event.message.content = json.dumps({"text": text})

    with pytest.MonkeyPatch.context() as m:
        mock_make_inbound = MagicMock()
        m.setattr(channel, "_make_inbound", mock_make_inbound)
        channel._on_message(event)

        mock_make_inbound.assert_called_once()
        assert mock_make_inbound.call_args[1]["msg_type"] == expected_type


# ---------------------------------------------------------------------------
# _is_supported_command unit tests — all supported commands + edge cases
# ---------------------------------------------------------------------------


from app.channels.feishu import SUPPORTED_COMMANDS, FeishuChannel as _FC  # noqa: E402


@pytest.mark.parametrize("cmd", sorted(SUPPORTED_COMMANDS))
def test_is_supported_command_recognizes_all_supported_commands(cmd):
    assert _FC._is_supported_command(f"/{cmd}") is True


@pytest.mark.parametrize("cmd", sorted(SUPPORTED_COMMANDS))
def test_is_supported_command_case_insensitive(cmd):
    assert _FC._is_supported_command(f"/{cmd.upper()}") is True


@pytest.mark.parametrize("cmd", sorted(SUPPORTED_COMMANDS))
def test_is_supported_command_with_argument(cmd):
    assert _FC._is_supported_command(f"/{cmd} some argument") is True


@pytest.mark.parametrize(
    "text",
    [
        "/mnt/user-data/workspace/file.txt",
        "/unknown-cmd",
        "/run-script",
        "no-slash",
        "",
        "/",  # slash only → empty command
    ],
)
def test_is_supported_command_rejects_non_commands(text):
    assert _FC._is_supported_command(text) is False
