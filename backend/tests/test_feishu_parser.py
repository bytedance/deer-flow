import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.channels.commands import KNOWN_CHANNEL_COMMANDS
from app.channels.feishu import FeishuChannel
from app.channels.message_bus import (
    PENDING_CLARIFICATION_METADATA_KEY,
    RESOLVED_FROM_PENDING_CLARIFICATION_METADATA_KEY,
    InboundMessage,
    MessageBus,
    OutboundMessage,
)
from app.channels.store import ChannelStore


def _pending(
    topic_id: str,
    *,
    thread_id: str | None = None,
    source_message_id: str | None = None,
    card_message_id: str | None = None,
    created_at: float = 9999999999,
) -> dict:
    return {
        "thread_id": thread_id or f"deer-thread-{topic_id}",
        "topic_id": topic_id,
        "source_message_id": source_message_id or topic_id,
        "card_message_id": card_message_id or f"card-{topic_id}",
        "created_at": created_at,
    }


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


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


def test_feishu_is_not_running_when_ws_thread_exits():
    bus = MessageBus()
    channel = FeishuChannel(bus, {"app_id": "test", "app_secret": "test"})
    channel._running = True
    channel._thread = MagicMock()
    channel._thread.is_alive.return_value = False

    assert channel.is_running is False


def test_feishu_event_handler_ignores_non_content_message_events():
    import lark_oapi as lark

    bus = MessageBus()
    channel = FeishuChannel(bus, {"app_id": "test", "app_secret": "test"})

    event_handler = channel._build_event_handler(lark)

    assert "p2.im.message.receive_v1" in event_handler._processorMap
    assert "p2.im.message.message_read_v1" in event_handler._processorMap
    assert "p2.im.message.reaction.created_v1" in event_handler._processorMap
    assert "p2.im.message.reaction.deleted_v1" in event_handler._processorMap
    assert "p2.im.message.recalled_v1" in event_handler._processorMap


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


def test_feishu_receive_file_replaces_placeholders_in_order():
    async def go():
        bus = MessageBus()
        channel = FeishuChannel(bus, {"app_id": "test", "app_secret": "test"})

        msg = InboundMessage(
            channel_name="feishu",
            chat_id="chat_1",
            user_id="user_1",
            text="before [image] middle [file] after",
            thread_ts="msg_1",
            files=[{"image_key": "img_key"}, {"file_key": "file_key"}],
        )

        channel._receive_single_file = AsyncMock(side_effect=["/mnt/user-data/uploads/a.png", "/mnt/user-data/uploads/b.pdf"])

        result = await channel.receive_file(msg, "thread_1")

        assert result.text == "before /mnt/user-data/uploads/a.png middle /mnt/user-data/uploads/b.pdf after"

    _run(go())


def test_feishu_on_message_extracts_image_and_file_keys():
    bus = MessageBus()
    channel = FeishuChannel(bus, {"app_id": "test", "app_secret": "test"})

    event = MagicMock()
    event.event.message.chat_id = "chat_1"
    event.event.message.message_id = "msg_1"
    event.event.message.root_id = None
    event.event.sender.sender_id.open_id = "user_1"

    # Rich text with one image and one file element.
    event.event.message.content = json.dumps(
        {
            "content": [
                [
                    {"tag": "text", "text": "See"},
                    {"tag": "img", "image_key": "img_123"},
                    {"tag": "file", "file_key": "file_456"},
                ]
            ]
        }
    )

    with pytest.MonkeyPatch.context() as m:
        mock_make_inbound = MagicMock()
        m.setattr(channel, "_make_inbound", mock_make_inbound)
        channel._on_message(event)

        mock_make_inbound.assert_called_once()
        files = mock_make_inbound.call_args[1]["files"]
        assert files == [{"image_key": "img_123"}, {"file_key": "file_456"}]
        assert "[image]" in mock_make_inbound.call_args[1]["text"]
        assert "[file]" in mock_make_inbound.call_args[1]["text"]


def test_feishu_on_message_reuses_stored_parent_topic_for_card_replies():
    bus = MessageBus()
    store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
    store.set_thread_id(
        "feishu",
        "chat_1",
        "deer-thread-1",
        topic_id="om_clarification_card",
        user_id="user_1",
    )
    channel = FeishuChannel(
        bus,
        {"app_id": "test", "app_secret": "test", "channel_store": store},
    )

    event = MagicMock()
    event.event.message.chat_id = "chat_1"
    event.event.message.message_id = "msg_reply"
    event.event.message.root_id = "om_unknown_root"
    event.event.message.parent_id = "om_clarification_card"
    event.event.message.thread_id = None
    event.event.sender.sender_id.open_id = "user_1"
    event.event.message.content = json.dumps({"text": "prod"})

    with pytest.MonkeyPatch.context() as m:
        mock_make_inbound = MagicMock()
        m.setattr(channel, "_make_inbound", mock_make_inbound)
        channel._on_message(event)

        inbound = mock_make_inbound.return_value
        assert inbound.topic_id == "om_clarification_card"
        assert mock_make_inbound.call_args.kwargs["metadata"]["topic_id"] == "om_clarification_card"


def _make_text_event(
    text: str,
    *,
    chat_id: str = "chat_1",
    message_id: str = "msg_1",
    user_id: str = "user_1",
    root_id: str | None = None,
    parent_id: str | None = None,
    thread_id: str | None = None,
):
    event = MagicMock()
    event.event.message.chat_id = chat_id
    event.event.message.message_id = message_id
    event.event.message.root_id = root_id
    event.event.message.parent_id = parent_id
    event.event.message.thread_id = thread_id
    event.event.sender.sender_id.open_id = user_id
    event.event.message.content = json.dumps({"text": text})
    return event


def test_feishu_plain_reply_consumes_pending_clarification_topic():
    bus = MessageBus()
    store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
    store.set_thread_id("feishu", "chat_1", "deer-thread-1", topic_id="om_original", user_id="user_1")
    channel = FeishuChannel(bus, {"app_id": "test", "app_secret": "test", "channel_store": store})
    channel._pending_clarifications[channel._pending_key("chat_1", "user_1")] = [_pending("om_original", thread_id="deer-thread-1", card_message_id="om_card")]

    with pytest.MonkeyPatch.context() as m:
        mock_make_inbound = MagicMock()
        m.setattr(channel, "_make_inbound", mock_make_inbound)
        channel._on_message(_make_text_event("2", message_id="msg_plain_2"))

        inbound = mock_make_inbound.return_value
        metadata = mock_make_inbound.call_args.kwargs["metadata"]
        assert inbound.topic_id == "om_original"
        assert metadata["topic_id"] == "om_original"
        assert metadata[RESOLVED_FROM_PENDING_CLARIFICATION_METADATA_KEY] is True
        assert channel._pending_key("chat_1", "user_1") not in channel._pending_clarifications


def test_feishu_pending_clarification_is_consumed_once():
    bus = MessageBus()
    channel = FeishuChannel(bus, {"app_id": "test", "app_secret": "test"})
    channel._pending_clarifications[channel._pending_key("chat_1", "user_1")] = [_pending("om_original", thread_id="deer-thread-1", card_message_id="om_card")]

    with pytest.MonkeyPatch.context() as m:
        created = []

        def fake_make_inbound(**kwargs):
            inbound = InboundMessage(channel_name="feishu", **kwargs)
            created.append(inbound)
            return inbound

        mock_make_inbound = MagicMock(side_effect=fake_make_inbound)
        m.setattr(channel, "_make_inbound", mock_make_inbound)
        channel._on_message(_make_text_event("2", message_id="msg_first"))
        channel._on_message(_make_text_event("next", message_id="msg_second"))

        first_inbound = created[0]
        second_inbound = created[1]
        first_metadata = mock_make_inbound.call_args_list[0].kwargs["metadata"]
        second_metadata = mock_make_inbound.call_args_list[1].kwargs["metadata"]
        assert first_inbound.topic_id == "om_original"
        assert second_inbound.topic_id == "msg_second"
        assert first_metadata["topic_id"] == "om_original"
        assert first_metadata[RESOLVED_FROM_PENDING_CLARIFICATION_METADATA_KEY] is True
        assert second_metadata["topic_id"] == "msg_second"
        assert second_metadata[RESOLVED_FROM_PENDING_CLARIFICATION_METADATA_KEY] is False


def test_feishu_expired_pending_clarification_is_ignored(monkeypatch):
    bus = MessageBus()
    channel = FeishuChannel(bus, {"app_id": "test", "app_secret": "test"})
    monkeypatch.setattr("app.channels.feishu.time.time", lambda: 10_000.0)
    channel._pending_clarifications[channel._pending_key("chat_1", "user_1")] = [_pending("om_original", thread_id="deer-thread-1", card_message_id="om_card", created_at=0.0)]

    with pytest.MonkeyPatch.context() as m:
        mock_make_inbound = MagicMock()
        m.setattr(channel, "_make_inbound", mock_make_inbound)
        channel._on_message(_make_text_event("2", message_id="msg_plain_2"))

        metadata = mock_make_inbound.call_args.kwargs["metadata"]
        assert metadata["topic_id"] == "msg_plain_2"
        assert metadata[RESOLVED_FROM_PENDING_CLARIFICATION_METADATA_KEY] is False
        assert channel._pending_key("chat_1", "user_1") not in channel._pending_clarifications


def test_feishu_command_does_not_consume_pending_clarification():
    bus = MessageBus()
    channel = FeishuChannel(bus, {"app_id": "test", "app_secret": "test"})
    key = channel._pending_key("chat_1", "user_1")
    channel._pending_clarifications[key] = [_pending("om_original", thread_id="deer-thread-1", card_message_id="om_card")]

    with pytest.MonkeyPatch.context() as m:
        mock_make_inbound = MagicMock()
        m.setattr(channel, "_make_inbound", mock_make_inbound)
        channel._on_message(_make_text_event("/status", message_id="msg_command"))

        metadata = mock_make_inbound.call_args.kwargs["metadata"]
        assert mock_make_inbound.call_args.kwargs["msg_type"].value == "command"
        assert metadata["topic_id"] == "msg_command"
        assert metadata[RESOLVED_FROM_PENDING_CLARIFICATION_METADATA_KEY] is False
        assert key in channel._pending_clarifications


def test_feishu_remembers_pending_clarification_only_after_final_card_success():
    bus = MessageBus()
    channel = FeishuChannel(bus, {"app_id": "test", "app_secret": "test"})
    outbound = OutboundMessage(
        channel_name="feishu",
        chat_id="chat_1",
        thread_id="deer-thread-1",
        text="clarify?",
        thread_ts="om_original",
        metadata={
            PENDING_CLARIFICATION_METADATA_KEY: True,
            "user_id": "user_1",
            "topic_id": "om_original",
            "message_id": "om_original",
        },
    )

    channel._remember_pending_clarification(outbound, None)
    assert channel._pending_clarifications == {}

    channel._remember_pending_clarification(outbound, "om_card")
    pending = channel._pending_clarifications[channel._pending_key("chat_1", "user_1")][0]
    assert pending["topic_id"] == "om_original"
    assert pending["thread_id"] == "deer-thread-1"
    assert pending["card_message_id"] == "om_card"


def test_feishu_multiple_pending_clarifications_are_consumed_in_order():
    bus = MessageBus()
    channel = FeishuChannel(bus, {"app_id": "test", "app_secret": "test"})
    key = channel._pending_key("chat_1", "user_1")
    channel._pending_clarifications[key] = [
        _pending("om_first", thread_id="deer-thread-1"),
        _pending("om_second", thread_id="deer-thread-2"),
    ]

    with pytest.MonkeyPatch.context() as m:
        created = []

        def fake_make_inbound(**kwargs):
            inbound = InboundMessage(channel_name="feishu", **kwargs)
            created.append(inbound)
            return inbound

        m.setattr(channel, "_make_inbound", MagicMock(side_effect=fake_make_inbound))
        channel._on_message(_make_text_event("first answer", message_id="msg_first"))
        channel._on_message(_make_text_event("second answer", message_id="msg_second"))

        assert [msg.topic_id for msg in created] == ["om_first", "om_second"]
        assert key not in channel._pending_clarifications


def test_feishu_explicit_reply_prefers_stored_mapping_over_pending():
    bus = MessageBus()
    store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
    store.set_thread_id("feishu", "chat_1", "deer-thread-card", topic_id="om_card", user_id="user_1")
    channel = FeishuChannel(bus, {"app_id": "test", "app_secret": "test", "channel_store": store})
    key = channel._pending_key("chat_1", "user_1")
    channel._pending_clarifications[key] = [_pending("om_pending", thread_id="deer-thread-pending")]

    with pytest.MonkeyPatch.context() as m:
        mock_make_inbound = MagicMock()
        m.setattr(channel, "_make_inbound", mock_make_inbound)
        channel._on_message(
            _make_text_event(
                "answer",
                message_id="msg_reply",
                root_id="om_unknown",
                parent_id="om_card",
            )
        )

        metadata = mock_make_inbound.call_args.kwargs["metadata"]
        assert metadata["topic_id"] == "om_card"
        assert metadata[RESOLVED_FROM_PENDING_CLARIFICATION_METADATA_KEY] is False
        assert key in channel._pending_clarifications


@pytest.mark.parametrize("command", sorted(KNOWN_CHANNEL_COMMANDS))
def test_feishu_recognizes_all_known_slash_commands(command):
    """Every entry in KNOWN_CHANNEL_COMMANDS must be classified as a command."""
    bus = MessageBus()
    config = {"app_id": "test", "app_secret": "test"}
    channel = FeishuChannel(bus, config)

    event = MagicMock()
    event.event.message.chat_id = "chat_1"
    event.event.message.message_id = "msg_1"
    event.event.message.root_id = None
    event.event.sender.sender_id.open_id = "user_1"
    event.event.message.content = json.dumps({"text": command})

    with pytest.MonkeyPatch.context() as m:
        mock_make_inbound = MagicMock()
        m.setattr(channel, "_make_inbound", mock_make_inbound)
        channel._on_message(event)

        mock_make_inbound.assert_called_once()
        assert mock_make_inbound.call_args[1]["msg_type"].value == "command", f"{command!r} should be classified as COMMAND"


@pytest.mark.parametrize(
    "text",
    [
        "/unknown",
        "/mnt/user-data/outputs/prd/technical-design.md",
        "/etc/passwd",
        "/not-a-command at all",
    ],
)
def test_feishu_treats_unknown_slash_text_as_chat(text):
    """Slash-prefixed text that is not a known command must be classified as CHAT."""
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
        assert mock_make_inbound.call_args[1]["msg_type"].value == "chat", f"{text!r} should be classified as CHAT"
