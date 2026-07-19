"""Tests for the IM channel system (MessageBus, ChannelStore, ChannelManager)."""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.channels.base import Channel
from app.channels.message_bus import (
    PENDING_CLARIFICATION_METADATA_KEY,
    InboundMessage,
    InboundMessageType,
    MessageBus,
    OutboundMessage,
    ResolvedAttachment,
)
from app.channels.store import ChannelStore
from deerflow.skills.types import Skill, SkillCategory
from deerflow.utils.messages import ORIGINAL_USER_CONTENT_KEY


def test_known_channel_command_detection_only_matches_control_commands():
    from app.channels.commands import is_known_channel_command

    assert is_known_channel_command("/new")
    assert is_known_channel_command("/HELP now")
    assert not is_known_channel_command("/mnt/user-data/uploads/report.pdf")
    assert not is_known_channel_command("/data-analysis analyze uploads/foo.csv")
    assert not is_known_channel_command(" /new")


def test_strip_leading_mentions_only_drops_flush_leading_mentions():
    from app.channels.commands import is_known_channel_command, strip_leading_mentions

    assert strip_leading_mentions("@bot /goal") == "/goal"
    assert strip_leading_mentions("@_user_1 /goal ship") == "/goal ship"
    assert strip_leading_mentions("<@U1> /status") == "/status"
    assert strip_leading_mentions("@bot @_user_2 /help") == "/help"
    assert strip_leading_mentions("@bot") == ""
    assert strip_leading_mentions("") == ""
    # No leading mention -> unchanged, including the leading-space non-command case.
    assert strip_leading_mentions("/goal") == "/goal"
    assert strip_leading_mentions(" /new") == " /new"
    assert strip_leading_mentions("hello /goal") == "hello /goal"
    # The shared classifier is deliberately NOT changed to strip mentions: Slack
    # relies on it keeping a leading non-bot mention as chat (see Slack tests), so
    # mention handling lives in the adapters, not here.
    assert not is_known_channel_command("@bot /goal")


def _make_channel_skill(tmp_path: Path, name: str, *, enabled: bool = True) -> Skill:
    skill_dir = tmp_path / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(f"# {name}\n", encoding="utf-8")
    return Skill(
        name=name,
        description=f"Description for {name}",
        license="MIT",
        skill_dir=skill_dir,
        skill_file=skill_file,
        relative_path=Path(name),
        category=SkillCategory.CUSTOM,
        enabled=enabled,
    )


def _make_channel_skill_storage(skills: list[Skill]):
    return SimpleNamespace(
        load_skills=lambda *, enabled_only: [skill for skill in skills if skill.enabled] if enabled_only else skills,
        get_container_root=lambda: "/mnt/skills",
    )


def _run(coro):
    """Run an async coroutine synchronously."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _wait_for(condition, *, timeout=5.0, interval=0.05):
    """Poll *condition* until it returns True, or raise after *timeout* seconds."""
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        await asyncio.sleep(interval)
    raise TimeoutError(f"Condition not met within {timeout}s")


# ---------------------------------------------------------------------------
# MessageBus tests
# ---------------------------------------------------------------------------


class TestMessageBus:
    def test_publish_and_get_inbound(self):
        bus = MessageBus()

        async def go():
            msg = InboundMessage(
                channel_name="test",
                chat_id="chat1",
                user_id="user1",
                text="hello",
            )
            await bus.publish_inbound(msg)
            result = await bus.get_inbound()
            assert result.text == "hello"
            assert result.channel_name == "test"
            assert result.chat_id == "chat1"

        _run(go())

    def test_inbound_queue_is_fifo(self):
        bus = MessageBus()

        async def go():
            for i in range(3):
                await bus.publish_inbound(InboundMessage(channel_name="test", chat_id="c", user_id="u", text=f"msg{i}"))
            for i in range(3):
                msg = await bus.get_inbound()
                assert msg.text == f"msg{i}"

        _run(go())

    def test_outbound_callback(self):
        bus = MessageBus()
        received = []

        async def callback(msg):
            received.append(msg)

        async def go():
            bus.subscribe_outbound(callback)
            out = OutboundMessage(channel_name="test", chat_id="c1", thread_id="t1", text="reply")
            await bus.publish_outbound(out)
            assert len(received) == 1
            assert received[0].text == "reply"

        _run(go())

    def test_unsubscribe_outbound(self):
        bus = MessageBus()
        received = []

        async def callback(msg):
            received.append(msg)

        async def go():
            bus.subscribe_outbound(callback)
            bus.unsubscribe_outbound(callback)
            out = OutboundMessage(channel_name="test", chat_id="c1", thread_id="t1", text="reply")
            await bus.publish_outbound(out)
            assert len(received) == 0

        _run(go())

    def test_unsubscribe_outbound_removes_fresh_bound_method_reference(self):
        bus = MessageBus()
        received = []

        class Handler:
            async def callback(self, msg):
                received.append((self, msg))

        handler = Handler()
        other_handler = Handler()

        async def go():
            bus.subscribe_outbound(handler.callback)
            bus.subscribe_outbound(other_handler.callback)
            bus.unsubscribe_outbound(handler.callback)
            out = OutboundMessage(channel_name="test", chat_id="c1", thread_id="t1", text="reply")
            await bus.publish_outbound(out)
            assert received == [(other_handler, out)]

        _run(go())

    def test_outbound_error_does_not_crash(self):
        bus = MessageBus()

        async def bad_callback(msg):
            raise ValueError("boom")

        received = []

        async def good_callback(msg):
            received.append(msg)

        async def go():
            bus.subscribe_outbound(bad_callback)
            bus.subscribe_outbound(good_callback)
            out = OutboundMessage(channel_name="test", chat_id="c1", thread_id="t1", text="reply")
            await bus.publish_outbound(out)
            assert len(received) == 1

        _run(go())

    def test_inbound_message_defaults(self):
        msg = InboundMessage(channel_name="test", chat_id="c", user_id="u", text="hi")
        assert msg.msg_type == InboundMessageType.CHAT
        assert msg.thread_ts is None
        assert msg.files == []
        assert msg.metadata == {}
        assert msg.created_at > 0

    def test_outbound_message_defaults(self):
        msg = OutboundMessage(channel_name="test", chat_id="c", thread_id="t", text="hi")
        assert msg.artifacts == []
        assert msg.is_final is True
        assert msg.thread_ts is None
        assert msg.metadata == {}


# ---------------------------------------------------------------------------
# ChannelStore tests
# ---------------------------------------------------------------------------


class TestChannelStore:
    @pytest.fixture
    def store(self, tmp_path):
        return ChannelStore(path=tmp_path / "store.json")

    def test_set_and_get_thread_id(self, store):
        store.set_thread_id("slack", "ch1", "thread-abc", user_id="u1")
        assert store.get_thread_id("slack", "ch1") == "thread-abc"

    def test_get_nonexistent_returns_none(self, store):
        assert store.get_thread_id("slack", "nonexistent") is None

    def test_remove(self, store):
        store.set_thread_id("slack", "ch1", "t1")
        assert store.remove("slack", "ch1") is True
        assert store.get_thread_id("slack", "ch1") is None

    def test_remove_nonexistent_returns_false(self, store):
        assert store.remove("slack", "nope") is False

    def test_list_entries_all(self, store):
        store.set_thread_id("slack", "ch1", "t1")
        store.set_thread_id("feishu", "ch2", "t2")
        entries = store.list_entries()
        assert len(entries) == 2

    def test_list_entries_filtered(self, store):
        store.set_thread_id("slack", "ch1", "t1")
        store.set_thread_id("feishu", "ch2", "t2")
        entries = store.list_entries(channel_name="slack")
        assert len(entries) == 1
        assert entries[0]["channel_name"] == "slack"

    def test_persistence(self, tmp_path):
        path = tmp_path / "store.json"
        store1 = ChannelStore(path=path)
        store1.set_thread_id("slack", "ch1", "t1")

        store2 = ChannelStore(path=path)
        assert store2.get_thread_id("slack", "ch1") == "t1"

    def test_update_preserves_created_at(self, store):
        store.set_thread_id("slack", "ch1", "t1")
        entries = store.list_entries()
        created_at = entries[0]["created_at"]

        store.set_thread_id("slack", "ch1", "t2")
        entries = store.list_entries()
        assert entries[0]["created_at"] == created_at
        assert entries[0]["thread_id"] == "t2"
        assert entries[0]["updated_at"] >= created_at

    def test_corrupt_file_handled(self, tmp_path):
        path = tmp_path / "store.json"
        path.write_text("not json", encoding="utf-8")
        store = ChannelStore(path=path)
        assert store.get_thread_id("x", "y") is None


# ---------------------------------------------------------------------------
# Channel base class tests
# ---------------------------------------------------------------------------


class DummyChannel(Channel):
    """Concrete test implementation of Channel."""

    def __init__(self, bus, config=None):
        super().__init__(name="dummy", bus=bus, config=config or {})
        self.sent_messages: list[OutboundMessage] = []
        self._running = False

    async def start(self):
        self._running = True
        self.bus.subscribe_outbound(self._on_outbound)

    async def stop(self):
        self._running = False
        self.bus.unsubscribe_outbound(self._on_outbound)

    async def send(self, msg: OutboundMessage):
        self.sent_messages.append(msg)


class TestChannelBase:
    def test_make_inbound(self):
        bus = MessageBus()
        ch = DummyChannel(bus)
        msg = ch._make_inbound(
            chat_id="c1",
            user_id="u1",
            text="hello",
            msg_type=InboundMessageType.COMMAND,
        )
        assert msg.channel_name == "dummy"
        assert msg.chat_id == "c1"
        assert msg.text == "hello"
        assert msg.msg_type == InboundMessageType.COMMAND

    def test_on_outbound_routes_to_channel(self):
        bus = MessageBus()
        ch = DummyChannel(bus)

        async def go():
            await ch.start()
            msg = OutboundMessage(channel_name="dummy", chat_id="c1", thread_id="t1", text="hi")
            await bus.publish_outbound(msg)
            assert len(ch.sent_messages) == 1

        _run(go())

    def test_on_outbound_ignores_other_channels(self):
        bus = MessageBus()
        ch = DummyChannel(bus)

        async def go():
            await ch.start()
            msg = OutboundMessage(channel_name="other", chat_id="c1", thread_id="t1", text="hi")
            await bus.publish_outbound(msg)
            assert len(ch.sent_messages) == 0

        _run(go())

    def test_send_with_retry_retries_until_success(self, monkeypatch):
        bus = MessageBus()
        ch = DummyChannel(bus)
        attempts = 0
        sleep = AsyncMock()
        monkeypatch.setattr("app.channels.base.asyncio.sleep", sleep)

        async def flaky_send():
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise RuntimeError(f"failure {attempts}")
            return "sent"

        result = _run(ch._send_with_retry(flaky_send, max_retries=3, log_prefix="[Dummy]"))

        assert result == "sent"
        assert attempts == 3
        assert [call.args[0] for call in sleep.await_args_list] == [1, 2]

    def test_log_future_error_handles_cancelled_future(self, caplog):
        bus = MessageBus()
        ch = DummyChannel(bus)
        fut = Future()
        fut.cancel()

        with caplog.at_level(logging.ERROR):
            ch._log_future_error(fut, "prepare_inbound", "m1")

        assert "prepare_inbound" not in caplog.text

    def test_log_future_error_surfaces_future_exception(self, caplog):
        bus = MessageBus()
        ch = DummyChannel(bus)
        fut = Future()
        fut.set_exception(RuntimeError("boom"))

        with caplog.at_level(logging.ERROR):
            ch._log_future_error(fut, "prepare_inbound", "m1")

        assert "prepare_inbound failed for msg_id=m1: boom" in caplog.text

    def test_channel_capabilities_match_channel_defaults(self):
        from app.channels.dingtalk import DingTalkChannel
        from app.channels.discord import DiscordChannel
        from app.channels.feishu import FeishuChannel
        from app.channels.github import GitHubChannel
        from app.channels.manager import CHANNEL_CAPABILITIES
        from app.channels.slack import SlackChannel
        from app.channels.telegram import TelegramChannel
        from app.channels.wechat import WechatChannel
        from app.channels.wecom import WeComChannel

        bus = MessageBus()
        defaults = {
            "dingtalk": DingTalkChannel(bus=bus, config={}).supports_streaming,
            "discord": DiscordChannel(bus=bus, config={}).supports_streaming,
            "feishu": FeishuChannel(bus=bus, config={}).supports_streaming,
            "github": GitHubChannel(bus=bus, config={}).supports_streaming,
            "slack": SlackChannel(bus=bus, config={}).supports_streaming,
            "telegram": TelegramChannel(bus=bus, config={}).supports_streaming,
            "wechat": WechatChannel(bus=bus, config={}).supports_streaming,
            "wecom": WeComChannel(bus=bus, config={}).supports_streaming,
        }

        assert {name: caps["supports_streaming"] for name, caps in CHANNEL_CAPABILITIES.items()} == defaults


# ---------------------------------------------------------------------------
# _extract_response_text tests
# ---------------------------------------------------------------------------


class TestExtractResponseText:
    def test_string_content(self):
        from app.channels.manager import _extract_response_text

        result = {"messages": [{"type": "ai", "content": "hello"}]}
        assert _extract_response_text(result) == "hello"

    def test_list_content_blocks(self):
        from app.channels.manager import _extract_response_text

        result = {"messages": [{"type": "ai", "content": [{"type": "text", "text": "hello"}, {"type": "text", "text": " world"}]}]}
        assert _extract_response_text(result) == "hello world"

    def test_picks_last_ai_message(self):
        from app.channels.manager import _extract_response_text

        result = {
            "messages": [
                {"type": "ai", "content": "first"},
                {"type": "human", "content": "question"},
                {"type": "ai", "content": "second"},
            ]
        }
        assert _extract_response_text(result) == "second"

    def test_empty_messages(self):
        from app.channels.manager import _extract_response_text

        assert _extract_response_text({"messages": []}) == ""

    def test_no_ai_messages(self):
        from app.channels.manager import _extract_response_text

        result = {"messages": [{"type": "human", "content": "hi"}]}
        assert _extract_response_text(result) == ""

    def test_list_result(self):
        from app.channels.manager import _extract_response_text

        result = [{"type": "ai", "content": "from list"}]
        assert _extract_response_text(result) == "from list"

    def test_skips_empty_ai_content(self):
        from app.channels.manager import _extract_response_text

        result = {
            "messages": [
                {"type": "ai", "content": ""},
                {"type": "ai", "content": "actual response"},
            ]
        }
        assert _extract_response_text(result) == "actual response"

    def test_clarification_tool_message(self):
        from app.channels.manager import _extract_response_text

        result = {
            "messages": [
                {"type": "human", "content": "健身"},
                {"type": "ai", "content": "", "tool_calls": [{"name": "ask_clarification", "args": {"question": "您想了解哪方面？"}}]},
                {"type": "tool", "name": "ask_clarification", "content": "您想了解哪方面？"},
            ]
        }
        assert _extract_response_text(result) == "您想了解哪方面？"

    def test_clarification_over_empty_ai(self):
        """When AI content is empty but ask_clarification tool message exists, use the tool message."""
        from app.channels.manager import _extract_response_text

        result = {
            "messages": [
                {"type": "ai", "content": ""},
                {"type": "tool", "name": "ask_clarification", "content": "Could you clarify?"},
            ]
        }
        assert _extract_response_text(result) == "Could you clarify?"

    def test_does_not_leak_previous_turn_text(self):
        """When current turn AI has no text (only tool calls), do not return previous turn's text."""
        from app.channels.manager import _extract_response_text

        result = {
            "messages": [
                {"type": "human", "content": "hello"},
                {"type": "ai", "content": "Hi there!"},
                {"type": "human", "content": "export data"},
                {
                    "type": "ai",
                    "content": "",
                    "tool_calls": [{"name": "present_files", "args": {"filepaths": ["/mnt/user-data/outputs/data.csv"]}}],
                },
                {"type": "tool", "name": "present_files", "content": "ok"},
            ]
        }
        # Should return "" (no text in current turn), NOT "Hi there!" from previous turn
        assert _extract_response_text(result) == ""

    def test_ignores_hidden_human_control_messages(self):
        """Hidden control messages should not terminate current-turn response extraction."""
        from app.channels.manager import _extract_response_text

        result = {
            "messages": [
                {"type": "human", "content": "plan this"},
                {"type": "ai", "content": "Here is the plan."},
                {
                    "type": "human",
                    "name": "todo_reminder",
                    "content": "keep todos updated",
                    "additional_kwargs": {"hide_from_ui": True},
                },
            ]
        }

        assert _extract_response_text(result) == "Here is the plan."


class TestClarificationDetection:
    def test_final_clarification_tool_message_is_pending(self):
        from app.channels.manager import _has_current_turn_clarification

        result = {
            "messages": [
                {"type": "human", "content": "deploy"},
                {"type": "ai", "content": "", "tool_calls": [{"name": "ask_clarification", "args": {}}]},
                {"type": "tool", "name": "ask_clarification", "content": "Which environment?"},
            ]
        }
        assert _has_current_turn_clarification(result) is True

    def test_clarification_followed_by_regular_ai_is_not_pending(self):
        from app.channels.manager import _has_current_turn_clarification

        result = {
            "messages": [
                {"type": "human", "content": "deploy"},
                {"type": "ai", "content": "", "tool_calls": [{"name": "ask_clarification", "args": {}}]},
                {"type": "tool", "name": "ask_clarification", "content": "Which environment?"},
                {"type": "ai", "content": "I will continue without pending clarification."},
            ]
        }
        assert _has_current_turn_clarification(result) is False

    def test_previous_turn_clarification_does_not_mark_current_turn(self):
        from app.channels.manager import _has_current_turn_clarification

        result = {
            "messages": [
                {"type": "human", "content": "deploy"},
                {"type": "ai", "content": "", "tool_calls": [{"name": "ask_clarification", "args": {}}]},
                {"type": "tool", "name": "ask_clarification", "content": "Which environment?"},
                {"type": "human", "content": "prod"},
                {"type": "ai", "content": "Deploying to prod."},
            ]
        }
        assert _has_current_turn_clarification(result) is False


# ---------------------------------------------------------------------------
# ChannelManager tests
# ---------------------------------------------------------------------------


def _make_mock_langgraph_client(thread_id="test-thread-123", run_result=None):
    """Create a mock langgraph_sdk async client."""
    mock_client = MagicMock()

    # threads.create() returns a Thread-like dict
    mock_client.threads.create = AsyncMock(return_value={"thread_id": thread_id})
    mock_client.threads.update = AsyncMock(return_value={"thread_id": thread_id})

    # threads.get() returns thread info (succeeds by default)
    mock_client.threads.get = AsyncMock(return_value={"thread_id": thread_id})

    # runs.wait() returns the final state with messages
    if run_result is None:
        run_result = {
            "messages": [
                {"type": "human", "content": "hi"},
                {"type": "ai", "content": "Hello from agent!"},
            ]
        }
    mock_client.runs.wait = AsyncMock(return_value=run_result)

    return mock_client


async def _make_channel_connection_repo(tmp_path: Path):
    from deerflow.persistence.channel_connections import ChannelConnectionRepository, ChannelCredentialCipher
    from deerflow.persistence.engine import get_session_factory, init_engine

    await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'channel-connections.db'}", sqlite_dir=str(tmp_path))
    return ChannelConnectionRepository(
        get_session_factory(),
        cipher=ChannelCredentialCipher.from_key("test-channel-key"),
    )


def _make_stream_part(event: str, data):
    return SimpleNamespace(event=event, data=data)


def _ok_stream_events():
    """Minimal successful streaming run: one text chunk plus a final values frame."""
    return [
        _make_stream_part(
            "messages-tuple",
            [{"id": "ai-1", "content": "Hello", "type": "AIMessageChunk"}, {"langgraph_node": "agent"}],
        ),
        _make_stream_part(
            "values",
            {"messages": [{"type": "human", "content": "hi"}, {"type": "ai", "content": "Hello"}], "artifacts": []},
        ),
    ]


def _make_async_iterator(items):
    async def iterator():
        for item in items:
            yield item

    return iterator()


class TestChannelManager:
    def test_get_client_includes_csrf_header_and_cookie(self):
        from app.channels.manager import ChannelManager

        bus = MessageBus()
        store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
        manager = ChannelManager(bus=bus, store=store, langgraph_url="http://localhost:8001")

        with patch("langgraph_sdk.get_client") as get_client:
            get_client.return_value = object()

            manager._get_client()

        get_client.assert_called_once()
        kwargs = get_client.call_args.kwargs
        assert kwargs["url"] == "http://localhost:8001"
        headers = kwargs["headers"]
        csrf_token = headers["X-CSRF-Token"]
        assert csrf_token
        assert headers["Cookie"] == f"csrf_token={csrf_token}"
        assert headers["X-DeerFlow-Internal-Token"]

    def test_concurrent_inbound_for_same_chat_reuses_single_thread(self):
        # Each inbound message is dispatched on its own task, so two messages
        # arriving close together for the same chat can both look up a missing
        # thread before either stores one. Without per-conversation locking they
        # each create a thread and the second store overwrites the first,
        # orphaning a Gateway thread and splitting the conversation. The create
        # path must be serialized so only one thread is created and reused.
        from app.channels.manager import ChannelManager

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(bus=bus, store=store)

            created_ids: list[str] = []
            first_create_started = asyncio.Event()
            release_create = asyncio.Event()

            async def blocking_create(*, metadata=None, headers=None):
                thread_id = f"thread-{len(created_ids) + 1}"
                created_ids.append(thread_id)
                first_create_started.set()
                # Hold the create open so a second concurrent message has a
                # chance to race in before this one stores its thread_id.
                await release_create.wait()
                return {"thread_id": thread_id}

            mock_client = MagicMock()
            mock_client.threads.create = blocking_create
            manager._client = mock_client

            msg = InboundMessage(channel_name="slack", chat_id="C1", user_id="U1", text="hi")

            task1 = asyncio.create_task(manager._get_or_create_thread(mock_client, msg))
            await first_create_started.wait()
            # task2 should block on the per-conversation lock rather than enter
            # threads.create a second time.
            task2 = asyncio.create_task(manager._get_or_create_thread(mock_client, msg))
            await asyncio.sleep(0)
            release_create.set()

            (tid1, created1), (tid2, created2) = await asyncio.gather(task1, task2)

            assert len(created_ids) == 1
            assert tid1 == tid2 == "thread-1"
            assert created1 is True
            assert created2 is False
            assert store.get_thread_id("slack", "C1") == "thread-1"

        _run(go())

    def test_fetch_gateway_includes_internal_auth_headers(self, monkeypatch):
        from app.channels.manager import ChannelManager

        class MockResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"models": [{"name": "default"}]}

        class MockAsyncClient:
            def __init__(self, *args, **kwargs):
                return None

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return None

            async def get(self, url, **kwargs):
                calls.append({"url": url, **kwargs})
                return MockResponse()

        calls = []
        monkeypatch.setattr("app.channels.manager.httpx.AsyncClient", MockAsyncClient)

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(bus=bus, store=store, gateway_url="http://gateway:8001")

            reply = await manager._fetch_gateway("/api/models", "models")

            assert reply == "Available models:\n• default"
            assert calls[0]["url"] == "http://gateway:8001/api/models"
            assert calls[0]["timeout"] == 10
            assert calls[0]["headers"]["X-DeerFlow-Internal-Token"]

        _run(go())

    def test_fetch_gateway_uses_bound_owner_headers(self, monkeypatch):
        from app.channels.manager import ChannelManager
        from app.gateway.internal_auth import INTERNAL_OWNER_USER_ID_HEADER_NAME

        class MockResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"facts": [{"text": "owner fact"}]}

        class MockAsyncClient:
            def __init__(self, *args, **kwargs):
                return None

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return None

            async def get(self, url, **kwargs):
                calls.append({"url": url, **kwargs})
                return MockResponse()

        calls = []
        monkeypatch.setattr("app.channels.manager.httpx.AsyncClient", MockAsyncClient)

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(bus=bus, store=store, gateway_url="http://gateway:8001")
            msg = InboundMessage(
                channel_name="slack",
                chat_id="C123",
                user_id="U-platform",
                owner_user_id="deerflow-user-1",
                connection_id="connection-1",
                text="/memory",
                msg_type=InboundMessageType.COMMAND,
            )

            reply = await manager._fetch_gateway("/api/memory", "memory", msg=msg)

            assert reply == "Memory contains 1 fact(s)."
            assert calls[0]["headers"][INTERNAL_OWNER_USER_ID_HEADER_NAME] == "deerflow-user-1"

        _run(go())

    def test_handle_chat_calls_channel_receive_file_for_inbound_files(self, monkeypatch):
        from app.channels.manager import ChannelManager

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(bus=bus, store=store)

            outbound_received = []

            async def capture_outbound(msg):
                outbound_received.append(msg)

            bus.subscribe_outbound(capture_outbound)

            mock_client = _make_mock_langgraph_client()
            manager._client = mock_client

            modified_msg = InboundMessage(
                channel_name="test",
                chat_id="chat1",
                user_id="user1",
                text="with /mnt/user-data/uploads/demo.png",
                files=[{"image_key": "img_1"}],
            )
            mock_channel = MagicMock()
            mock_channel.receive_file = AsyncMock(return_value=modified_msg)
            mock_channel.supports_streaming = False
            mock_service = MagicMock()
            mock_service.get_channel.return_value = mock_channel
            monkeypatch.setattr("app.channels.service.get_channel_service", lambda: mock_service)

            await manager.start()

            inbound = InboundMessage(
                channel_name="test",
                chat_id="chat1",
                user_id="platform-user",
                owner_user_id="owner-1",
                connection_id="connection-1",
                text="hi [image]",
                files=[{"image_key": "img_1"}],
            )
            await bus.publish_inbound(inbound)
            await _wait_for(lambda: len(outbound_received) >= 1)
            await manager.stop()

            mock_channel.receive_file.assert_awaited_once()
            called_msg, called_thread_id = mock_channel.receive_file.await_args.args
            assert called_msg.text == "hi [image]"
            assert isinstance(called_thread_id, str)
            assert called_thread_id
            assert mock_channel.receive_file.await_args.kwargs["user_id"] == "owner-1"

            mock_client.runs.wait.assert_called_once()
            run_call_args = mock_client.runs.wait.call_args
            assert run_call_args[1]["input"]["messages"][0]["content"] == "with /mnt/user-data/uploads/demo.png"

        _run(go())

    def test_ingest_inbound_files_uses_explicit_owner_bucket(self, tmp_path, monkeypatch):
        from app.channels.manager import INBOUND_FILE_READERS, _ingest_inbound_files
        from deerflow.config.paths import Paths

        paths = Paths(tmp_path)
        monkeypatch.setattr("deerflow.uploads.manager.get_paths", lambda: paths)

        async def read_file(file_info, client):
            del file_info, client
            return b"owner data"

        INBOUND_FILE_READERS["owner-test"] = read_file

        async def go():
            try:
                created = await _ingest_inbound_files(
                    "thread-owner",
                    InboundMessage(
                        channel_name="owner-test",
                        chat_id="C123",
                        user_id="U-platform",
                        text="file",
                        files=[{"filename": "report.txt", "type": "file"}],
                    ),
                    user_id="owner-1",
                )
            finally:
                INBOUND_FILE_READERS.pop("owner-test", None)

            assert created == [
                {
                    "filename": "report.txt",
                    "size": len(b"owner data"),
                    "path": "/mnt/user-data/uploads/report.txt",
                    "is_image": False,
                }
            ]
            assert (paths.sandbox_uploads_dir("thread-owner", user_id="owner-1") / "report.txt").read_bytes() == b"owner data"
            assert not paths.sandbox_uploads_dir("thread-owner").exists()

        _run(go())

    def test_channel_storage_user_id_falls_back_to_platform_user(self, monkeypatch):
        """Unbound auth-enabled channels stage files under the same bucket the run uses.

        ``_resolve_run_params`` runs an unbound msg under ``safe(msg.user_id)``, so
        ``_channel_storage_user_id`` must resolve to the same value instead of
        ``None`` (which would fall back to ``"default"`` in the dispatcher task and
        cross buckets — the agent would read uploads the channel never wrote there).
        """
        from app.channels.manager import _channel_storage_user_id, _safe_user_id_for_run

        # Auth enabled (no auth-disabled owner), unbound (no owner_user_id).
        monkeypatch.setattr("app.channels.manager._auth_disabled_owner_user_id", lambda: None)

        unbound = InboundMessage(channel_name="slack", chat_id="C1", user_id="U-platform", text="hi")
        assert _channel_storage_user_id(unbound) == _safe_user_id_for_run("U-platform")

        bound = InboundMessage(channel_name="slack", chat_id="C1", user_id="U-platform", text="hi", owner_user_id="owner-1")
        assert _channel_storage_user_id(bound) == _safe_user_id_for_run("owner-1")

        anonymous = InboundMessage(channel_name="slack", chat_id="C1", user_id="", text="hi")
        assert _channel_storage_user_id(anonymous) is None

    def test_handle_chat_creates_thread(self):
        from app.channels.manager import ChannelManager

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(bus=bus, store=store)

            outbound_received = []

            async def capture_outbound(msg):
                outbound_received.append(msg)

            bus.subscribe_outbound(capture_outbound)

            mock_client = _make_mock_langgraph_client()
            manager._client = mock_client

            await manager.start()

            inbound = InboundMessage(
                channel_name="test",
                chat_id="chat1",
                user_id="user1",
                text="hi",
                topic_id="topic1",
                thread_ts="msg1",
                connection_id="conn1",
            )
            await bus.publish_inbound(inbound)
            await _wait_for(lambda: len(outbound_received) >= 1)
            await manager.stop()

            # Thread should be created through Gateway
            mock_client.threads.create.assert_called_once()
            assert mock_client.threads.create.call_args.kwargs["metadata"] == {
                "channel_source": {
                    "type": "im_channel",
                    "provider": "test",
                    "chat_id": "chat1",
                    "topic_id": "topic1",
                    "thread_ts": "msg1",
                    "connection_id": "conn1",
                }
            }

            # Thread ID should be stored
            thread_id = store.get_thread_id("test", "chat1", topic_id="topic1")
            assert thread_id == "test-thread-123"

            # runs.wait should be called with the thread_id
            mock_client.runs.wait.assert_called_once()
            call_args = mock_client.runs.wait.call_args
            assert call_args[0][0] == "test-thread-123"  # thread_id
            assert call_args[0][1] == "lead_agent"  # assistant_id
            assert call_args[1]["input"]["messages"][0]["content"] == "hi"
            assert call_args[1]["config"]["configurable"]["checkpoint_ns"] == ""
            assert call_args[1]["config"]["configurable"]["thread_id"] == "test-thread-123"

            assert len(outbound_received) == 1
            assert outbound_received[0].text == "Hello from agent!"

        _run(go())

    def test_dispatch_loop_dedupes_stable_provider_message_id(self, tmp_path):
        from app.channels.manager import ChannelManager

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=tmp_path / "store.json")
            manager = ChannelManager(bus=bus, store=store)
            manager._client = _make_mock_langgraph_client()
            outbound_received: list[OutboundMessage] = []

            async def capture_outbound(msg: OutboundMessage) -> None:
                outbound_received.append(msg)

            bus.subscribe_outbound(capture_outbound)
            await manager.start()

            def _slack_inbound(message_id: str) -> InboundMessage:
                # Distinct objects per publish, like a real provider redelivery.
                return InboundMessage(
                    channel_name="slack",
                    chat_id="C123",
                    user_id="U123",
                    text="sensitive prompt",
                    topic_id="1710000000.000100",
                    metadata={"team_id": "T123", "message_id": message_id},
                )

            # Same stable message_id delivered twice -> processed once.
            await bus.publish_inbound(_slack_inbound("1710000000.000200"))
            await bus.publish_inbound(_slack_inbound("1710000000.000200"))
            await _wait_for(lambda: manager._client.runs.wait.call_count == 1 and len(outbound_received) == 1)
            await asyncio.sleep(0.05)
            assert manager._client.threads.create.call_count == 1
            assert manager._client.runs.wait.call_count == 1
            assert len(outbound_received) == 1

            # Negative control: a *different* message_id must still be processed,
            # so an over-dedupe regression (dropping distinct messages) is caught.
            await bus.publish_inbound(_slack_inbound("1710000000.000999"))
            await _wait_for(lambda: manager._client.runs.wait.call_count == 2 and len(outbound_received) == 2)
            await asyncio.sleep(0.05)
            await manager.stop()

            assert manager._client.runs.wait.call_count == 2
            assert len(outbound_received) == 2

        _run(go())

    def test_inbound_dedupe_key_fails_closed_without_workspace(self):
        """Without a workspace identifier, skip dedupe instead of collapsing workspaces (willem #3)."""
        from app.channels.manager import ChannelManager

        with_workspace = InboundMessage(
            channel_name="slack",
            chat_id="C1",
            user_id="U1",
            text="x",
            metadata={"team_id": "T1", "message_id": "m1"},
        )
        assert ChannelManager._inbound_dedupe_key(with_workspace) == ("slack", "T1", "C1", "m1")

        without_workspace = InboundMessage(
            channel_name="slack",
            chat_id="C1",
            user_id="U1",
            text="x",
            metadata={"message_id": "m1"},
        )
        assert ChannelManager._inbound_dedupe_key(without_workspace) is None

    def test_inbound_dedupe_key_uses_chat_id_for_chat_scoped_providers_when_unbound(self):
        """Unbound telegram/feishu/wechat must still form a dedupe key via chat_id.

        Those adapters persist connection.workspace_id = chat_id, but
        attach_connection_identity only sets msg.workspace_id when a connection
        exists. Provider redeliveries on unbound (or not-yet-bound) chats would
        otherwise skip the entire inbound dedupe path and run the agent N times.
        """
        from app.channels.manager import ChannelManager

        for channel, chat_id, message_id in (
            ("telegram", "12345", "42"),
            ("feishu", "oc_abc", "om_1"),
            ("wechat", "wx_user_1", "m1"),
        ):
            unbound = InboundMessage(
                channel_name=channel,
                chat_id=chat_id,
                user_id="u1",
                text="hi",
                metadata={"message_id": message_id},
            )
            assert ChannelManager._inbound_dedupe_key(unbound) == (channel, chat_id, chat_id, message_id)

            # Bound shape (workspace already on the message) must keep the same key
            # so bound and unbound redeliveries of the same chat share the cache.
            bound = InboundMessage(
                channel_name=channel,
                chat_id=chat_id,
                user_id="u1",
                text="hi",
                workspace_id=chat_id,
                metadata={"message_id": message_id},
            )
            assert ChannelManager._inbound_dedupe_key(bound) == (channel, chat_id, chat_id, message_id)

    def test_inbound_dedupe_key_uses_dingtalk_conversation_id_when_unbound(self):
        """DingTalk stamps conversation_id on every inbound; use it when unbound.

        Group connections store workspace_id=conversation_id; P2P stores None.
        Without a metadata fallback, unbound groups and all P2P traffic skipped
        dedupe entirely (including bound P2P, whose connection.workspace_id is
        None). conversation_id is already on the message and is the natural
        tenant scope — same role as Slack team_id / Discord guild_id.
        """
        from app.channels.manager import ChannelManager

        group_unbound = InboundMessage(
            channel_name="dingtalk",
            chat_id="cid123",
            user_id="staff1",
            text="hi",
            metadata={
                "conversation_type": "2",
                "conversation_id": "cid123",
                "message_id": "mid1",
            },
        )
        assert ChannelManager._inbound_dedupe_key(group_unbound) == ("dingtalk", "cid123", "cid123", "mid1")

        p2p = InboundMessage(
            channel_name="dingtalk",
            chat_id="staff1",
            user_id="staff1",
            text="hi",
            # Bound P2P still has workspace_id=None on the connection record.
            connection_id="conn1",
            owner_user_id="owner1",
            workspace_id=None,
            metadata={
                "conversation_type": "1",
                "conversation_id": "cid_p2p",
                "message_id": "mid1",
            },
        )
        assert ChannelManager._inbound_dedupe_key(p2p) == ("dingtalk", "cid_p2p", "staff1", "mid1")

    def test_inbound_dedupe_chat_scoped_fallback_does_not_collapse_distinct_chats(self):
        """newly_missed guard: chat_id fallback must not cross-dedupe two chats.

        Same stable message_id string in two different chats is legitimate and
        must produce distinct keys (message_ids are only unique per chat on
        Telegram/Feishu/WeChat).
        """
        from app.channels.manager import ChannelManager

        a = InboundMessage(
            channel_name="telegram",
            chat_id="111",
            user_id="u1",
            text="hi",
            metadata={"message_id": "42"},
        )
        b = InboundMessage(
            channel_name="telegram",
            chat_id="222",
            user_id="u2",
            text="hi",
            metadata={"message_id": "42"},
        )
        assert ChannelManager._inbound_dedupe_key(a) == ("telegram", "111", "111", "42")
        assert ChannelManager._inbound_dedupe_key(b) == ("telegram", "222", "222", "42")
        assert ChannelManager._inbound_dedupe_key(a) != ChannelManager._inbound_dedupe_key(b)

    @pytest.mark.parametrize(
        ("channel", "chat_id"),
        (
            ("wechat", "wx_user_1"),
            ("telegram", "12345"),
            ("feishu", "oc_abc"),
        ),
    )
    def test_dispatch_loop_dedupes_unbound_chat_scoped_redelivery(self, tmp_path, monkeypatch, channel, chat_id):
        """Provider redelivery of an unbound chat-scoped message runs the agent once.

        Shaped like wechat.py / telegram.py inbound metadata (message_id only, no
        workspace_id / team_id) before attach_connection_identity finds a binding.
        Parametrized across all three CHAT_SCOPED_WORKSPACE_CHANNELS so the
        streaming dispatch path (telegram/feishu) is covered end-to-end too, not
        only WeChat's runs.wait path.
        """
        monkeypatch.setattr("app.channels.manager.STREAM_UPDATE_MIN_INTERVAL_SECONDS", 0.0)
        from app.channels.manager import ChannelManager

        streaming = ChannelManager._channel_supports_streaming(channel)

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=tmp_path / "store.json")
            manager = ChannelManager(bus=bus, store=store)
            manager._client = _make_mock_langgraph_client()
            manager._client.runs.stream = MagicMock(side_effect=lambda *a, **kw: _make_async_iterator(_ok_stream_events()))
            outbound_received: list[OutboundMessage] = []

            async def capture_outbound(msg: OutboundMessage) -> None:
                outbound_received.append(msg)

            bus.subscribe_outbound(capture_outbound)
            await manager.start()

            # The mock the channel's dispatch path actually drives.
            run_call = manager._client.runs.stream if streaming else manager._client.runs.wait

            def _inbound(message_id: str) -> InboundMessage:
                return InboundMessage(
                    channel_name=channel,
                    chat_id=chat_id,
                    user_id="u1",
                    text=f"hello from {channel}",
                    metadata={"message_id": message_id},
                )

            await bus.publish_inbound(_inbound("m-1"))
            await bus.publish_inbound(_inbound("m-1"))
            await _wait_for(lambda: run_call.call_count == 1 and any(m.is_final for m in outbound_received))
            await asyncio.sleep(0.05)
            assert run_call.call_count == 1

            # Distinct message_id still processes (negative control / newly_missed).
            await bus.publish_inbound(_inbound("m-2"))
            await _wait_for(lambda: run_call.call_count == 2)
            await asyncio.sleep(0.05)
            await manager.stop()

            assert run_call.call_count == 2

        _run(go())

    def test_streaming_transient_failure_releases_dedupe_key(self, tmp_path, monkeypatch):
        """Release a swallowed streaming error only after its final outbound.

        _release_inbound_dedupe_key lives in _handle_message's `except Exception`
        handler, but _handle_streaming_chat handles its own errors and never
        re-raises — so without an explicit release the key recorded on receipt
        survives the full dedupe TTL and the provider's redelivery (the retry
        that would recover the failure) is silently dropped. Releasing before
        the final outbound would let that retry overtake the terminal reply.
        """
        monkeypatch.setattr("app.channels.manager.STREAM_UPDATE_MIN_INTERVAL_SECONDS", 0.0)
        from app.channels.manager import ChannelManager

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=tmp_path / "store.json")
            manager = ChannelManager(bus=bus, store=store)
            outbound_received: list[OutboundMessage] = []
            key_present_during_final_publish: list[bool] = []

            async def capture_outbound(msg: OutboundMessage) -> None:
                outbound_received.append(msg)
                if msg.is_final:
                    key = manager._inbound_dedupe_key(_inbound())
                    key_present_during_final_publish.append(key in manager._recent_inbound_events)

            bus.subscribe_outbound(capture_outbound)

            def _failing_stream(*args, **kwargs):
                async def gen():
                    yield _make_stream_part(
                        "messages-tuple",
                        [{"id": "ai-1", "content": "Partial", "type": "AIMessageChunk"}, {"langgraph_node": "agent"}],
                    )
                    raise ConnectionError("stream broken")

                return gen()

            manager._client = _make_mock_langgraph_client()
            manager._client.runs.stream = MagicMock(side_effect=_failing_stream)
            await manager.start()

            def _inbound() -> InboundMessage:
                return InboundMessage(
                    channel_name="feishu",
                    chat_id="chat1",
                    user_id="u1",
                    text="hi",
                    metadata={"message_id": "m-1"},
                )

            await bus.publish_inbound(_inbound())
            await _wait_for(lambda: any(m.is_final for m in outbound_received))
            await asyncio.sleep(0.05)
            assert manager._client.runs.stream.call_count == 1
            assert key_present_during_final_publish == [True]

            # The provider redelivers the same message after the failure.
            await bus.publish_inbound(_inbound())
            await _wait_for(lambda: manager._client.runs.stream.call_count == 2)
            await manager.stop()

            assert manager._client.runs.stream.call_count == 2

        _run(go())

    def test_thread_busy_releases_dedupe_key(self, tmp_path):
        """A busy thread is transient, so its redelivery must stay reprocessable.

        runs.wait's ConflictError is handled in place (busy message, no re-raise),
        so it bypasses _handle_message's release just like the streaming path.
        """
        import httpx
        from langgraph_sdk.errors import ConflictError

        from app.channels.manager import THREAD_BUSY_MESSAGE, ChannelManager

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=tmp_path / "store.json")
            manager = ChannelManager(bus=bus, store=store)
            outbound_received: list[OutboundMessage] = []

            async def capture_outbound(msg: OutboundMessage) -> None:
                outbound_received.append(msg)

            bus.subscribe_outbound(capture_outbound)

            request = httpx.Request("POST", "http://127.0.0.1:2024/threads/t/runs")
            conflict = ConflictError(
                "Thread is already running a task.",
                response=httpx.Response(409, request=request),
                body={"message": "Thread is already running a task."},
            )
            manager._client = _make_mock_langgraph_client()
            manager._client.runs.wait = AsyncMock(side_effect=conflict)
            await manager.start()

            def _inbound() -> InboundMessage:
                return InboundMessage(
                    channel_name="wechat",
                    chat_id="wx_user_1",
                    user_id="wx_user_1",
                    text="hi",
                    metadata={"message_id": "m-1"},
                )

            await bus.publish_inbound(_inbound())
            await _wait_for(lambda: any(m.text == THREAD_BUSY_MESSAGE for m in outbound_received))
            await asyncio.sleep(0.05)
            assert manager._client.runs.wait.call_count == 1

            await bus.publish_inbound(_inbound())
            await _wait_for(lambda: manager._client.runs.wait.call_count == 2)
            await manager.stop()

            assert manager._client.runs.wait.call_count == 2

        _run(go())

    def test_fire_and_forget_thread_busy_releases_dedupe_key(self, tmp_path):
        """Same invariant on the third swallow site: runs.create's busy branch."""
        import httpx
        from langgraph_sdk.errors import ConflictError

        import app.gateway.github.run_policy  # noqa: F401 — register policy
        from app.channels.manager import THREAD_BUSY_MESSAGE, ChannelManager

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=tmp_path / "store.json")
            manager = ChannelManager(bus=bus, store=store)
            outbound_received: list[OutboundMessage] = []

            async def capture_outbound(msg: OutboundMessage) -> None:
                outbound_received.append(msg)

            bus.subscribe_outbound(capture_outbound)

            request = httpx.Request("POST", "http://127.0.0.1:2024/threads/t/runs")
            conflict = ConflictError(
                "Thread is already running a task.",
                response=httpx.Response(409, request=request),
                body={"message": "Thread is already running a task."},
            )
            manager._client = _make_mock_langgraph_client()
            manager._client.runs.create = AsyncMock(side_effect=conflict)
            await manager.start()

            def _inbound() -> InboundMessage:
                return InboundMessage(
                    channel_name="github",
                    chat_id="owner/repo",
                    user_id="dev",
                    owner_user_id="agent-owner-1",
                    workspace_id="owner/repo",
                    text="hi",
                    metadata={"message_id": "delivery-1:dev:agent"},
                )

            await bus.publish_inbound(_inbound())
            await _wait_for(lambda: any(m.text == THREAD_BUSY_MESSAGE for m in outbound_received))
            await asyncio.sleep(0.05)
            assert manager._client.runs.create.call_count == 1

            await bus.publish_inbound(_inbound())
            await _wait_for(lambda: manager._client.runs.create.call_count == 2)
            await manager.stop()

            assert manager._client.runs.create.call_count == 2

        _run(go())

    def test_github_redelivery_is_deduped_like_other_channels(self, tmp_path):
        """A redelivered GitHub webhook must dispatch the agent only once.

        PR #3584 added inbound dedupe for the IM channels; the GitHub channel
        added in PR #3754 never stamped the ``message_id`` / workspace the
        dedupe keys on, so GitHub's native "Redeliver" button or a
        retry-on-timeout re-ran the agent with real side effects (e.g. a
        duplicate PR comment). The dispatcher now stamps the X-GitHub-Delivery
        GUID (scoped per agent) plus the repo, so the same manager dedupe
        absorbs the replay — while a second agent bound to the same delivery,
        and a genuinely new delivery, still fire.
        """
        from app.channels.manager import ChannelManager

        manager = ChannelManager(bus=MessageBus(), store=ChannelStore(path=tmp_path / "store.json"))

        def _gh(delivery: str, agent: str = "reviewer") -> InboundMessage:
            # Shaped exactly as app.gateway.github.dispatcher.fanout_event emits.
            return InboundMessage(
                channel_name="github",
                chat_id="zhfeng/llm-gateway",
                user_id="alice",
                text="@bot please review",
                topic_id=f"7:{agent}",
                workspace_id="zhfeng/llm-gateway",
                metadata={"message_id": f"{delivery}:{agent}", "agent_name": agent},
            )

        # The dedupe key matches the other channels' 4-tuple shape.
        assert ChannelManager._inbound_dedupe_key(_gh("d1")) == ("github", "zhfeng/llm-gateway", "zhfeng/llm-gateway", "d1:reviewer")

        # First delivery fires; an identical redelivery of the same GUID is dropped.
        assert manager._is_duplicate_inbound(_gh("d1")) is False
        assert manager._is_duplicate_inbound(_gh("d1")) is True
        # A genuinely new delivery still fires.
        assert manager._is_duplicate_inbound(_gh("d2")) is False
        # A second agent fanned out from the SAME delivery is not cross-deduped.
        assert manager._is_duplicate_inbound(_gh("d1", agent="coder")) is False

    def test_dispatch_loop_releases_dedupe_key_when_handling_fails(self, tmp_path):
        """A transient handling failure must not black-hole a provider redelivery (ShenAC #1)."""
        from app.channels.manager import ChannelManager

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=tmp_path / "store.json")
            manager = ChannelManager(bus=bus, store=store)
            client = _make_mock_langgraph_client()
            attempts = {"n": 0}

            async def flaky_wait(*args, **kwargs):
                attempts["n"] += 1
                if attempts["n"] == 1:
                    raise RuntimeError("transient gateway 503")
                return {"messages": [{"type": "human", "content": "hi"}, {"type": "ai", "content": "recovered"}]}

            client.runs.wait = AsyncMock(side_effect=flaky_wait)
            manager._client = client

            outbound_received: list[OutboundMessage] = []

            async def capture_outbound(msg: OutboundMessage) -> None:
                outbound_received.append(msg)

            bus.subscribe_outbound(capture_outbound)
            await manager.start()

            inbound = InboundMessage(
                channel_name="slack",
                chat_id="C123",
                user_id="U123",
                text="hello",
                metadata={"team_id": "T123", "message_id": "m-1"},
            )

            # First delivery fails transiently; the dedupe key must be released.
            await bus.publish_inbound(inbound)
            await _wait_for(lambda: attempts["n"] == 1 and len(outbound_received) >= 1)

            # Provider redelivers the same message_id: it must be reprocessed, not dropped.
            await bus.publish_inbound(inbound)
            await _wait_for(lambda: attempts["n"] == 2)
            await asyncio.sleep(0.05)
            await manager.stop()

            assert attempts["n"] == 2

        _run(go())

    def test_handle_chat_outbound_preserves_inbound_metadata(self):
        """DingTalk (and similar) need inbound metadata on outbound sends (e.g. sender_staff_id)."""
        from app.channels.manager import ChannelManager

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(bus=bus, store=store)
            outbound_received: list[OutboundMessage] = []

            async def capture_outbound(msg: OutboundMessage) -> None:
                outbound_received.append(msg)

            bus.subscribe_outbound(capture_outbound)
            mock_client = _make_mock_langgraph_client()
            manager._client = mock_client
            await manager.start()

            meta = {
                "sender_staff_id": "staff_001",
                "conversation_type": "1",
                "conversation_id": "conv_001",
            }
            inbound = InboundMessage(
                channel_name="test",
                chat_id="chat1",
                user_id="user1",
                text="hi",
                metadata=meta,
            )
            await bus.publish_inbound(inbound)
            await _wait_for(lambda: len(outbound_received) >= 1)
            await manager.stop()

            assert len(outbound_received) == 1
            assert outbound_received[0].metadata == meta

        _run(go())

    def test_handle_chat_marks_clarification_outbound_metadata(self):
        from app.channels.manager import ChannelManager

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(bus=bus, store=store)
            outbound_received: list[OutboundMessage] = []

            async def capture_outbound(msg: OutboundMessage) -> None:
                outbound_received.append(msg)

            bus.subscribe_outbound(capture_outbound)
            mock_client = _make_mock_langgraph_client(
                run_result={
                    "messages": [
                        {"type": "human", "content": "deploy"},
                        {"type": "ai", "content": "", "tool_calls": [{"name": "ask_clarification", "args": {}}]},
                        {"type": "tool", "name": "ask_clarification", "content": "Which environment?"},
                    ]
                }
            )
            manager._client = mock_client
            await manager.start()

            inbound = InboundMessage(
                channel_name="test",
                chat_id="chat1",
                user_id="user1",
                text="deploy",
                metadata={"message_id": "msg-1"},
            )
            await bus.publish_inbound(inbound)
            await _wait_for(lambda: len(outbound_received) >= 1)
            await manager.stop()

            assert outbound_received[0].text == "Which environment?"
            assert outbound_received[0].metadata["message_id"] == "msg-1"
            assert outbound_received[0].metadata[PENDING_CLARIFICATION_METADATA_KEY] is True

        _run(go())

    def test_handle_chat_does_not_mark_regular_outbound_as_clarification(self):
        from app.channels.manager import ChannelManager

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(bus=bus, store=store)
            outbound_received: list[OutboundMessage] = []

            async def capture_outbound(msg: OutboundMessage) -> None:
                outbound_received.append(msg)

            bus.subscribe_outbound(capture_outbound)
            mock_client = _make_mock_langgraph_client()
            manager._client = mock_client
            await manager.start()

            await bus.publish_inbound(InboundMessage(channel_name="test", chat_id="chat1", user_id="user1", text="hi"))
            await _wait_for(lambda: len(outbound_received) >= 1)
            await manager.stop()

            assert outbound_received[0].text == "Hello from agent!"
            assert PENDING_CLARIFICATION_METADATA_KEY not in outbound_received[0].metadata

        _run(go())

    def test_handle_chat_outbound_drops_large_metadata_keys(self):
        """Large metadata keys like raw_message should be stripped from outbound messages."""
        from app.channels.manager import ChannelManager

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(bus=bus, store=store)
            outbound_received: list[OutboundMessage] = []

            async def capture_outbound(msg: OutboundMessage) -> None:
                outbound_received.append(msg)

            bus.subscribe_outbound(capture_outbound)
            mock_client = _make_mock_langgraph_client()
            manager._client = mock_client
            await manager.start()

            meta = {
                "sender_staff_id": "staff_001",
                "conversation_type": "1",
                "raw_message": {"huge": "payload" * 1000},
                "ref_msg": {"also": "large"},
            }
            inbound = InboundMessage(
                channel_name="test",
                chat_id="chat1",
                user_id="user1",
                text="hi",
                metadata=meta,
            )
            await bus.publish_inbound(inbound)
            await _wait_for(lambda: len(outbound_received) >= 1)
            await manager.stop()

            assert len(outbound_received) == 1
            out_meta = outbound_received[0].metadata
            assert "sender_staff_id" in out_meta
            assert "conversation_type" in out_meta
            assert "raw_message" not in out_meta
            assert "ref_msg" not in out_meta

        _run(go())

    def test_handle_chat_uses_channel_session_overrides(self):
        from app.channels.manager import ChannelManager

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(
                bus=bus,
                store=store,
                channel_sessions={
                    "slack": {
                        "assistant_id": "mobile_agent",
                        "config": {"recursion_limit": 55},
                        "context": {
                            "thinking_enabled": False,
                            "subagent_enabled": True,
                        },
                    }
                },
            )

            outbound_received = []

            async def capture_outbound(msg):
                outbound_received.append(msg)

            bus.subscribe_outbound(capture_outbound)

            mock_client = _make_mock_langgraph_client()
            manager._client = mock_client

            await manager.start()

            inbound = InboundMessage(channel_name="slack", chat_id="chat1", user_id="user1", text="hi")
            await bus.publish_inbound(inbound)
            await _wait_for(lambda: len(outbound_received) >= 1)
            await manager.stop()

            mock_client.runs.wait.assert_called_once()
            call_args = mock_client.runs.wait.call_args
            assert call_args[0][1] == "lead_agent"
            assert call_args[1]["config"]["recursion_limit"] == 55
            assert call_args[1]["config"]["configurable"]["checkpoint_ns"] == ""
            assert call_args[1]["config"]["configurable"]["thread_id"] == "test-thread-123"
            assert call_args[1]["context"]["thinking_enabled"] is False
            assert call_args[1]["context"]["subagent_enabled"] is True
            assert call_args[1]["context"]["agent_name"] == "mobile-agent"

        _run(go())

    def test_clarification_follow_up_preserves_history(self, monkeypatch):
        """Conversation should continue after ask_clarification instead of resetting history."""
        from app.channels.manager import ChannelManager

        monkeypatch.delenv("DEER_FLOW_AUTH_DISABLED", raising=False)

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(bus=bus, store=store)

            outbound_received = []

            async def capture_outbound(msg):
                outbound_received.append(msg)

            bus.subscribe_outbound(capture_outbound)

            history_by_checkpoint: dict[tuple[str, str], list[str]] = {}

            async def _runs_wait(thread_id, assistant_id, *, input, config, context, multitask_strategy=None):
                del assistant_id, context  # unused in this test, kept for signature parity

                checkpoint_ns = config.get("configurable", {}).get("checkpoint_ns")
                key = (thread_id, str(checkpoint_ns))
                history = history_by_checkpoint.setdefault(key, [])

                human_text = input["messages"][0]["content"]
                history.append(human_text)

                if len(history) == 1:
                    return {
                        "messages": [
                            {"type": "human", "content": history[0]},
                            {
                                "type": "ai",
                                "content": "",
                                "tool_calls": [
                                    {
                                        "name": "ask_clarification",
                                        "args": {"question": "Which environment should I use?"},
                                    }
                                ],
                            },
                            {
                                "type": "tool",
                                "name": "ask_clarification",
                                "content": "Which environment should I use?",
                            },
                        ]
                    }

                if len(history) == 2 and history[0] == "Deploy my app" and history[1] == "prod":
                    return {
                        "messages": [
                            {"type": "human", "content": history[0]},
                            {
                                "type": "ai",
                                "content": "",
                                "tool_calls": [
                                    {
                                        "name": "ask_clarification",
                                        "args": {"question": "Which environment should I use?"},
                                    }
                                ],
                            },
                            {
                                "type": "tool",
                                "name": "ask_clarification",
                                "content": "Which environment should I use?",
                            },
                            {"type": "human", "content": history[1]},
                            {"type": "ai", "content": "Got it. I will deploy to prod."},
                        ]
                    }

                return {
                    "messages": [
                        {"type": "human", "content": history[-1]},
                        {"type": "ai", "content": "History missing; clarification repeated."},
                    ]
                }

            mock_client = MagicMock()
            mock_client.threads.create = AsyncMock(return_value={"thread_id": "clarify-thread-1"})
            mock_client.threads.get = AsyncMock(return_value={"thread_id": "clarify-thread-1"})
            mock_client.runs.wait = AsyncMock(side_effect=_runs_wait)
            manager._client = mock_client

            await manager.start()

            await bus.publish_inbound(
                InboundMessage(
                    channel_name="test",
                    chat_id="chat1",
                    user_id="user1",
                    text="Deploy my app",
                )
            )
            await _wait_for(lambda: len(outbound_received) >= 1)

            await bus.publish_inbound(
                InboundMessage(
                    channel_name="test",
                    chat_id="chat1",
                    user_id="user1",
                    text="prod",
                )
            )
            await _wait_for(lambda: len(outbound_received) >= 2)
            await manager.stop()

            assert outbound_received[0].text == "Which environment should I use?"
            assert outbound_received[1].text == "Got it. I will deploy to prod."

            assert mock_client.runs.wait.call_count == 2
            first_call = mock_client.runs.wait.call_args_list[0]
            second_call = mock_client.runs.wait.call_args_list[1]
            assert first_call.kwargs["config"]["configurable"]["checkpoint_ns"] == ""
            assert second_call.kwargs["config"]["configurable"]["checkpoint_ns"] == ""

        _run(go())

    def test_handle_chat_uses_user_session_overrides(self):
        from app.channels.manager import ChannelManager

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(
                bus=bus,
                store=store,
                default_session={"context": {"is_plan_mode": True}},
                channel_sessions={
                    "slack": {
                        "assistant_id": "mobile_agent",
                        "config": {"recursion_limit": 55},
                        "context": {
                            "thinking_enabled": False,
                            "subagent_enabled": False,
                        },
                        "users": {
                            "vip-user": {
                                "assistant_id": " VIP_AGENT ",
                                "config": {"recursion_limit": 77},
                                "context": {
                                    "thinking_enabled": True,
                                    "subagent_enabled": True,
                                },
                            }
                        },
                    }
                },
            )

            outbound_received = []

            async def capture_outbound(msg):
                outbound_received.append(msg)

            bus.subscribe_outbound(capture_outbound)

            mock_client = _make_mock_langgraph_client()
            manager._client = mock_client

            await manager.start()

            inbound = InboundMessage(channel_name="slack", chat_id="chat1", user_id="vip-user", text="hi")
            await bus.publish_inbound(inbound)
            await _wait_for(lambda: len(outbound_received) >= 1)
            await manager.stop()

            mock_client.runs.wait.assert_called_once()
            call_args = mock_client.runs.wait.call_args
            assert call_args[0][1] == "lead_agent"
            assert call_args[1]["config"]["recursion_limit"] == 77
            assert call_args[1]["context"]["thinking_enabled"] is True
            assert call_args[1]["context"]["subagent_enabled"] is True
            assert call_args[1]["context"]["agent_name"] == "vip-agent"
            assert call_args[1]["context"]["is_plan_mode"] is True

        _run(go())

    def test_handle_chat_rejects_invalid_custom_agent_name(self):
        from app.channels.manager import ChannelManager

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(
                bus=bus,
                store=store,
                channel_sessions={
                    "telegram": {
                        "assistant_id": "bad agent!",
                    }
                },
            )

            outbound_received = []

            async def capture_outbound(msg):
                outbound_received.append(msg)

            bus.subscribe_outbound(capture_outbound)

            mock_client = _make_mock_langgraph_client()
            manager._client = mock_client

            await manager.start()

            inbound = InboundMessage(channel_name="telegram", chat_id="chat1", user_id="user1", text="hi")
            await bus.publish_inbound(inbound)
            await _wait_for(lambda: len(outbound_received) >= 1)
            await manager.stop()

            mock_client.runs.wait.assert_not_called()
            assert outbound_received[0].text == ("Invalid channel session assistant_id 'bad agent!'. Use 'lead_agent' or a custom agent name containing only letters, digits, and hyphens.")

        _run(go())

    def test_handle_feishu_chat_streams_multiple_outbound_updates(self, monkeypatch):
        from app.channels.manager import ChannelManager

        monkeypatch.setattr("app.channels.manager.STREAM_UPDATE_MIN_INTERVAL_SECONDS", 0.0)

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(bus=bus, store=store)

            outbound_received = []

            async def capture_outbound(msg):
                outbound_received.append(msg)

            bus.subscribe_outbound(capture_outbound)

            stream_events = [
                _make_stream_part(
                    "messages-tuple",
                    [
                        {"id": "ai-1", "content": "Hello", "type": "AIMessageChunk"},
                        {"langgraph_node": "agent"},
                    ],
                ),
                _make_stream_part(
                    "messages-tuple",
                    [
                        {"id": "ai-1", "content": " world", "type": "AIMessageChunk"},
                        {"langgraph_node": "agent"},
                    ],
                ),
                _make_stream_part(
                    "values",
                    {
                        "messages": [
                            {"type": "human", "content": "hi"},
                            {"type": "ai", "content": "Hello world"},
                        ],
                        "artifacts": [],
                    },
                ),
            ]

            mock_client = _make_mock_langgraph_client()
            mock_client.runs.stream = MagicMock(return_value=_make_async_iterator(stream_events))
            manager._client = mock_client

            await manager.start()

            inbound = InboundMessage(
                channel_name="feishu",
                chat_id="chat1",
                user_id="user1",
                text="hi",
                thread_ts="om-source-1",
            )
            await bus.publish_inbound(inbound)
            await _wait_for(lambda: len(outbound_received) >= 3)
            await manager.stop()

            mock_client.runs.stream.assert_called_once()
            assert [msg.text for msg in outbound_received] == ["Hello ▉", "Hello world ▉", "Hello world"]
            assert [msg.is_final for msg in outbound_received] == [False, False, True]
            assert all(msg.thread_ts == "om-source-1" for msg in outbound_received)

        _run(go())

    def test_handle_streaming_chat_accepts_runtime_messages_event(self, monkeypatch):
        """The embedded runtime emits SSE event name "messages" (LangGraph
        Platform semantics) for the requested "messages-tuple" stream mode —
        the manager must accumulate text from those events too."""
        from app.channels.manager import ChannelManager

        monkeypatch.setattr("app.channels.manager.STREAM_UPDATE_MIN_INTERVAL_SECONDS", 0.0)

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(bus=bus, store=store)

            outbound_received = []

            async def capture_outbound(msg):
                outbound_received.append(msg)

            bus.subscribe_outbound(capture_outbound)

            stream_events = [
                _make_stream_part(
                    "messages",
                    [
                        {"id": "ai-1", "content": "Hello", "type": "AIMessageChunk"},
                        {"langgraph_node": "agent"},
                    ],
                ),
                _make_stream_part(
                    "messages",
                    [
                        {"id": "ai-1", "content": " world", "type": "AIMessageChunk"},
                        {"langgraph_node": "agent"},
                    ],
                ),
                _make_stream_part(
                    "values",
                    {
                        "messages": [
                            {"type": "human", "content": "hi"},
                            {"type": "ai", "content": "Hello world"},
                        ],
                        "artifacts": [],
                    },
                ),
            ]

            mock_client = _make_mock_langgraph_client()
            mock_client.runs.stream = MagicMock(return_value=_make_async_iterator(stream_events))
            manager._client = mock_client

            await manager.start()

            inbound = InboundMessage(
                channel_name="telegram",
                chat_id="chat1",
                user_id="user1",
                text="hi",
                thread_ts="42",
            )
            await bus.publish_inbound(inbound)
            await _wait_for(lambda: len(outbound_received) >= 3)
            await manager.stop()

            mock_client.runs.stream.assert_called_once()
            assert [msg.text for msg in outbound_received] == ["Hello ▉", "Hello world ▉", "Hello world"]
            assert [msg.is_final for msg in outbound_received] == [False, False, True]

        _run(go())

    def test_handle_feishu_streaming_marks_only_final_clarification_outbound(self, monkeypatch):
        from app.channels.manager import ChannelManager

        monkeypatch.setattr("app.channels.manager.STREAM_UPDATE_MIN_INTERVAL_SECONDS", 0.0)

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(bus=bus, store=store)
            outbound_received: list[OutboundMessage] = []

            async def capture_outbound(msg: OutboundMessage) -> None:
                outbound_received.append(msg)

            bus.subscribe_outbound(capture_outbound)
            stream_events = [
                _make_stream_part(
                    "messages-tuple",
                    [
                        {"id": "ai-1", "content": "Thinking", "type": "AIMessageChunk"},
                        {"langgraph_node": "agent"},
                    ],
                ),
                _make_stream_part(
                    "values",
                    {
                        "messages": [
                            {"type": "human", "content": "deploy"},
                            {"type": "ai", "content": "", "tool_calls": [{"name": "ask_clarification", "args": {}}]},
                            {"type": "tool", "name": "ask_clarification", "content": "Which environment?"},
                        ],
                        "artifacts": [],
                    },
                ),
            ]
            mock_client = _make_mock_langgraph_client()
            mock_client.runs.stream = MagicMock(return_value=_make_async_iterator(stream_events))
            manager._client = mock_client
            await manager.start()

            await bus.publish_inbound(
                InboundMessage(
                    channel_name="feishu",
                    chat_id="chat1",
                    user_id="user1",
                    text="deploy",
                    thread_ts="om-source-1",
                )
            )
            await _wait_for(lambda: len(outbound_received) >= 2)
            await manager.stop()

            assert [msg.is_final for msg in outbound_received] == [False, False, True]
            assert outbound_received[0].text == "Thinking ▉"
            assert outbound_received[1].text == "Which environment? ▉"
            assert outbound_received[2].text == "Which environment?"
            assert all(PENDING_CLARIFICATION_METADATA_KEY not in msg.metadata for msg in outbound_received[:-1])
            assert outbound_received[-1].metadata[PENDING_CLARIFICATION_METADATA_KEY] is True

        _run(go())

    def test_handle_feishu_stream_error_still_sends_final(self, monkeypatch):
        """When the stream raises mid-way, a final outbound with is_final=True must still be published."""
        from app.channels.manager import ChannelManager

        monkeypatch.setattr("app.channels.manager.STREAM_UPDATE_MIN_INTERVAL_SECONDS", 0.0)

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(bus=bus, store=store)

            outbound_received = []

            async def capture_outbound(msg):
                outbound_received.append(msg)

            bus.subscribe_outbound(capture_outbound)

            async def _failing_stream():
                yield _make_stream_part(
                    "messages-tuple",
                    [
                        {"id": "ai-1", "content": "Partial", "type": "AIMessageChunk"},
                        {"langgraph_node": "agent"},
                    ],
                )
                raise ConnectionError("stream broken")

            mock_client = _make_mock_langgraph_client()
            mock_client.runs.stream = MagicMock(return_value=_failing_stream())
            manager._client = mock_client

            await manager.start()

            inbound = InboundMessage(
                channel_name="feishu",
                chat_id="chat1",
                user_id="user1",
                text="hi",
                thread_ts="om-source-1",
            )
            await bus.publish_inbound(inbound)
            await _wait_for(lambda: any(m.is_final for m in outbound_received))
            await manager.stop()

            # Should have at least one intermediate and one final message
            final_msgs = [m for m in outbound_received if m.is_final]
            assert len(final_msgs) == 1
            assert final_msgs[0].thread_ts == "om-source-1"

        _run(go())

    def test_handle_feishu_stream_conflict_sends_busy_message(self, monkeypatch):
        import httpx
        from langgraph_sdk.errors import ConflictError

        from app.channels.manager import THREAD_BUSY_MESSAGE, ChannelManager

        monkeypatch.setattr("app.channels.manager.STREAM_UPDATE_MIN_INTERVAL_SECONDS", 0.0)

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(bus=bus, store=store)

            outbound_received = []

            async def capture_outbound(msg):
                outbound_received.append(msg)

            bus.subscribe_outbound(capture_outbound)

            async def _conflict_stream():
                request = httpx.Request("POST", "http://127.0.0.1:2024/runs")
                response = httpx.Response(409, request=request)
                raise ConflictError(
                    "Thread is already running a task. Wait for it to finish or choose a different multitask strategy.",
                    response=response,
                    body={"message": "Thread is already running a task. Wait for it to finish or choose a different multitask strategy."},
                )
                yield  # pragma: no cover

            mock_client = _make_mock_langgraph_client()
            mock_client.runs.stream = MagicMock(return_value=_conflict_stream())
            manager._client = mock_client

            await manager.start()

            inbound = InboundMessage(
                channel_name="feishu",
                chat_id="chat1",
                user_id="user1",
                text="hi",
                thread_ts="om-source-1",
            )
            await bus.publish_inbound(inbound)
            await _wait_for(lambda: any(m.is_final for m in outbound_received))
            await manager.stop()

            final_msgs = [m for m in outbound_received if m.is_final]
            assert len(final_msgs) == 1
            assert final_msgs[0].text == THREAD_BUSY_MESSAGE
            assert final_msgs[0].thread_ts == "om-source-1"

        _run(go())

    def test_handle_feishu_same_thread_messages_queue_instead_of_busy(self, monkeypatch):
        from app.channels.manager import THREAD_BUSY_MESSAGE, ChannelManager

        monkeypatch.setattr("app.channels.manager.STREAM_UPDATE_MIN_INTERVAL_SECONDS", 0.0)

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(bus=bus, store=store)

            outbound_received = []

            async def capture_outbound(msg):
                outbound_received.append(msg)

            bus.subscribe_outbound(capture_outbound)

            first_started = asyncio.Event()
            release_first = asyncio.Event()
            second_started = asyncio.Event()

            async def _stream(thread_id, assistant_id, *, input, **kwargs):  # noqa: ARG001
                prompt = input["messages"][0]["content"]
                if prompt == "first":
                    first_started.set()
                    await release_first.wait()
                    yield _make_stream_part(
                        "values",
                        {
                            "messages": [
                                {"type": "human", "content": "first"},
                                {"type": "ai", "content": "First done"},
                            ],
                            "artifacts": [],
                        },
                    )
                    return

                second_started.set()
                yield _make_stream_part(
                    "values",
                    {
                        "messages": [
                            {"type": "human", "content": "second"},
                            {"type": "ai", "content": "Second done"},
                        ],
                        "artifacts": [],
                    },
                )

            mock_client = _make_mock_langgraph_client(thread_id="feishu-thread-1")
            mock_client.runs.stream = MagicMock(side_effect=_stream)
            manager._client = mock_client

            await manager.start()

            await bus.publish_inbound(
                InboundMessage(
                    channel_name="feishu",
                    chat_id="chat1",
                    user_id="user1",
                    text="first",
                    topic_id="topic-1",
                    thread_ts="om-source-1",
                )
            )
            await _wait_for(first_started.is_set)

            await bus.publish_inbound(
                InboundMessage(
                    channel_name="feishu",
                    chat_id="chat1",
                    user_id="user1",
                    text="second",
                    topic_id="topic-1",
                    thread_ts="om-source-2",
                )
            )

            await _wait_for(lambda: any(message.thread_ts == "om-source-2" and message.text.startswith("Queued behind another request") for message in outbound_received))
            assert second_started.is_set() is False

            release_first.set()
            await _wait_for(second_started.is_set)
            await _wait_for(lambda: len([message for message in outbound_received if message.is_final]) == 2)
            await manager.stop()

            assert all(message.text != THREAD_BUSY_MESSAGE for message in outbound_received)
            second_turn = [message for message in outbound_received if message.thread_ts == "om-source-2"]
            assert second_turn[0].text.startswith("Queued behind another request")
            assert any(message.text == "thinking..." for message in second_turn if message.is_final is False)
            assert second_turn[-1].text == "Second done"
            assert mock_client.runs.stream.call_count == 2

        _run(go())

    def test_handle_feishu_queue_waiter_cleanup_on_cancelled_progress_publish(self):
        from app.channels.manager import ChannelManager

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(bus=bus, store=store)

            msg = InboundMessage(
                channel_name="feishu",
                chat_id="chat1",
                user_id="user1",
                text="second",
                topic_id="topic-1",
                thread_ts="om-source-2",
            )

            thread_id = "feishu-thread-1"
            serial_state, _ = manager._begin_serialized_thread_run(
                channel_name="feishu",
                thread_id=thread_id,
            )
            assert serial_state is not None
            await serial_state.lock.acquire()

            manager._get_client = MagicMock(return_value=object())
            manager._get_or_create_thread = AsyncMock(return_value=(thread_id, False))
            manager._update_thread_channel_metadata = AsyncMock()
            manager._publish_progress_update = AsyncMock(side_effect=asyncio.CancelledError())
            manager._handle_chat_on_thread = AsyncMock()

            with pytest.raises(asyncio.CancelledError):
                await manager._handle_chat(msg, bound_identity_checked=True)

            leaked_state = manager._serialized_thread_runs.get(("feishu", thread_id))
            assert leaked_state is serial_state
            assert leaked_state.waiters == 1
            assert leaked_state.lock.locked() is True
            manager._handle_chat_on_thread.assert_not_awaited()

            manager._finish_serialized_thread_run(
                channel_name="feishu",
                thread_id=thread_id,
                state=serial_state,
                lock_acquired=True,
            )
            assert ("feishu", thread_id) not in manager._serialized_thread_runs

        _run(go())

    def test_handle_feishu_different_threads_can_stream_concurrently(self, monkeypatch):
        from app.channels.manager import ChannelManager

        monkeypatch.setattr("app.channels.manager.STREAM_UPDATE_MIN_INTERVAL_SECONDS", 0.0)

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(bus=bus, store=store)

            first_started = asyncio.Event()
            second_started = asyncio.Event()
            release_streams = asyncio.Event()

            async def create_thread(**kwargs):
                topic_id = kwargs["metadata"]["channel_source"]["topic_id"]
                return {"thread_id": f"thread-{topic_id}"}

            async def _stream(thread_id, assistant_id, *, input, **kwargs):  # noqa: ARG001
                if thread_id == "thread-topic-a":
                    first_started.set()
                elif thread_id == "thread-topic-b":
                    second_started.set()
                await release_streams.wait()
                yield _make_stream_part(
                    "values",
                    {
                        "messages": [
                            {"type": "human", "content": input["messages"][0]["content"]},
                            {"type": "ai", "content": f"done:{thread_id}"},
                        ],
                        "artifacts": [],
                    },
                )

            mock_client = _make_mock_langgraph_client()
            mock_client.threads.create = AsyncMock(side_effect=create_thread)
            mock_client.runs.stream = MagicMock(side_effect=_stream)
            manager._client = mock_client

            outbound_received = []

            async def capture_outbound(msg):
                outbound_received.append(msg)

            bus.subscribe_outbound(capture_outbound)

            await manager.start()
            await bus.publish_inbound(
                InboundMessage(
                    channel_name="feishu",
                    chat_id="chat1",
                    user_id="user1",
                    text="first",
                    topic_id="topic-a",
                    thread_ts="om-source-a",
                )
            )
            await bus.publish_inbound(
                InboundMessage(
                    channel_name="feishu",
                    chat_id="chat1",
                    user_id="user1",
                    text="second",
                    topic_id="topic-b",
                    thread_ts="om-source-b",
                )
            )

            await _wait_for(first_started.is_set)
            await _wait_for(second_started.is_set)
            release_streams.set()
            await _wait_for(lambda: len([message for message in outbound_received if message.is_final]) == 2)
            await manager.stop()

            assert mock_client.runs.stream.call_count == 2
            assert not any(message.text.startswith("Queued behind another request") for message in outbound_received)

        _run(go())

    def test_handle_command_help(self):
        from app.channels.manager import ChannelManager

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(bus=bus, store=store)

            outbound_received = []

            async def capture_outbound(msg):
                outbound_received.append(msg)

            bus.subscribe_outbound(capture_outbound)
            await manager.start()

            inbound = InboundMessage(
                channel_name="test",
                chat_id="chat1",
                user_id="user1",
                text="/help",
                msg_type=InboundMessageType.COMMAND,
            )
            await bus.publish_inbound(inbound)
            await _wait_for(lambda: len(outbound_received) >= 1)
            await manager.stop()

            assert len(outbound_received) == 1
            assert "/new" in outbound_received[0].text
            assert "/help" in outbound_received[0].text

        _run(go())

    def test_handle_command_blank_text_is_reported_without_running_agent(self):
        from app.channels.manager import ChannelManager

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(bus=bus, store=store)

            mock_client = _make_mock_langgraph_client()
            manager._client = mock_client

            outbound_received = []

            async def capture_outbound(msg):
                outbound_received.append(msg)

            bus.subscribe_outbound(capture_outbound)
            await manager.start()

            inbound = InboundMessage(
                channel_name="test",
                chat_id="chat1",
                user_id="user1",
                text="   ",
                msg_type=InboundMessageType.COMMAND,
            )
            await bus.publish_inbound(inbound)
            await _wait_for(lambda: len(outbound_received) >= 1)
            await manager.stop()

            mock_client.runs.wait.assert_not_called()
            assert outbound_received[0].text.startswith("Unknown command.")

        _run(go())

    def test_handle_command_rejects_multi_slash_control_command(self):
        from app.channels.manager import ChannelManager

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(bus=bus, store=store)

            mock_client = _make_mock_langgraph_client()
            manager._client = mock_client

            outbound_received = []

            async def capture_outbound(msg):
                outbound_received.append(msg)

            bus.subscribe_outbound(capture_outbound)
            await manager.start()

            inbound = InboundMessage(
                channel_name="test",
                chat_id="chat1",
                user_id="user1",
                text="//help",
                msg_type=InboundMessageType.COMMAND,
            )
            await bus.publish_inbound(inbound)
            await _wait_for(lambda: len(outbound_received) >= 1)
            await manager.stop()

            mock_client.runs.wait.assert_not_called()
            assert outbound_received[0].text.startswith("Unknown command: //help.")

        _run(go())

    def test_handle_command_requires_control_command_at_start(self):
        from app.channels.manager import ChannelManager

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(bus=bus, store=store)

            mock_client = _make_mock_langgraph_client(thread_id="new-thread-456")
            manager._client = mock_client

            outbound_received = []

            async def capture_outbound(msg):
                outbound_received.append(msg)

            bus.subscribe_outbound(capture_outbound)
            await manager.start()

            inbound = InboundMessage(
                channel_name="test",
                chat_id="chat1",
                user_id="user1",
                text=" /new",
                msg_type=InboundMessageType.COMMAND,
            )
            await bus.publish_inbound(inbound)
            await _wait_for(lambda: len(outbound_received) >= 1)
            await manager.stop()

            mock_client.threads.create.assert_not_called()
            assert store.get_thread_id("test", "chat1") is None
            assert outbound_received[0].text.startswith("Unknown command: /new.")

        _run(go())

    def test_handle_command_outbound_thread_id_uses_topic_thread(self):
        from app.channels.manager import ChannelManager

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(bus=bus, store=store)
            store.set_thread_id("test", "chat1", "base-thread")
            store.set_thread_id("test", "chat1", "topic-thread", topic_id="topic-1")

            outbound_received = []

            async def capture_outbound(msg):
                outbound_received.append(msg)

            bus.subscribe_outbound(capture_outbound)
            await manager.start()

            inbound = InboundMessage(
                channel_name="test",
                chat_id="chat1",
                user_id="user1",
                text="/status",
                msg_type=InboundMessageType.COMMAND,
                topic_id="topic-1",
            )
            await bus.publish_inbound(inbound)
            await _wait_for(lambda: len(outbound_received) >= 1)
            await manager.stop()

            assert outbound_received[0].text == "Active thread: topic-thread"
            assert outbound_received[0].thread_id == "topic-thread"

        _run(go())

    def test_handle_command_slash_skill_routes_to_chat(self, tmp_path):
        from app.channels.manager import ChannelManager

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(bus=bus, store=store)
            manager._skill_storage = _make_channel_skill_storage([_make_channel_skill(tmp_path, "data-analysis")])

            mock_client = _make_mock_langgraph_client()
            manager._client = mock_client

            outbound_received = []

            async def capture_outbound(msg):
                outbound_received.append(msg)

            bus.subscribe_outbound(capture_outbound)
            await manager.start()

            inbound = InboundMessage(
                channel_name="test",
                chat_id="chat1",
                user_id="user1",
                text="/data-analysis analyze uploads/foo.csv",
                msg_type=InboundMessageType.COMMAND,
            )
            await bus.publish_inbound(inbound)
            await _wait_for(lambda: len(outbound_received) >= 1)
            await manager.stop()

            mock_client.runs.wait.assert_called_once()
            call_args = mock_client.runs.wait.call_args
            assert call_args[1]["input"]["messages"][0]["content"] == "/data-analysis analyze uploads/foo.csv"
            assert outbound_received[0].text == "Hello from agent!"

        _run(go())

    def test_handle_command_slash_skill_with_attachment_preserves_original_content(self, monkeypatch, tmp_path):
        from app.channels.manager import ChannelManager

        async def fake_ingest(thread_id, msg, *, user_id=None):
            del user_id
            return [
                {
                    "filename": "report.pdf",
                    "size": 12,
                    "path": "/mnt/user-data/uploads/report.pdf",
                    "is_image": False,
                }
            ]

        monkeypatch.setattr("app.channels.manager._ingest_inbound_files", fake_ingest)

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(bus=bus, store=store)
            manager._skill_storage = _make_channel_skill_storage([_make_channel_skill(tmp_path, "data-analysis")])

            mock_client = _make_mock_langgraph_client()
            manager._client = mock_client

            outbound_received = []

            async def capture_outbound(msg):
                outbound_received.append(msg)

            bus.subscribe_outbound(capture_outbound)
            await manager.start()

            original_text = "/data-analysis analyze report.pdf"
            inbound = InboundMessage(
                channel_name="test",
                chat_id="chat1",
                user_id="user1",
                text=original_text,
                files=[{"filename": "report.pdf"}],
                msg_type=InboundMessageType.COMMAND,
            )
            await bus.publish_inbound(inbound)
            await _wait_for(lambda: len(outbound_received) >= 1)
            await manager.stop()

            mock_client.runs.wait.assert_called_once()
            human_message = mock_client.runs.wait.call_args[1]["input"]["messages"][0]
            assert human_message["content"].startswith("<uploaded_files>")
            assert original_text in human_message["content"]
            assert human_message["additional_kwargs"][ORIGINAL_USER_CONTENT_KEY] == original_text
            assert outbound_received[0].text == "Hello from agent!"

        _run(go())

    def test_streaming_slash_skill_with_attachment_preserves_original_content(self, monkeypatch, tmp_path):
        from app.channels.manager import ChannelManager

        async def fake_ingest(thread_id, msg, *, user_id=None):
            del user_id
            return [
                {
                    "filename": "report.pdf",
                    "size": 12,
                    "path": "/mnt/user-data/uploads/report.pdf",
                    "is_image": False,
                }
            ]

        monkeypatch.setattr("app.channels.manager._ingest_inbound_files", fake_ingest)

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(bus=bus, store=store)
            manager._skill_storage = _make_channel_skill_storage([_make_channel_skill(tmp_path, "data-analysis")])

            mock_client = _make_mock_langgraph_client()
            mock_client.runs.stream = MagicMock(
                return_value=_make_async_iterator(
                    [
                        _make_stream_part(
                            "values",
                            {"messages": [{"type": "ai", "content": "streamed response"}]},
                        )
                    ]
                )
            )
            manager._client = mock_client

            outbound_received = []

            async def capture_outbound(msg):
                outbound_received.append(msg)

            bus.subscribe_outbound(capture_outbound)
            await manager.start()

            original_text = "/data-analysis analyze report.pdf"
            inbound = InboundMessage(
                channel_name="feishu",
                chat_id="chat1",
                user_id="user1",
                text=original_text,
                files=[{"filename": "report.pdf"}],
                msg_type=InboundMessageType.COMMAND,
            )
            await bus.publish_inbound(inbound)
            await _wait_for(lambda: any(message.is_final for message in outbound_received))
            await manager.stop()

            mock_client.runs.stream.assert_called_once()
            human_message = mock_client.runs.stream.call_args[1]["input"]["messages"][0]
            assert human_message["content"].startswith("<uploaded_files>")
            assert original_text in human_message["content"]
            assert human_message["additional_kwargs"][ORIGINAL_USER_CONTENT_KEY] == original_text

        _run(go())

    def test_handle_command_slash_skill_requires_command_at_start(self, tmp_path):
        from app.channels.manager import ChannelManager

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(bus=bus, store=store)
            manager._skill_storage = _make_channel_skill_storage([_make_channel_skill(tmp_path, "data-analysis")])

            mock_client = _make_mock_langgraph_client()
            manager._client = mock_client

            outbound_received = []

            async def capture_outbound(msg):
                outbound_received.append(msg)

            bus.subscribe_outbound(capture_outbound)
            await manager.start()

            inbound = InboundMessage(
                channel_name="test",
                chat_id="chat1",
                user_id="user1",
                text="  /data-analysis analyze uploads/foo.csv",
                msg_type=InboundMessageType.COMMAND,
            )
            await bus.publish_inbound(inbound)
            await _wait_for(lambda: len(outbound_received) >= 1)
            await manager.stop()

            mock_client.runs.wait.assert_not_called()
            assert outbound_received[0].text.startswith("Unknown command: /data-analysis.")

        _run(go())

    def test_handle_command_slash_skill_respects_custom_agent_skill_whitelist(self, monkeypatch, tmp_path):
        from app.channels.manager import ChannelManager

        monkeypatch.setattr("app.channels.manager.load_agent_config", lambda name, *, user_id=None: SimpleNamespace(skills=["frontend-design"]))

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(
                bus=bus,
                store=store,
                default_session={"assistant_id": "analyst-agent"},
            )
            manager._skill_storage = _make_channel_skill_storage([_make_channel_skill(tmp_path, "data-analysis")])

            mock_client = _make_mock_langgraph_client()
            manager._client = mock_client

            outbound_received = []

            async def capture_outbound(msg):
                outbound_received.append(msg)

            bus.subscribe_outbound(capture_outbound)
            await manager.start()

            inbound = InboundMessage(
                channel_name="test",
                chat_id="chat1",
                user_id="user1",
                text="/data-analysis analyze uploads/foo.csv",
                msg_type=InboundMessageType.COMMAND,
            )
            await bus.publish_inbound(inbound)
            await _wait_for(lambda: len(outbound_received) >= 1)
            await manager.stop()

            mock_client.runs.wait.assert_not_called()
            assert outbound_received[0].text == "Skill `/data-analysis` is not available for this agent."

        _run(go())

    def test_slash_skill_whitelist_loads_agent_config_for_the_resolved_owner(self, monkeypatch):
        """The per-user custom agent whitelist must be read from the same owner
        bucket the run uses. ``_resolve_run_params`` resolves that owner into
        ``run_context["user_id"]`` (per ``_channel_storage_user_id``, the single
        source of truth for run identity and storage), but the whitelist
        pre-check dropped it, so ``load_agent_config`` fell back to the dispatch
        loop's unset contextvar (``"default"``) — reading, or failing to find,
        the wrong user's agent config.
        """
        from app.channels.manager import ChannelManager

        captured: dict[str, object] = {}

        def spy_load_agent_config(name, *, user_id=None):
            captured["name"] = name
            captured["user_id"] = user_id
            return SimpleNamespace(skills=["data-analysis"])

        monkeypatch.setattr("app.channels.manager.load_agent_config", spy_load_agent_config)

        bus = MessageBus()
        store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
        manager = ChannelManager(bus=bus, store=store, default_session={"assistant_id": "analyst-agent"})

        # A bound connection: the owner resolves to a real, non-default bucket.
        msg = InboundMessage(
            channel_name="test",
            chat_id="chat1",
            user_id="platform-user",
            owner_user_id="owner-alice",
            text="/data-analysis go",
            msg_type=InboundMessageType.COMMAND,
        )

        expected_owner = manager._resolve_run_params(msg, "")[2].get("user_id")

        manager._resolve_available_skill_names(msg)

        assert expected_owner and expected_owner != "default"
        assert captured["user_id"] == expected_owner

    def test_handle_command_slash_skill_reports_disabled_skill(self, tmp_path):
        from app.channels.manager import ChannelManager

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(bus=bus, store=store)
            manager._skill_storage = _make_channel_skill_storage([_make_channel_skill(tmp_path, "data-analysis", enabled=False)])

            mock_client = _make_mock_langgraph_client()
            manager._client = mock_client

            outbound_received = []

            async def capture_outbound(msg):
                outbound_received.append(msg)

            bus.subscribe_outbound(capture_outbound)
            await manager.start()

            inbound = InboundMessage(
                channel_name="test",
                chat_id="chat1",
                user_id="user1",
                text="/data-analysis analyze uploads/foo.csv",
                msg_type=InboundMessageType.COMMAND,
            )
            await bus.publish_inbound(inbound)
            await _wait_for(lambda: len(outbound_received) >= 1)
            await manager.stop()

            mock_client.runs.wait.assert_not_called()
            assert outbound_received[0].text == "Skill `/data-analysis` is installed but disabled. Enable it before using slash activation."

        _run(go())

    def test_handle_command_uninstalled_slash_skill_stays_unknown_command(self, tmp_path):
        from app.channels.manager import ChannelManager

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(bus=bus, store=store)
            manager._skill_storage = _make_channel_skill_storage([_make_channel_skill(tmp_path, "frontend-design")])

            mock_client = _make_mock_langgraph_client()
            manager._client = mock_client

            outbound_received = []

            async def capture_outbound(msg):
                outbound_received.append(msg)

            bus.subscribe_outbound(capture_outbound)
            await manager.start()

            inbound = InboundMessage(
                channel_name="test",
                chat_id="chat1",
                user_id="user1",
                text="/data-analysis analyze uploads/foo.csv",
                msg_type=InboundMessageType.COMMAND,
            )
            await bus.publish_inbound(inbound)
            await _wait_for(lambda: len(outbound_received) >= 1)
            await manager.stop()

            mock_client.runs.wait.assert_not_called()
            assert outbound_received[0].text.startswith("Unknown command: /data-analysis.")

        _run(go())

    def test_handle_command_slash_skill_resolution_error_is_reported(self, monkeypatch):
        from app.channels.manager import ChannelManager, SlashSkillCommandResolutionError

        def fail_resolution(text, available_skills=None, storage=None):
            raise SlashSkillCommandResolutionError("Failed to resolve slash skill command. Please check the skill configuration.")

        monkeypatch.setattr("app.channels.manager._resolve_slash_skill_command", fail_resolution)

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(bus=bus, store=store)
            store.set_thread_id("test", "chat1", "base-thread")
            store.set_thread_id("test", "chat1", "topic-thread", topic_id="topic-1")

            mock_client = _make_mock_langgraph_client()
            manager._client = mock_client

            outbound_received = []

            async def capture_outbound(msg):
                outbound_received.append(msg)

            bus.subscribe_outbound(capture_outbound)
            await manager.start()

            inbound = InboundMessage(
                channel_name="test",
                chat_id="chat1",
                user_id="user1",
                text="/data-analysis analyze uploads/foo.csv",
                msg_type=InboundMessageType.COMMAND,
                topic_id="topic-1",
            )
            await bus.publish_inbound(inbound)
            await _wait_for(lambda: len(outbound_received) >= 1)
            await manager.stop()

            mock_client.runs.wait.assert_not_called()
            assert outbound_received[0].text == "Failed to resolve slash skill command. Please check the skill configuration."
            assert outbound_received[0].thread_id == "topic-thread"

        _run(go())

    def test_handle_command_new(self):
        from app.channels.manager import ChannelManager

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(bus=bus, store=store)

            store.set_thread_id("test", "chat1", "old-thread")

            mock_client = _make_mock_langgraph_client(thread_id="new-thread-456")
            manager._client = mock_client

            outbound_received = []

            async def capture_outbound(msg):
                outbound_received.append(msg)

            bus.subscribe_outbound(capture_outbound)
            await manager.start()

            inbound = InboundMessage(
                channel_name="test",
                chat_id="chat1",
                user_id="user1",
                text="/new",
                msg_type=InboundMessageType.COMMAND,
            )
            await bus.publish_inbound(inbound)
            await _wait_for(lambda: len(outbound_received) >= 1)
            await manager.stop()

            new_thread = store.get_thread_id("test", "chat1")
            assert new_thread == "new-thread-456"
            assert new_thread != "old-thread"
            assert "New conversation started" in outbound_received[0].text

            # threads.create should be called for /new
            mock_client.threads.create.assert_called_once()

        _run(go())

    def test_each_topic_creates_new_thread(self):
        """Messages with distinct topic_ids should each create a new DeerFlow thread."""
        from app.channels.manager import ChannelManager

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(bus=bus, store=store)

            # Return a different thread_id for each create call
            thread_ids = iter(["thread-1", "thread-2"])

            async def create_thread(**kwargs):
                return {"thread_id": next(thread_ids)}

            mock_client = _make_mock_langgraph_client()
            mock_client.threads.create = AsyncMock(side_effect=create_thread)
            manager._client = mock_client

            outbound_received = []

            async def capture(msg):
                outbound_received.append(msg)

            bus.subscribe_outbound(capture)
            await manager.start()

            # Send two messages with different topic_ids (e.g. group chat, each starts a new topic)
            for i, text in enumerate(["first", "second"]):
                await bus.publish_inbound(
                    InboundMessage(
                        channel_name="test",
                        chat_id="chat1",
                        user_id="user1",
                        text=text,
                        topic_id=f"topic-{i}",
                    )
                )
            await _wait_for(lambda: mock_client.runs.wait.call_count >= 2)
            await manager.stop()

            # threads.create should be called twice (different topics)
            assert mock_client.threads.create.call_count == 2

            # runs.wait should be called twice with different thread_ids
            assert mock_client.runs.wait.call_count == 2
            wait_thread_ids = [c[0][0] for c in mock_client.runs.wait.call_args_list]
            assert "thread-1" in wait_thread_ids
            assert "thread-2" in wait_thread_ids

        _run(go())

    def test_same_topic_reuses_thread(self, monkeypatch):
        """Messages with the same topic_id should reuse the same DeerFlow thread."""
        from app.channels.manager import ChannelManager

        monkeypatch.delenv("DEER_FLOW_AUTH_DISABLED", raising=False)

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(bus=bus, store=store)

            mock_client = _make_mock_langgraph_client(thread_id="topic-thread-1")
            manager._client = mock_client

            outbound_received = []

            async def capture(msg):
                outbound_received.append(msg)

            bus.subscribe_outbound(capture)
            await manager.start()

            # Send two messages with the same topic_id (simulates replies in a thread)
            for text in ["first message", "follow-up"]:
                msg = InboundMessage(
                    channel_name="test",
                    chat_id="chat1",
                    user_id="user1",
                    text=text,
                    topic_id="topic-root-123",
                )
                await bus.publish_inbound(msg)

            await _wait_for(lambda: mock_client.runs.wait.call_count >= 2)
            await manager.stop()

            # threads.create should be called only ONCE (second message reuses the thread)
            mock_client.threads.create.assert_called_once()
            mock_client.threads.update.assert_called_once_with(
                "topic-thread-1",
                metadata={
                    "channel_source": {
                        "type": "im_channel",
                        "provider": "test",
                        "chat_id": "chat1",
                        "topic_id": "topic-root-123",
                    }
                },
            )

            # Both runs.wait calls should use the same thread_id
            assert mock_client.runs.wait.call_count == 2
            for call in mock_client.runs.wait.call_args_list:
                assert call[0][0] == "topic-thread-1"

        _run(go())

    def test_none_topic_reuses_thread(self):
        """Messages with topic_id=None should reuse the same thread (e.g. a private/direct chat)."""
        from app.channels.manager import ChannelManager

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(bus=bus, store=store)

            mock_client = _make_mock_langgraph_client(thread_id="private-thread-1")
            manager._client = mock_client

            outbound_received = []

            async def capture(msg):
                outbound_received.append(msg)

            bus.subscribe_outbound(capture)
            await manager.start()

            # Send two messages with topic_id=None (simulates a private/direct chat)
            for text in ["hello", "what did I just say?"]:
                msg = InboundMessage(
                    channel_name="slack",
                    chat_id="chat1",
                    user_id="user1",
                    text=text,
                    topic_id=None,
                )
                await bus.publish_inbound(msg)

            await _wait_for(lambda: mock_client.runs.wait.call_count >= 2)
            await manager.stop()

            # threads.create should be called only ONCE (second message reuses the thread)
            mock_client.threads.create.assert_called_once()

            # Both runs.wait calls should use the same thread_id
            assert mock_client.runs.wait.call_count == 2
            for call in mock_client.runs.wait.call_args_list:
                assert call[0][0] == "private-thread-1"

        _run(go())

    def test_different_topics_get_different_threads(self):
        """Messages with different topic_ids should create separate threads."""
        from app.channels.manager import ChannelManager

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(bus=bus, store=store)

            thread_ids = iter(["thread-A", "thread-B"])

            async def create_thread(**kwargs):
                return {"thread_id": next(thread_ids)}

            mock_client = _make_mock_langgraph_client()
            mock_client.threads.create = AsyncMock(side_effect=create_thread)
            manager._client = mock_client

            bus.subscribe_outbound(lambda msg: None)
            await manager.start()

            # Send messages with different topic_ids
            for topic in ["topic-1", "topic-2"]:
                msg = InboundMessage(
                    channel_name="test",
                    chat_id="chat1",
                    user_id="user1",
                    text="hi",
                    topic_id=topic,
                )
                await bus.publish_inbound(msg)

            await _wait_for(lambda: mock_client.runs.wait.call_count >= 2)
            await manager.stop()

            # threads.create called twice (different topics)
            assert mock_client.threads.create.call_count == 2

            # runs.wait used different thread_ids
            wait_thread_ids = [c[0][0] for c in mock_client.runs.wait.call_args_list]
            assert set(wait_thread_ids) == {"thread-A", "thread-B"}

        _run(go())

    def test_handle_command_bootstrap_with_text(self):
        """/bootstrap <text> should route to chat with is_bootstrap=True in run_context."""
        from app.channels.manager import ChannelManager

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(bus=bus, store=store)

            outbound_received = []

            async def capture_outbound(msg):
                outbound_received.append(msg)

            bus.subscribe_outbound(capture_outbound)

            mock_client = _make_mock_langgraph_client()
            manager._client = mock_client

            await manager.start()

            inbound = InboundMessage(
                channel_name="test",
                chat_id="chat1",
                user_id="user1",
                text="/bootstrap setup my workspace",
                msg_type=InboundMessageType.COMMAND,
            )
            await bus.publish_inbound(inbound)
            await _wait_for(lambda: len(outbound_received) >= 1)
            await manager.stop()

            # Should go through the chat path (runs.wait), not the command reply path
            mock_client.runs.wait.assert_called_once()
            call_args = mock_client.runs.wait.call_args

            # The text sent to the agent should be the part after /bootstrap
            assert call_args[1]["input"]["messages"][0]["content"] == "setup my workspace"

            # run_context should contain is_bootstrap=True
            assert call_args[1]["context"]["is_bootstrap"] is True

            # Normal context fields should still be present
            assert "thread_id" in call_args[1]["context"]

            # Should get the agent response (not a command reply)
            assert outbound_received[0].text == "Hello from agent!"

        _run(go())

    def test_handle_command_bootstrap_without_text(self):
        """/bootstrap with no text should use a default message."""
        from app.channels.manager import ChannelManager

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(bus=bus, store=store)

            outbound_received = []

            async def capture_outbound(msg):
                outbound_received.append(msg)

            bus.subscribe_outbound(capture_outbound)

            mock_client = _make_mock_langgraph_client()
            manager._client = mock_client

            await manager.start()

            inbound = InboundMessage(
                channel_name="test",
                chat_id="chat1",
                user_id="user1",
                text="/bootstrap",
                msg_type=InboundMessageType.COMMAND,
            )
            await bus.publish_inbound(inbound)
            await _wait_for(lambda: len(outbound_received) >= 1)
            await manager.stop()

            mock_client.runs.wait.assert_called_once()
            call_args = mock_client.runs.wait.call_args

            # Default text should be used when no text is provided
            assert call_args[1]["input"]["messages"][0]["content"] == "Initialize workspace"
            assert call_args[1]["context"]["is_bootstrap"] is True

        _run(go())

    def test_handle_command_bootstrap_feishu_uses_streaming(self, monkeypatch):
        """/bootstrap from feishu should go through the streaming path."""
        from app.channels.manager import ChannelManager

        monkeypatch.setattr("app.channels.manager.STREAM_UPDATE_MIN_INTERVAL_SECONDS", 0.0)

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(bus=bus, store=store)

            outbound_received = []

            async def capture_outbound(msg):
                outbound_received.append(msg)

            bus.subscribe_outbound(capture_outbound)

            stream_events = [
                _make_stream_part(
                    "values",
                    {
                        "messages": [
                            {"type": "human", "content": "hello"},
                            {"type": "ai", "content": "Bootstrap done"},
                        ],
                        "artifacts": [],
                    },
                ),
            ]

            mock_client = _make_mock_langgraph_client()
            mock_client.runs.stream = MagicMock(return_value=_make_async_iterator(stream_events))
            manager._client = mock_client

            await manager.start()

            inbound = InboundMessage(
                channel_name="feishu",
                chat_id="chat1",
                user_id="user1",
                text="/bootstrap hello",
                msg_type=InboundMessageType.COMMAND,
                thread_ts="om-source-1",
            )
            await bus.publish_inbound(inbound)
            await _wait_for(lambda: any(m.is_final for m in outbound_received))
            await manager.stop()

            # Should use streaming path (runs.stream, not runs.wait)
            mock_client.runs.stream.assert_called_once()
            call_args = mock_client.runs.stream.call_args

            assert call_args[1]["input"]["messages"][0]["content"] == "hello"
            assert call_args[1]["config"]["configurable"]["checkpoint_ns"] == ""
            assert call_args[1]["config"]["configurable"]["thread_id"] == "test-thread-123"
            assert call_args[1]["context"]["is_bootstrap"] is True

            # Final message should be published
            final_msgs = [m for m in outbound_received if m.is_final]
            assert len(final_msgs) == 1
            assert final_msgs[0].text == "Bootstrap done"

        _run(go())

    def test_handle_command_bootstrap_creates_thread_if_needed(self):
        """/bootstrap should create a new thread when none exists."""
        from app.channels.manager import ChannelManager

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(bus=bus, store=store)

            outbound_received = []

            async def capture_outbound(msg):
                outbound_received.append(msg)

            bus.subscribe_outbound(capture_outbound)

            mock_client = _make_mock_langgraph_client(thread_id="bootstrap-thread")
            manager._client = mock_client

            await manager.start()

            inbound = InboundMessage(
                channel_name="test",
                chat_id="chat1",
                user_id="user1",
                text="/bootstrap init",
                msg_type=InboundMessageType.COMMAND,
            )
            await bus.publish_inbound(inbound)
            await _wait_for(lambda: len(outbound_received) >= 1)
            await manager.stop()

            # A thread should be created
            mock_client.threads.create.assert_called_once()
            assert store.get_thread_id("test", "chat1") == "bootstrap-thread"

        _run(go())

    def test_help_includes_bootstrap(self):
        """/help output should mention /bootstrap."""
        from app.channels.manager import ChannelManager

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(bus=bus, store=store)

            outbound_received = []

            async def capture(msg):
                outbound_received.append(msg)

            bus.subscribe_outbound(capture)
            await manager.start()

            inbound = InboundMessage(
                channel_name="test",
                chat_id="chat1",
                user_id="user1",
                text="/help",
                msg_type=InboundMessageType.COMMAND,
            )
            await bus.publish_inbound(inbound)
            await _wait_for(lambda: len(outbound_received) >= 1)
            await manager.stop()

            assert "/bootstrap" in outbound_received[0].text

        _run(go())


class TestResolveRunParamsUserId:
    """Regression for PR #3294: channel identity must reach ``run_context``
    while staying safe for user-scoped filesystem buckets.
    """

    def _manager(self):
        from app.channels.manager import ChannelManager

        bus = MessageBus()
        store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
        return ChannelManager(bus=bus, store=store)

    def test_safe_user_id_is_passed_through(self, monkeypatch):
        manager = self._manager()
        monkeypatch.delenv("DEER_FLOW_AUTH_DISABLED", raising=False)
        msg = InboundMessage(channel_name="telegram", chat_id="c", user_id="123456", text="hi")

        _, _, run_context = manager._resolve_run_params(msg, "thread-1")

        assert run_context["user_id"] == "123456"
        assert run_context["channel_user_id"] == "123456"

    def test_resolve_run_params_plumbs_channel_name_into_run_context(self):
        """``channel_name`` must land on ``run_context`` so in-graph code can
        gate tool exposure on it.

        Concretely: the lead-agent factory withholds the ``update_agent``
        tool from runs whose ``run_context["channel_name"]`` is webhook-shaped
        (currently ``"github"``). If this plumbing regresses, the factory
        loses the only signal it has to make that decision and webhook
        runs silently regain a privilege-escalation path.
        """
        manager = self._manager()

        gh_msg = InboundMessage(channel_name="github", chat_id="acme/widget", user_id="alice", text="hi")
        _, _, gh_ctx = manager._resolve_run_params(gh_msg, "thread-1")
        assert gh_ctx["channel_name"] == "github"

        tg_msg = InboundMessage(channel_name="telegram", chat_id="c", user_id="42", text="hi")
        _, _, tg_ctx = manager._resolve_run_params(tg_msg, "thread-2")
        assert tg_ctx["channel_name"] == "telegram"

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"user_id": "U-platform", "owner_user_id": "deerflow-user-1"},  # bound
            {"user_id": "U-platform"},  # unbound auth-enabled
            {"user_id": "feishu|ou_AbC/123"},  # unbound needing sanitization
        ],
    )
    def test_run_identity_matches_storage_bucket(self, kwargs, monkeypatch):
        """The run user_id and the file/artifact storage bucket share one resolver.

        Pins #2 and #3 to a single source of truth so they cannot drift: whatever
        _resolve_run_params puts in run_context["user_id"] is exactly what
        _channel_storage_user_id scopes uploads/artifacts to.
        """
        from app.channels.manager import _channel_storage_user_id

        manager = self._manager()
        monkeypatch.delenv("DEER_FLOW_AUTH_DISABLED", raising=False)
        msg = InboundMessage(channel_name="slack", chat_id="C123", text="hi", **kwargs)

        _, _, run_context = manager._resolve_run_params(msg, "thread-1")

        assert run_context["user_id"] == _channel_storage_user_id(msg)

    def test_connection_owner_user_id_takes_precedence_over_platform_user_id(self, monkeypatch):
        manager = self._manager()
        monkeypatch.delenv("DEER_FLOW_AUTH_DISABLED", raising=False)
        msg = InboundMessage(
            channel_name="slack",
            chat_id="C123",
            user_id="U-platform",
            owner_user_id="deerflow-user-1",
            connection_id="connection-1",
            text="hi",
        )

        _, _, run_context = manager._resolve_run_params(msg, "thread-1")

        assert run_context["user_id"] == "deerflow-user-1"
        assert run_context["channel_user_id"] == "U-platform"

    def test_github_channel_gets_raised_recursion_limit(self):
        """Autonomous GitHub coding runs (clone → edit → test → push → PR) need
        more super-steps than an interactive chat turn. The default
        ``recursion_limit`` of 100 is raised for the github channel only."""
        manager = self._manager()

        gh_msg = InboundMessage(channel_name="github", chat_id="zhfeng/llm-gateway", user_id="zhfeng", text="hi")
        _, gh_config, _ = manager._resolve_run_params(gh_msg, "thread-1")
        assert gh_config["recursion_limit"] >= 250

        # Interactive channels keep the default ceiling.
        slack_msg = InboundMessage(channel_name="slack", chat_id="C1", user_id="u", text="hi")
        _, slack_config, _ = manager._resolve_run_params(slack_msg, "thread-1")
        assert slack_config["recursion_limit"] == 100

    def test_github_channel_recursion_limit_respects_higher_override(self):
        """An explicit higher recursion_limit in channel/user config must not be
        lowered by the github bump (it uses ``max``)."""
        manager = self._manager()
        manager._default_session["config"] = {"recursion_limit": 400}

        gh_msg = InboundMessage(channel_name="github", chat_id="zhfeng/llm-gateway", user_id="zhfeng", text="hi")
        _, gh_config, _ = manager._resolve_run_params(gh_msg, "thread-1")
        assert gh_config["recursion_limit"] == 400

    def test_github_channel_per_agent_recursion_limit_override(self):
        """An agent's ``github.recursion_limit`` overrides the channel default.

        Some autonomous workloads (large refactors, multi-file migrations)
        need more headroom than 250; others (review-only agents) need less.
        The per-agent value flows via ``msg.metadata["github"]["recursion_limit"]``
        — the dispatcher reads it from ``GitHubAgentConfig`` at fanout time.
        The per-agent value is honored verbatim, including values below the
        channel default and below 100.
        """
        manager = self._manager()

        # Higher than the channel default — agent gets the bigger ceiling.
        gh_msg = InboundMessage(
            channel_name="github",
            chat_id="zhfeng/llm-gateway",
            user_id="zhfeng",
            text="hi",
            metadata={"github": {"recursion_limit": 500}},
        )
        _, gh_config, _ = manager._resolve_run_params(gh_msg, "thread-1")
        assert gh_config["recursion_limit"] == 500

        # Below the channel default — agent gets the lower ceiling.
        gh_msg_low = InboundMessage(
            channel_name="github",
            chat_id="zhfeng/llm-gateway",
            user_id="zhfeng",
            text="hi",
            metadata={"github": {"recursion_limit": 120}},
        )
        _, gh_config_low, _ = manager._resolve_run_params(gh_msg_low, "thread-1")
        assert gh_config_low["recursion_limit"] == 120

    def test_github_channel_per_agent_recursion_limit_honors_value_below_100(self):
        """Regression pin for willem-bd's finding #4 on PR #3754.

        Previously the channel-policy step did ``max(existing, limit)``
        which clamped any per-agent recursion_limit below 100 up to 100,
        silently breaking a safety-conscious ``github.recursion_limit: 50``
        on a review-only agent. The per-agent value is now honored
        verbatim for any positive integer, including values below 100.
        """
        manager = self._manager()

        # 50: well below the 100 floor that the old max() would have applied,
        # AND below the 250 channel default. Both clamps would silently lose
        # this setting; the per-agent value must win.
        gh_msg = InboundMessage(
            channel_name="github",
            chat_id="zhfeng/llm-gateway",
            user_id="zhfeng",
            text="hi",
            metadata={"github": {"recursion_limit": 50}},
        )
        _, gh_config, _ = manager._resolve_run_params(gh_msg, "thread-1")
        assert gh_config["recursion_limit"] == 50

        # Boundary just-below-default to pin the contract: the override
        # always wins over the channel default, no matter the relative size.
        for value in (1, 25, 99, 100, 249, 250, 251, 1024):
            gh_msg = InboundMessage(
                channel_name="github",
                chat_id="zhfeng/llm-gateway",
                user_id="zhfeng",
                text="hi",
                metadata={"github": {"recursion_limit": value}},
            )
            _, gh_config, _ = manager._resolve_run_params(gh_msg, "thread-1")
            assert gh_config["recursion_limit"] == value, f"override {value!r} must be honored verbatim"

    def test_github_channel_recursion_limit_ignores_invalid_override(self):
        """Non-int / non-positive recursion_limit values fall back to the channel default."""
        manager = self._manager()

        for bad in (None, 0, -1, "many", 3.5):
            gh_msg = InboundMessage(
                channel_name="github",
                chat_id="zhfeng/llm-gateway",
                user_id="zhfeng",
                text="hi",
                metadata={"github": {"recursion_limit": bad}},
            )
            _, gh_config, _ = manager._resolve_run_params(gh_msg, "thread-1")
            assert gh_config["recursion_limit"] == 250, f"bad value {bad!r} should fall back to 250"

    def test_auth_disabled_user_id_is_used_for_unbound_channel_messages(self, monkeypatch):
        from app.gateway.auth_disabled import AUTH_DISABLED_USER_ID
        from app.gateway.internal_auth import INTERNAL_OWNER_USER_ID_HEADER_NAME

        manager = self._manager()
        monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "1")
        msg = InboundMessage(channel_name="slack", chat_id="C123", user_id="U-platform", text="hi")

        _, _, run_context = manager._resolve_run_params(msg, "thread-1")

        assert run_context["user_id"] == AUTH_DISABLED_USER_ID
        assert run_context["channel_user_id"] == "U-platform"

        from app.channels.manager import _owner_headers

        headers = _owner_headers(msg)
        assert headers is not None
        assert headers[INTERNAL_OWNER_USER_ID_HEADER_NAME] == AUTH_DISABLED_USER_ID

    def test_auth_disabled_user_id_overrides_bound_owner_for_local_visibility(self, monkeypatch):
        from app.gateway.auth_disabled import AUTH_DISABLED_USER_ID

        manager = self._manager()
        monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "1")
        msg = InboundMessage(
            channel_name="slack",
            chat_id="C123",
            user_id="U-platform",
            owner_user_id="real-user-from-old-binding",
            text="hi",
        )

        _, _, run_context = manager._resolve_run_params(msg, "thread-1")

        assert run_context["user_id"] == AUTH_DISABLED_USER_ID
        assert run_context["channel_user_id"] == "U-platform"

    def test_unbound_channel_messages_keep_platform_user_id_when_auth_is_enabled(self, monkeypatch):
        from app.channels.manager import _owner_headers

        manager = self._manager()
        monkeypatch.delenv("DEER_FLOW_AUTH_DISABLED", raising=False)
        msg = InboundMessage(channel_name="slack", chat_id="C123", user_id="U-platform", text="hi")

        _, _, run_context = manager._resolve_run_params(msg, "thread-1")

        assert run_context["user_id"] == "U-platform"
        assert run_context["channel_user_id"] == "U-platform"
        assert _owner_headers(msg) is None

    def test_unsafe_user_id_is_normalized_but_raw_preserved(self, monkeypatch):
        from deerflow.config.paths import make_safe_user_id

        manager = self._manager()
        monkeypatch.delenv("DEER_FLOW_AUTH_DISABLED", raising=False)
        raw = "user@example.com"
        msg = InboundMessage(channel_name="feishu", chat_id="c", user_id=raw, text="hi")

        _, _, run_context = manager._resolve_run_params(msg, "thread-1")

        assert run_context["user_id"] == make_safe_user_id(raw)
        assert run_context["user_id"] != raw
        assert run_context["channel_user_id"] == raw

    def test_unsafe_user_id_migrates_unique_legacy_bucket(self, tmp_path, monkeypatch):
        from deerflow.config.paths import Paths, make_safe_user_id

        paths = Paths(tmp_path)
        legacy_dir = paths.base_dir / "users" / "user-example-com-63a710569261a24b"
        legacy_dir.mkdir(parents=True)
        (legacy_dir / "memory.json").write_text('{"legacy": true}\n', encoding="utf-8")
        monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: paths)

        manager = self._manager()
        monkeypatch.delenv("DEER_FLOW_AUTH_DISABLED", raising=False)
        raw = "user@example.com"
        msg = InboundMessage(channel_name="feishu", chat_id="c", user_id=raw, text="hi")

        _, _, run_context = manager._resolve_run_params(msg, "thread-1")

        safe = make_safe_user_id(raw)
        assert run_context["user_id"] == safe
        assert paths.user_dir(safe).exists()
        assert not legacy_dir.exists()
        assert (paths.user_dir(safe) / "memory.json").read_text(encoding="utf-8") == '{"legacy": true}\n'

    @pytest.mark.parametrize("raw_user_id", ["", None])
    def test_empty_or_none_user_id_is_not_injected(self, raw_user_id, monkeypatch):
        manager = self._manager()
        monkeypatch.delenv("DEER_FLOW_AUTH_DISABLED", raising=False)
        msg = InboundMessage(channel_name="feishu", chat_id="c", user_id=raw_user_id, text="hi")

        _, _, run_context = manager._resolve_run_params(msg, "thread-1")

        assert "user_id" not in run_context
        assert "channel_user_id" not in run_context


class TestGithubFireAndForget:
    """Regression for the ``httpx.ReadTimeout`` on long autonomous GitHub runs.

    The GitHub channel's outbound ``send`` is log-only by design — the agent
    posts to the issue/PR via the ``gh`` CLI from inside the sandbox. Keeping
    ``client.runs.wait`` on the manager side kept an HTTP stream open for the
    entire run lifetime, so any run that legitimately exceeded the SDK default
    300s read deadline (a routine clone → edit → test → push → PR cycle) blew
    up with ``httpx.ReadTimeout`` and the outer except branch then released the
    dedupe key and emitted a false "internal error" outbound.

    The fix is policy-driven: ``ChannelRunPolicy.fire_and_forget=True`` swaps
    the dispatch call to ``runs.create`` (short POST, returns once the run is
    ``pending``) and skips the response-extraction + outbound-publish block.
    """

    def test_channel_run_policy_default_is_not_fire_and_forget(self):
        """Adding ``fire_and_forget`` must not silently re-route any existing
        channel onto the new path — the default has to stay False so Slack,
        Telegram, Discord, etc. keep using ``runs.wait`` exactly as before."""
        from app.channels.run_policy import ChannelRunPolicy

        assert ChannelRunPolicy().fire_and_forget is False
        assert ChannelRunPolicy().serialize_thread_runs is False

    def test_feishu_channel_policy_opts_into_serialized_thread_runs(self):
        """Feishu's queue-same-thread behavior should be policy-driven."""
        import app.channels.feishu_run_policy  # noqa: F401
        from app.channels.run_policy import CHANNEL_RUN_POLICY

        feishu_policy = CHANNEL_RUN_POLICY.get("feishu")
        assert feishu_policy is not None
        assert feishu_policy.serialize_thread_runs is True

    def test_github_channel_policy_opts_into_fire_and_forget(self):
        """The GitHub channel must register ``fire_and_forget=True``. This is
        the only signal the manager has to skip ``runs.wait`` for github."""
        # Importing the github subpackage registers the policy as a side
        # effect (``register_policy()`` runs at module import time).
        import app.gateway.github.run_policy  # noqa: F401
        from app.channels.run_policy import CHANNEL_RUN_POLICY

        github_policy = CHANNEL_RUN_POLICY.get("github")
        assert github_policy is not None
        assert github_policy.fire_and_forget is True

    def test_handle_chat_for_github_calls_runs_create_not_wait(self):
        """The hot path: a github inbound dispatches via ``runs.create``, not
        ``runs.wait``. ``runs.create`` returns once the run is ``pending`` so
        the manager doesn't have to hold an HTTP stream open for ~6 minutes."""
        import app.gateway.github.run_policy  # noqa: F401 — register policy
        from app.channels.manager import ChannelManager

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            # GitHub deliveries skip the bound-identity gate (authenticity is
            # enforced at the webhook route by HMAC), but constructing the
            # manager with the default require_bound_identity=False keeps the
            # test focused on the dispatch path rather than the gate.
            manager = ChannelManager(bus=bus, store=store)

            mock_client = _make_mock_langgraph_client(thread_id="gh-thread-1")
            # Wire runs.create as an AsyncMock — _make_mock_langgraph_client
            # only wires runs.wait. Returning the same {"thread_id": ...} dict
            # mirrors what the real SDK returns from POST /threads/{id}/runs.
            mock_client.runs.create = AsyncMock(return_value={"run_id": "run-abc", "status": "pending"})
            manager._client = mock_client

            await manager._handle_chat(
                InboundMessage(
                    channel_name="github",
                    chat_id="zhfeng/llm-gateway",
                    user_id="zhfeng",
                    owner_user_id="agent-owner-1",
                    text="please fix the bug in foo.py",
                )
            )

            mock_client.runs.create.assert_called_once()
            # And — crucially — ``runs.wait`` must NOT have been called. Any
            # regression that keeps the long-poll alive for github would
            # immediately re-introduce the ``httpx.ReadTimeout`` symptom.
            mock_client.runs.wait.assert_not_called()

            create_args = mock_client.runs.create.call_args
            assert create_args[0][0] == "gh-thread-1"  # thread_id
            assert create_args[0][1] == "lead_agent"  # assistant_id
            # multitask_strategy must still be ``reject`` — concurrent runs on
            # the same GitHub thread are surfaced via ConflictError below.
            assert create_args[1]["multitask_strategy"] == "reject"

        _run(go())

    def test_handle_chat_for_github_does_not_publish_outbound(self):
        """Fire-and-forget channels publish nothing on success. The GitHub
        agent posts to the issue/PR itself via the ``gh`` CLI; if the manager
        ALSO published an outbound, the channel's log-only ``send`` would
        write a final-state message into ``gateway.log`` for every run and
        muddy the operator-facing logs. The streaming-path counterpart of
        this guarantee already holds — this pins the non-streaming side."""
        import app.gateway.github.run_policy  # noqa: F401 — register policy
        from app.channels.manager import ChannelManager

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(bus=bus, store=store)

            outbound_received: list[OutboundMessage] = []

            async def capture_outbound(msg):
                outbound_received.append(msg)

            bus.subscribe_outbound(capture_outbound)

            mock_client = _make_mock_langgraph_client(thread_id="gh-thread-2")
            mock_client.runs.create = AsyncMock(return_value={"run_id": "run-xyz", "status": "pending"})
            manager._client = mock_client

            await manager.start()
            try:
                await manager._handle_chat(
                    InboundMessage(
                        channel_name="github",
                        chat_id="zhfeng/llm-gateway",
                        user_id="zhfeng",
                        owner_user_id="agent-owner-1",
                        text="please add a test for the empty case",
                    )
                )
                # Give the bus a chance to flush anything that might have
                # been published. Nothing should arrive — but if a future
                # regression starts publishing again we want this test to see
                # it, not race against it.
                await asyncio.sleep(0.05)
            finally:
                await manager.stop()

            assert outbound_received == []
            mock_client.runs.create.assert_called_once()
            mock_client.runs.wait.assert_not_called()

        _run(go())

    def test_handle_chat_for_github_busy_thread_still_emits_busy_message(self):
        """A ``ConflictError`` from ``runs.create`` (the runtime rejected the
        run because a previous one on the same thread is still active) must
        still trip the ``THREAD_BUSY_MESSAGE`` outbound path. The GitHub
        channel's ``send`` is log-only, so in practice the operator sees the
        busy message in ``gateway.log`` rather than on the PR — but the manager
        must treat this exactly like the ``runs.wait`` case so any future
        non-github fire-and-forget channel inherits the behavior unchanged."""
        import httpx
        from langgraph_sdk.errors import ConflictError

        import app.gateway.github.run_policy  # noqa: F401 — register policy
        from app.channels.manager import THREAD_BUSY_MESSAGE, ChannelManager

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(bus=bus, store=store)

            outbound_received: list[OutboundMessage] = []

            async def capture_outbound(msg):
                outbound_received.append(msg)

            bus.subscribe_outbound(capture_outbound)

            request = httpx.Request("POST", "http://127.0.0.1:2024/threads/gh-thread-3/runs")
            response = httpx.Response(409, request=request)
            conflict = ConflictError(
                "Thread is already running a task. Wait for it to finish or choose a different multitask strategy.",
                response=response,
                body={"message": "Thread is already running a task."},
            )

            mock_client = _make_mock_langgraph_client(thread_id="gh-thread-3")
            mock_client.runs.create = AsyncMock(side_effect=conflict)
            manager._client = mock_client

            await manager.start()
            try:
                await manager._handle_chat(
                    InboundMessage(
                        channel_name="github",
                        chat_id="zhfeng/llm-gateway",
                        user_id="zhfeng",
                        owner_user_id="agent-owner-1",
                        text="ping",
                    )
                )
                await _wait_for(lambda: any(m.text == THREAD_BUSY_MESSAGE for m in outbound_received))
            finally:
                await manager.stop()

            busy = [m for m in outbound_received if m.text == THREAD_BUSY_MESSAGE]
            assert len(busy) == 1
            assert busy[0].channel_name == "github"
            mock_client.runs.create.assert_called_once()
            mock_client.runs.wait.assert_not_called()

        _run(go())

    def test_handle_chat_for_non_fire_and_forget_channel_still_uses_runs_wait(self):
        """Regression guard for the non-github channels (Slack, DingTalk,
        WeCom, etc.) — they still need the manager to ferry the final
        assistant message back, so the ``runs.wait`` dispatch path must stay
        intact when ``fire_and_forget`` is False or the channel has no policy
        entry at all."""
        from app.channels.manager import ChannelManager

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(bus=bus, store=store)

            mock_client = _make_mock_langgraph_client(thread_id="slack-thread-1")
            # runs.create is wired so we can prove it is NOT used for slack.
            mock_client.runs.create = AsyncMock(return_value={"run_id": "should-not-be-used"})
            manager._client = mock_client

            await manager._handle_chat(
                InboundMessage(
                    channel_name="slack",
                    chat_id="C1",
                    user_id="U1",
                    text="hi",
                )
            )

            mock_client.runs.wait.assert_called_once()
            mock_client.runs.create.assert_not_called()

        _run(go())


class _BoundIdentityRepo:
    def __init__(self, connections: list[dict[str, str | None]] | None = None) -> None:
        self.connections = list(connections or [])
        self.lookups: list[dict[str, str | None]] = []
        self.thread_sets: list[dict[str, str | None]] = []

    async def find_connection_by_external_identity(self, *, provider: str, external_account_id: str, workspace_id: str | None = None):
        self.lookups.append(
            {
                "provider": provider,
                "external_account_id": external_account_id,
                "workspace_id": workspace_id,
            }
        )
        for connection in self.connections:
            if connection.get("provider") == provider and connection.get("external_account_id") == external_account_id and connection.get("workspace_id") == workspace_id:
                return connection
        return None

    async def get_thread_id(self, connection_id: str, chat_id: str, topic_id: str | None = None):
        return None

    async def set_thread_id(
        self,
        *,
        connection_id: str,
        owner_user_id: str,
        provider: str,
        external_conversation_id: str,
        external_topic_id: str | None,
        thread_id: str,
    ) -> None:
        self.thread_sets.append(
            {
                "connection_id": connection_id,
                "owner_user_id": owner_user_id,
                "provider": provider,
                "external_conversation_id": external_conversation_id,
                "external_topic_id": external_topic_id,
                "thread_id": thread_id,
            }
        )


class TestChannelManagerBoundIdentityPolicy:
    def test_unbound_auth_enabled_chat_is_rejected_before_thread_or_run_creation(self, monkeypatch):
        from app.channels.manager import BOUND_IDENTITY_REQUIRED_MESSAGE, ChannelManager

        monkeypatch.delenv("DEER_FLOW_AUTH_DISABLED", raising=False)

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(bus=bus, store=store, require_bound_identity=True)
            mock_client = _make_mock_langgraph_client()
            manager._client = mock_client
            outbound_received = []

            async def capture(msg):
                outbound_received.append(msg)

            bus.subscribe_outbound(capture)
            await manager._handle_chat(
                InboundMessage(
                    channel_name="slack",
                    chat_id="C123",
                    user_id="U-platform",
                    text="hi",
                    thread_ts="1710000000.000100",
                )
            )

            assert len(outbound_received) == 1
            assert outbound_received[0].text == BOUND_IDENTITY_REQUIRED_MESSAGE
            assert outbound_received[0].thread_id == ""
            assert outbound_received[0].connection_id is None
            assert outbound_received[0].owner_user_id is None
            mock_client.threads.create.assert_not_called()
            mock_client.runs.wait.assert_not_called()

        _run(go())

    def test_bound_identity_repo_unavailable_uses_transient_failure_message(self, monkeypatch):
        from app.channels.manager import BOUND_IDENTITY_UNAVAILABLE_MESSAGE, ChannelManager

        monkeypatch.delenv("DEER_FLOW_AUTH_DISABLED", raising=False)

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(bus=bus, store=store, require_bound_identity=True)
            mock_client = _make_mock_langgraph_client()
            manager._client = mock_client
            outbound_received = []

            async def capture(msg):
                outbound_received.append(msg)

            bus.subscribe_outbound(capture)
            await manager._handle_chat(
                InboundMessage(
                    channel_name="slack",
                    chat_id="C123",
                    user_id="U-platform",
                    owner_user_id="deerflow-user-1",
                    connection_id="connection-1",
                    workspace_id="T123",
                    text="hi",
                )
            )

            assert len(outbound_received) == 1
            assert outbound_received[0].text == BOUND_IDENTITY_UNAVAILABLE_MESSAGE
            assert outbound_received[0].connection_id is None
            assert outbound_received[0].owner_user_id is None
            mock_client.threads.create.assert_not_called()
            mock_client.runs.wait.assert_not_called()

        _run(go())

    def test_unbound_auth_enabled_chat_is_rejected_before_semaphore(self, monkeypatch):
        from app.channels.manager import BOUND_IDENTITY_REQUIRED_MESSAGE, ChannelManager

        monkeypatch.delenv("DEER_FLOW_AUTH_DISABLED", raising=False)

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(bus=bus, store=store, require_bound_identity=True)
            outbound_received = []

            async def capture(msg):
                outbound_received.append(msg)

            bus.subscribe_outbound(capture)
            await manager.start()
            assert manager._semaphore is not None
            await manager._semaphore.acquire()
            try:
                await asyncio.wait_for(
                    manager._handle_message(
                        InboundMessage(
                            channel_name="slack",
                            chat_id="C123",
                            user_id="U-platform",
                            text="hi",
                        )
                    ),
                    timeout=0.5,
                )
            finally:
                manager._semaphore.release()
                await manager.stop()

            assert len(outbound_received) == 1
            assert outbound_received[0].text == BOUND_IDENTITY_REQUIRED_MESSAGE
            assert outbound_received[0].connection_id is None
            assert outbound_received[0].owner_user_id is None

        _run(go())

    def test_bound_auth_enabled_chat_is_allowed_when_bound_identity_is_required(self, monkeypatch):
        from app.channels.manager import ChannelManager

        monkeypatch.delenv("DEER_FLOW_AUTH_DISABLED", raising=False)

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            repo = _BoundIdentityRepo(
                [
                    {
                        "id": "connection-1",
                        "owner_user_id": "deerflow-user-1",
                        "provider": "slack",
                        "external_account_id": "U-platform",
                        "workspace_id": "T123",
                    }
                ]
            )
            manager = ChannelManager(bus=bus, store=store, connection_repo=repo, require_bound_identity=True)
            mock_client = _make_mock_langgraph_client(thread_id="thread-bound")
            manager._client = mock_client

            await manager._handle_chat(
                InboundMessage(
                    channel_name="slack",
                    chat_id="C123",
                    user_id="U-platform",
                    owner_user_id="deerflow-user-1",
                    connection_id="connection-1",
                    workspace_id="T123",
                    text="hi",
                )
            )

            mock_client.threads.create.assert_called_once()
            mock_client.runs.wait.assert_called_once()
            run_context = mock_client.runs.wait.call_args.kwargs["context"]
            assert run_context["user_id"] == "deerflow-user-1"
            assert run_context["channel_user_id"] == "U-platform"

        _run(go())

    def test_bound_auth_enabled_message_checks_bound_identity_once_on_hot_path(self, monkeypatch):
        from app.channels.manager import ChannelManager

        monkeypatch.delenv("DEER_FLOW_AUTH_DISABLED", raising=False)

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            repo = _BoundIdentityRepo(
                [
                    {
                        "id": "connection-1",
                        "owner_user_id": "deerflow-user-1",
                        "provider": "slack",
                        "external_account_id": "U-platform",
                        "workspace_id": "T123",
                    }
                ]
            )
            manager = ChannelManager(bus=bus, store=store, connection_repo=repo, require_bound_identity=True)
            mock_client = _make_mock_langgraph_client(thread_id="thread-bound")
            manager._client = mock_client
            await manager.start()
            try:
                await manager._handle_message(
                    InboundMessage(
                        channel_name="slack",
                        chat_id="C123",
                        user_id="U-platform",
                        owner_user_id="deerflow-user-1",
                        connection_id="connection-1",
                        workspace_id="T123",
                        text="hi",
                    )
                )
            finally:
                await manager.stop()

            assert repo.lookups == [
                {
                    "provider": "slack",
                    "external_account_id": "U-platform",
                    "workspace_id": "T123",
                }
            ]
            mock_client.threads.create.assert_called_once()
            mock_client.runs.wait.assert_called_once()

        _run(go())

    def test_auth_enabled_chat_rejects_unverified_bound_identity(self, monkeypatch):
        from app.channels.manager import BOUND_IDENTITY_REQUIRED_MESSAGE, ChannelManager

        monkeypatch.delenv("DEER_FLOW_AUTH_DISABLED", raising=False)

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            repo = _BoundIdentityRepo(
                [
                    {
                        "id": "actual-connection",
                        "owner_user_id": "actual-owner",
                        "provider": "slack",
                        "external_account_id": "U-platform",
                        "workspace_id": None,
                    }
                ]
            )
            manager = ChannelManager(bus=bus, store=store, connection_repo=repo, require_bound_identity=True)
            mock_client = _make_mock_langgraph_client()
            manager._client = mock_client
            outbound_received = []

            async def capture(msg):
                outbound_received.append(msg)

            bus.subscribe_outbound(capture)
            await manager._handle_chat(
                InboundMessage(
                    channel_name="slack",
                    chat_id="C123",
                    user_id="U-platform",
                    owner_user_id="forged-owner",
                    connection_id="forged-connection",
                    text="hi",
                )
            )

            assert len(outbound_received) == 1
            assert outbound_received[0].text == BOUND_IDENTITY_REQUIRED_MESSAGE
            assert outbound_received[0].connection_id == "actual-connection"
            assert outbound_received[0].owner_user_id == "actual-owner"
            mock_client.threads.create.assert_not_called()
            mock_client.runs.wait.assert_not_called()

        _run(go())

    def test_auth_disabled_chat_keeps_default_user_when_bound_identity_is_required(self, monkeypatch):
        from app.channels.manager import ChannelManager
        from app.gateway.auth_disabled import AUTH_DISABLED_USER_ID

        monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "1")

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(bus=bus, store=store, require_bound_identity=True)
            mock_client = _make_mock_langgraph_client(thread_id="thread-local")
            manager._client = mock_client

            await manager._handle_chat(
                InboundMessage(
                    channel_name="slack",
                    chat_id="C123",
                    user_id="U-platform",
                    text="hi",
                )
            )

            mock_client.threads.create.assert_called_once()
            mock_client.runs.wait.assert_called_once()
            run_context = mock_client.runs.wait.call_args.kwargs["context"]
            assert run_context["user_id"] == AUTH_DISABLED_USER_ID
            assert run_context["channel_user_id"] == "U-platform"

        _run(go())

    def test_legacy_open_bot_mode_allows_unbound_auth_enabled_chat(self, monkeypatch):
        from app.channels.manager import ChannelManager

        monkeypatch.delenv("DEER_FLOW_AUTH_DISABLED", raising=False)

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(bus=bus, store=store, require_bound_identity=False)
            mock_client = _make_mock_langgraph_client(thread_id="thread-legacy")
            manager._client = mock_client

            await manager._handle_chat(
                InboundMessage(
                    channel_name="slack",
                    chat_id="C123",
                    user_id="U-platform",
                    text="hi",
                )
            )

            mock_client.threads.create.assert_called_once()
            mock_client.runs.wait.assert_called_once()
            run_context = mock_client.runs.wait.call_args.kwargs["context"]
            assert run_context["user_id"] == "U-platform"
            assert run_context["channel_user_id"] == "U-platform"

        _run(go())

    def test_unbound_auth_enabled_new_command_is_rejected_before_thread_creation(self, monkeypatch):
        from app.channels.manager import BOUND_IDENTITY_REQUIRED_MESSAGE, ChannelManager

        monkeypatch.delenv("DEER_FLOW_AUTH_DISABLED", raising=False)

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(bus=bus, store=store, require_bound_identity=True)
            mock_client = _make_mock_langgraph_client()
            manager._client = mock_client
            outbound_received = []

            async def capture(msg):
                outbound_received.append(msg)

            bus.subscribe_outbound(capture)
            await manager._handle_command(
                InboundMessage(
                    channel_name="slack",
                    chat_id="C123",
                    user_id="U-platform",
                    text="/new",
                    msg_type=InboundMessageType.COMMAND,
                    thread_ts="1710000000.000100",
                )
            )

            assert len(outbound_received) == 1
            assert outbound_received[0].text == BOUND_IDENTITY_REQUIRED_MESSAGE
            assert outbound_received[0].thread_id == ""
            assert outbound_received[0].connection_id is None
            assert outbound_received[0].owner_user_id is None
            mock_client.threads.create.assert_not_called()

        _run(go())

    def test_bound_auth_enabled_new_command_creates_thread(self, monkeypatch):
        from app.channels.manager import ChannelManager

        monkeypatch.delenv("DEER_FLOW_AUTH_DISABLED", raising=False)

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            repo = _BoundIdentityRepo(
                [
                    {
                        "id": "connection-1",
                        "owner_user_id": "deerflow-user-1",
                        "provider": "slack",
                        "external_account_id": "U-platform",
                        "workspace_id": "T123",
                    }
                ]
            )
            manager = ChannelManager(bus=bus, store=store, connection_repo=repo, require_bound_identity=True)
            mock_client = _make_mock_langgraph_client(thread_id="thread-bound")
            manager._client = mock_client

            await manager._handle_command(
                InboundMessage(
                    channel_name="slack",
                    chat_id="C123",
                    user_id="U-platform",
                    owner_user_id="deerflow-user-1",
                    connection_id="connection-1",
                    workspace_id="T123",
                    text="/new",
                    msg_type=InboundMessageType.COMMAND,
                )
            )

            mock_client.threads.create.assert_called_once()

        _run(go())

    def test_webhook_channel_run_policy_opts_out_of_bound_identity_gate(self, monkeypatch):
        """A channel whose ChannelRunPolicy declares ``requires_bound_identity=False``
        is exempt from the per-sender bound-identity gate, even when
        ``require_bound_identity=True`` is on for interactive IM channels in the
        same deployment. This is what lets GitHub webhook deliveries reach the
        agent: they are HMAC-authenticated at the route, and the sender→DeerFlow
        binding lives in the agent's config.yaml ownership, not in the
        channel-connections table.
        """
        from app.channels.manager import ChannelManager
        from app.channels.run_policy import CHANNEL_RUN_POLICY, ChannelRunPolicy

        monkeypatch.delenv("DEER_FLOW_AUTH_DISABLED", raising=False)

        # Save+restore so test parallelism / re-import side effects from
        # app.gateway.github.run_policy don't leak across tests.
        original = CHANNEL_RUN_POLICY.get("webhook-fixture")
        CHANNEL_RUN_POLICY["webhook-fixture"] = ChannelRunPolicy(
            is_interactive=False,
            requires_bound_identity=False,
        )
        try:

            async def go():
                bus = MessageBus()
                store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
                manager = ChannelManager(bus=bus, store=store, require_bound_identity=True)
                mock_client = _make_mock_langgraph_client(thread_id="thread-webhook")
                manager._client = mock_client

                await manager._handle_chat(
                    InboundMessage(
                        channel_name="webhook-fixture",
                        chat_id="repo-owner/repo-name",
                        user_id="commenter-login",
                        # owner_user_id is set by the dispatcher from the
                        # agent binding, NOT from a channel-connection row.
                        owner_user_id="agent-installer-user",
                        text="hi",
                    )
                )

                # If the gate fired, threads.create would never be called and
                # one outbound rejection would be on the bus instead. We
                # assert the agent path ran.
                mock_client.threads.create.assert_called_once()
                mock_client.runs.wait.assert_called_once()

            _run(go())
        finally:
            if original is None:
                CHANNEL_RUN_POLICY.pop("webhook-fixture", None)
            else:
                CHANNEL_RUN_POLICY["webhook-fixture"] = original


class TestChannelManagerConnectionRouting:
    def test_connection_scoped_conversations_do_not_share_threads(self, tmp_path, monkeypatch):
        from app.channels.manager import ChannelManager
        from app.gateway.internal_auth import INTERNAL_OWNER_USER_ID_HEADER_NAME
        from deerflow.persistence.engine import close_engine

        monkeypatch.delenv("DEER_FLOW_AUTH_DISABLED", raising=False)

        async def go():
            repo = await _make_channel_connection_repo(tmp_path)
            alice = await repo.upsert_connection(
                owner_user_id="alice",
                provider="slack",
                external_account_id="U-alice",
                workspace_id="T1",
            )
            bob = await repo.upsert_connection(
                owner_user_id="bob",
                provider="slack",
                external_account_id="U-bob",
                workspace_id="T1",
            )

            bus = MessageBus()
            store = ChannelStore(path=tmp_path / "legacy-store.json")
            manager = ChannelManager(bus=bus, store=store, connection_repo=repo)
            mock_client = _make_mock_langgraph_client()
            mock_client.threads.create = AsyncMock(
                side_effect=[
                    {"thread_id": "thread-alice"},
                    {"thread_id": "thread-bob"},
                ]
            )
            manager._client = mock_client

            await manager._handle_chat(
                InboundMessage(
                    channel_name="slack",
                    chat_id="C-shared",
                    user_id="U-alice",
                    owner_user_id="alice",
                    connection_id=alice["id"],
                    text="hello",
                    thread_ts="1710000000.000100",
                    topic_id="1710000000.000100",
                )
            )
            await manager._handle_chat(
                InboundMessage(
                    channel_name="slack",
                    chat_id="C-shared",
                    user_id="U-bob",
                    owner_user_id="bob",
                    connection_id=bob["id"],
                    text="hello",
                    thread_ts="1710000000.000100",
                    topic_id="1710000000.000100",
                )
            )

            assert await repo.get_thread_id(alice["id"], "C-shared", "1710000000.000100") == "thread-alice"
            assert await repo.get_thread_id(bob["id"], "C-shared", "1710000000.000100") == "thread-bob"
            assert store.list_entries() == []

            first_context = mock_client.runs.wait.call_args_list[0].kwargs["context"]
            second_context = mock_client.runs.wait.call_args_list[1].kwargs["context"]
            assert first_context["user_id"] == "alice"
            assert first_context["channel_user_id"] == "U-alice"
            assert second_context["user_id"] == "bob"
            assert second_context["channel_user_id"] == "U-bob"

            first_create_headers = mock_client.threads.create.call_args_list[0].kwargs["headers"]
            second_create_headers = mock_client.threads.create.call_args_list[1].kwargs["headers"]
            assert first_create_headers[INTERNAL_OWNER_USER_ID_HEADER_NAME] == "alice"
            assert second_create_headers[INTERNAL_OWNER_USER_ID_HEADER_NAME] == "bob"

            first_run_headers = mock_client.runs.wait.call_args_list[0].kwargs["headers"]
            second_run_headers = mock_client.runs.wait.call_args_list[1].kwargs["headers"]
            assert first_run_headers[INTERNAL_OWNER_USER_ID_HEADER_NAME] == "alice"
            assert second_run_headers[INTERNAL_OWNER_USER_ID_HEADER_NAME] == "bob"

        try:
            _run(go())
        finally:
            _run(close_engine())


# ---------------------------------------------------------------------------
# ChannelService tests
# ---------------------------------------------------------------------------


class TestExtractArtifacts:
    def test_extracts_from_present_files_tool_call(self):
        from app.channels.manager import _extract_artifacts

        result = {
            "messages": [
                {"type": "human", "content": "generate report"},
                {
                    "type": "ai",
                    "content": "Here is your report.",
                    "tool_calls": [
                        {"name": "present_files", "args": {"filepaths": ["/mnt/user-data/outputs/report.md"]}},
                    ],
                },
                {"type": "tool", "name": "present_files", "content": "Successfully presented files"},
            ]
        }
        assert _extract_artifacts(result) == ["/mnt/user-data/outputs/report.md"]

    def test_empty_when_no_present_files(self):
        from app.channels.manager import _extract_artifacts

        result = {
            "messages": [
                {"type": "human", "content": "hello"},
                {"type": "ai", "content": "hello"},
            ]
        }
        assert _extract_artifacts(result) == []

    def test_empty_for_list_result_no_tool_calls(self):
        from app.channels.manager import _extract_artifacts

        result = [{"type": "ai", "content": "hello"}]
        assert _extract_artifacts(result) == []

    def test_only_extracts_after_last_human_message(self):
        """Artifacts from previous turns (before the last human message) should be ignored."""
        from app.channels.manager import _extract_artifacts

        result = {
            "messages": [
                {"type": "human", "content": "make report"},
                {
                    "type": "ai",
                    "content": "Created report.",
                    "tool_calls": [
                        {"name": "present_files", "args": {"filepaths": ["/mnt/user-data/outputs/report.md"]}},
                    ],
                },
                {"type": "tool", "name": "present_files", "content": "ok"},
                {"type": "human", "content": "add chart"},
                {
                    "type": "ai",
                    "content": "Created chart.",
                    "tool_calls": [
                        {"name": "present_files", "args": {"filepaths": ["/mnt/user-data/outputs/chart.png"]}},
                    ],
                },
                {"type": "tool", "name": "present_files", "content": "ok"},
            ]
        }
        # Should only return chart.png (from the last turn)
        assert _extract_artifacts(result) == ["/mnt/user-data/outputs/chart.png"]

    def test_multiple_files_in_single_call(self):
        from app.channels.manager import _extract_artifacts

        result = {
            "messages": [
                {"type": "human", "content": "export"},
                {
                    "type": "ai",
                    "content": "Done.",
                    "tool_calls": [
                        {"name": "present_files", "args": {"filepaths": ["/mnt/user-data/outputs/a.txt", "/mnt/user-data/outputs/b.csv"]}},
                    ],
                },
            ]
        }
        assert _extract_artifacts(result) == ["/mnt/user-data/outputs/a.txt", "/mnt/user-data/outputs/b.csv"]

    def test_ignores_hidden_human_control_messages(self):
        """Hidden control messages should not hide current-turn present_files artifacts."""
        from app.channels.manager import _extract_artifacts

        result = {
            "messages": [
                {"type": "human", "content": "export"},
                {
                    "type": "ai",
                    "content": "Done.",
                    "tool_calls": [
                        {"name": "present_files", "args": {"filepaths": ["/mnt/user-data/outputs/plan.md"]}},
                    ],
                },
                {
                    "type": "human",
                    "name": "todo_completion_reminder",
                    "content": "mark tasks complete",
                    "additional_kwargs": {"hide_from_ui": True},
                },
            ]
        }

        assert _extract_artifacts(result) == ["/mnt/user-data/outputs/plan.md"]


class TestFormatArtifactText:
    def test_single_artifact(self):
        from app.channels.manager import _format_artifact_text

        text = _format_artifact_text(["/mnt/user-data/outputs/report.md"])
        assert text == "Created File: 📎 report.md"

    def test_multiple_artifacts(self):
        from app.channels.manager import _format_artifact_text

        text = _format_artifact_text(
            ["/mnt/user-data/outputs/a.txt", "/mnt/user-data/outputs/b.csv"],
        )
        assert text == "Created Files: 📎 a.txt、b.csv"


class TestHandleChatWithArtifacts:
    def test_bound_owner_artifacts_resolve_from_owner_outputs_bucket(self, tmp_path, monkeypatch):
        from app.channels.manager import ChannelManager
        from deerflow.config.paths import Paths

        paths = Paths(tmp_path)
        monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: paths)
        outputs_dir = paths.sandbox_outputs_dir("test-thread-123", user_id="owner-1")
        outputs_dir.mkdir(parents=True)
        (outputs_dir / "report.md").write_text("owner report", encoding="utf-8")

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=tmp_path / "store.json")
            manager = ChannelManager(bus=bus, store=store)

            run_result = {
                "messages": [
                    {"type": "human", "content": "generate report"},
                    {
                        "type": "ai",
                        "content": "Here is your report.",
                        "tool_calls": [
                            {"name": "present_files", "args": {"filepaths": ["/mnt/user-data/outputs/report.md"]}},
                        ],
                    },
                    {"type": "tool", "name": "present_files", "content": "ok"},
                ],
            }
            mock_client = _make_mock_langgraph_client(run_result=run_result)
            manager._client = mock_client

            outbound_received = []
            bus.subscribe_outbound(lambda msg: outbound_received.append(msg))
            await manager.start()

            await bus.publish_inbound(
                InboundMessage(
                    channel_name="test",
                    chat_id="c1",
                    user_id="U-platform",
                    owner_user_id="owner-1",
                    connection_id="connection-1",
                    text="generate report",
                )
            )
            await _wait_for(lambda: len(outbound_received) >= 1)
            await manager.stop()

            assert len(outbound_received) == 1
            assert len(outbound_received[0].attachments) == 1
            assert outbound_received[0].attachments[0].actual_path == outputs_dir / "report.md"

        _run(go())

    def test_artifacts_appended_to_text(self):
        from app.channels.manager import ChannelManager

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(bus=bus, store=store)

            run_result = {
                "messages": [
                    {"type": "human", "content": "generate report"},
                    {
                        "type": "ai",
                        "content": "Here is your report.",
                        "tool_calls": [
                            {"name": "present_files", "args": {"filepaths": ["/mnt/user-data/outputs/report.md"]}},
                        ],
                    },
                    {"type": "tool", "name": "present_files", "content": "ok"},
                ],
            }
            mock_client = _make_mock_langgraph_client(run_result=run_result)
            manager._client = mock_client

            outbound_received = []
            bus.subscribe_outbound(lambda msg: outbound_received.append(msg))
            await manager.start()

            await bus.publish_inbound(
                InboundMessage(
                    channel_name="test",
                    chat_id="c1",
                    user_id="u1",
                    text="generate report",
                )
            )
            await _wait_for(lambda: len(outbound_received) >= 1)
            await manager.stop()

            assert len(outbound_received) == 1
            assert "Here is your report." in outbound_received[0].text
            assert "report.md" in outbound_received[0].text
            assert outbound_received[0].artifacts == ["/mnt/user-data/outputs/report.md"]

        _run(go())

    def test_artifacts_only_no_text(self):
        """When agent produces artifacts but no text, the artifacts should be the response."""
        from app.channels.manager import ChannelManager

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(bus=bus, store=store)

            run_result = {
                "messages": [
                    {"type": "human", "content": "export data"},
                    {
                        "type": "ai",
                        "content": "",
                        "tool_calls": [
                            {"name": "present_files", "args": {"filepaths": ["/mnt/user-data/outputs/output.csv"]}},
                        ],
                    },
                    {"type": "tool", "name": "present_files", "content": "ok"},
                ],
            }
            mock_client = _make_mock_langgraph_client(run_result=run_result)
            manager._client = mock_client

            outbound_received = []
            bus.subscribe_outbound(lambda msg: outbound_received.append(msg))
            await manager.start()

            await bus.publish_inbound(
                InboundMessage(
                    channel_name="test",
                    chat_id="c1",
                    user_id="u1",
                    text="export data",
                )
            )
            await _wait_for(lambda: len(outbound_received) >= 1)
            await manager.stop()

            assert len(outbound_received) == 1
            # Should NOT be the "(No response from agent)" fallback
            assert outbound_received[0].text != "(No response from agent)"
            assert "output.csv" in outbound_received[0].text
            assert outbound_received[0].artifacts == ["/mnt/user-data/outputs/output.csv"]

        _run(go())

    def test_hidden_human_control_message_does_not_trigger_no_response_fallback(self):
        """Plan-mode hidden control messages should not mask the final AI response."""
        from app.channels.manager import ChannelManager

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(bus=bus, store=store)

            run_result = {
                "messages": [
                    {"type": "human", "content": "make a plan"},
                    {"type": "ai", "content": "Here is a concrete plan."},
                    {
                        "type": "human",
                        "name": "todo_reminder",
                        "content": "sync todos",
                        "additional_kwargs": {"hide_from_ui": True},
                    },
                ]
            }
            mock_client = _make_mock_langgraph_client(run_result=run_result)
            manager._client = mock_client

            outbound_received = []
            bus.subscribe_outbound(lambda msg: outbound_received.append(msg))
            await manager.start()

            await bus.publish_inbound(
                InboundMessage(
                    channel_name="test",
                    chat_id="c1",
                    user_id="u1",
                    text="make a plan",
                )
            )
            await _wait_for(lambda: len(outbound_received) >= 1)
            await manager.stop()

            assert len(outbound_received) == 1
            assert outbound_received[0].text == "Here is a concrete plan."

        _run(go())

    def test_only_last_turn_artifacts_returned(self):
        """Only artifacts from the current turn's present_files calls should be included."""
        from app.channels.manager import ChannelManager

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(bus=bus, store=store)

            # Turn 1: produces report.md
            turn1_result = {
                "messages": [
                    {"type": "human", "content": "make report"},
                    {
                        "type": "ai",
                        "content": "Created report.",
                        "tool_calls": [
                            {"name": "present_files", "args": {"filepaths": ["/mnt/user-data/outputs/report.md"]}},
                        ],
                    },
                    {"type": "tool", "name": "present_files", "content": "ok"},
                ],
            }
            # Turn 2: accumulated messages include turn 1's artifacts, but only chart.png is new
            turn2_result = {
                "messages": [
                    {"type": "human", "content": "make report"},
                    {
                        "type": "ai",
                        "content": "Created report.",
                        "tool_calls": [
                            {"name": "present_files", "args": {"filepaths": ["/mnt/user-data/outputs/report.md"]}},
                        ],
                    },
                    {"type": "tool", "name": "present_files", "content": "ok"},
                    {"type": "human", "content": "add chart"},
                    {
                        "type": "ai",
                        "content": "Created chart.",
                        "tool_calls": [
                            {"name": "present_files", "args": {"filepaths": ["/mnt/user-data/outputs/chart.png"]}},
                        ],
                    },
                    {"type": "tool", "name": "present_files", "content": "ok"},
                ],
            }

            mock_client = _make_mock_langgraph_client(thread_id="thread-dup-test")
            mock_client.runs.wait = AsyncMock(side_effect=[turn1_result, turn2_result])
            manager._client = mock_client

            outbound_received = []
            bus.subscribe_outbound(lambda msg: outbound_received.append(msg))
            await manager.start()

            # Send two messages with the same topic_id (same thread)
            for text in ["make report", "add chart"]:
                msg = InboundMessage(
                    channel_name="test",
                    chat_id="c1",
                    user_id="u1",
                    text=text,
                    topic_id="topic-dup",
                )
                await bus.publish_inbound(msg)

            await _wait_for(lambda: len(outbound_received) >= 2)
            await manager.stop()

            assert len(outbound_received) == 2

            # Turn 1: should include report.md
            assert "report.md" in outbound_received[0].text
            assert outbound_received[0].artifacts == ["/mnt/user-data/outputs/report.md"]

            # Turn 2: should include ONLY chart.png (report.md is from previous turn)
            assert "chart.png" in outbound_received[1].text
            assert "report.md" not in outbound_received[1].text
            assert outbound_received[1].artifacts == ["/mnt/user-data/outputs/chart.png"]

        _run(go())


class TestFeishuChannel:
    def test_prepare_inbound_publishes_without_waiting_for_running_card(self):
        from app.channels.feishu import FeishuChannel

        async def go():
            bus = MessageBus()
            bus.publish_inbound = AsyncMock()
            channel = FeishuChannel(bus, config={})

            reply_started = asyncio.Event()
            release_reply = asyncio.Event()

            async def slow_reply(message_id: str, text: str) -> str:
                reply_started.set()
                await release_reply.wait()
                return "om-running-card"

            channel._add_reaction = AsyncMock()
            channel._reply_card = AsyncMock(side_effect=slow_reply)

            inbound = InboundMessage(
                channel_name="feishu",
                chat_id="chat-1",
                user_id="user-1",
                text="hello",
                thread_ts="om-source-msg",
            )

            prepare_task = asyncio.create_task(channel._prepare_inbound("om-source-msg", inbound))

            await _wait_for(lambda: bus.publish_inbound.await_count == 1)
            await prepare_task

            assert reply_started.is_set()
            assert "om-source-msg" in channel._running_card_tasks
            assert channel._reply_card.await_count == 1

            release_reply.set()
            await _wait_for(lambda: channel._running_card_ids.get("om-source-msg") == "om-running-card")
            await _wait_for(lambda: "om-source-msg" not in channel._running_card_tasks)

        _run(go())

    def test_prepare_inbound_topic_reply_includes_source_preview(self):
        from app.channels.feishu import SOURCE_PREVIEW_METADATA_KEY, FeishuChannel

        async def go():
            bus = MessageBus()
            bus.publish_inbound = AsyncMock()
            channel = FeishuChannel(bus, config={})

            reply_started = asyncio.Event()
            release_reply = asyncio.Event()

            async def slow_reply(message_id: str, text: str) -> str:
                reply_started.set()
                await release_reply.wait()
                return "om-running-card"

            channel._add_reaction = AsyncMock()
            channel._reply_card = AsyncMock(side_effect=slow_reply)

            inbound = InboundMessage(
                channel_name="feishu",
                chat_id="chat-1",
                user_id="user-1",
                text="follow-up question",
                thread_ts="om-source-msg",
                metadata={SOURCE_PREVIEW_METADATA_KEY: "follow-up question"},
            )

            prepare_task = asyncio.create_task(channel._prepare_inbound("om-source-msg", inbound))

            await _wait_for(lambda: bus.publish_inbound.await_count == 1)
            await _wait_for(reply_started.is_set)

            preview_text = channel._reply_card.await_args.args[1]
            assert preview_text == "> follow-up question\n\nthinking..."

            await prepare_task
            release_reply.set()
            await _wait_for(lambda: channel._running_card_ids.get("om-source-msg") == "om-running-card")

        _run(go())

    def test_prepare_inbound_and_send_share_running_card_task(self):
        from app.channels.feishu import FeishuChannel

        async def go():
            bus = MessageBus()
            bus.publish_inbound = AsyncMock()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            channel = FeishuChannel(bus, config={"channel_store": store})
            channel._api_client = MagicMock()

            reply_started = asyncio.Event()
            release_reply = asyncio.Event()

            async def slow_reply(message_id: str, text: str) -> str:
                reply_started.set()
                await release_reply.wait()
                return "om-running-card"

            channel._add_reaction = AsyncMock()
            channel._reply_card = AsyncMock(side_effect=slow_reply)
            channel._update_card = AsyncMock()

            inbound = InboundMessage(
                channel_name="feishu",
                chat_id="chat-1",
                user_id="user-1",
                text="hello",
                thread_ts="om-source-msg",
            )

            prepare_task = asyncio.create_task(channel._prepare_inbound("om-source-msg", inbound))
            await _wait_for(lambda: bus.publish_inbound.await_count == 1)
            await _wait_for(reply_started.is_set)

            send_task = asyncio.create_task(
                channel.send(
                    OutboundMessage(
                        channel_name="feishu",
                        chat_id="chat-1",
                        thread_id="thread-1",
                        text="Hello",
                        is_final=False,
                        thread_ts="om-source-msg",
                        metadata={
                            "user_id": "user-1",
                            "root_id": "om-root-msg",
                            "topic_id": "om-root-msg",
                        },
                    )
                )
            )

            await asyncio.sleep(0)
            assert channel._reply_card.await_count == 1

            release_reply.set()
            await prepare_task
            await send_task

            assert channel._reply_card.await_count == 1
            channel._update_card.assert_awaited_once_with("om-running-card", "Hello")
            assert "om-source-msg" not in channel._running_card_tasks
            assert store.get_thread_id("feishu", "chat-1", topic_id="om-source-msg") == "thread-1"
            assert store.get_thread_id("feishu", "chat-1", topic_id="om-running-card") == "thread-1"
            assert store.get_thread_id("feishu", "chat-1", topic_id="om-root-msg") == "thread-1"

        _run(go())

    def test_streaming_reuses_single_running_card(self):
        from lark_oapi.api.im.v1 import (
            CreateMessageReactionRequest,
            CreateMessageReactionRequestBody,
            Emoji,
            PatchMessageRequest,
            PatchMessageRequestBody,
            ReplyMessageRequest,
            ReplyMessageRequestBody,
        )

        from app.channels.feishu import FeishuChannel

        async def go():
            bus = MessageBus()
            channel = FeishuChannel(bus, config={})

            channel._api_client = MagicMock()
            channel._ReplyMessageRequest = ReplyMessageRequest
            channel._ReplyMessageRequestBody = ReplyMessageRequestBody
            channel._PatchMessageRequest = PatchMessageRequest
            channel._PatchMessageRequestBody = PatchMessageRequestBody
            channel._CreateMessageReactionRequest = CreateMessageReactionRequest
            channel._CreateMessageReactionRequestBody = CreateMessageReactionRequestBody
            channel._Emoji = Emoji

            reply_response = MagicMock()
            reply_response.data.message_id = "om-running-card"
            channel._api_client.im.v1.message.reply = MagicMock(return_value=reply_response)
            channel._api_client.im.v1.message.patch = MagicMock()
            channel._api_client.im.v1.message_reaction.create = MagicMock()

            await channel._send_running_reply("om-source-msg")

            await channel.send(
                OutboundMessage(
                    channel_name="feishu",
                    chat_id="chat-1",
                    thread_id="thread-1",
                    text="Hello",
                    is_final=False,
                    thread_ts="om-source-msg",
                )
            )
            await channel.send(
                OutboundMessage(
                    channel_name="feishu",
                    chat_id="chat-1",
                    thread_id="thread-1",
                    text="Hello world",
                    is_final=True,
                    thread_ts="om-source-msg",
                )
            )

            assert channel._api_client.im.v1.message.reply.call_count == 1
            assert channel._api_client.im.v1.message.patch.call_count == 2
            assert channel._api_client.im.v1.message_reaction.create.call_count == 1
            assert "om-source-msg" not in channel._running_card_ids
            assert "om-source-msg" not in channel._running_card_tasks

            first_patch_request = channel._api_client.im.v1.message.patch.call_args_list[0].args[0]
            final_patch_request = channel._api_client.im.v1.message.patch.call_args_list[1].args[0]
            assert first_patch_request.message_id == "om-running-card"
            assert final_patch_request.message_id == "om-running-card"
            assert json.loads(first_patch_request.body.content)["elements"][0]["content"] == "Hello"
            assert json.loads(final_patch_request.body.content)["elements"][0]["content"] == "Hello world"
            assert json.loads(final_patch_request.body.content)["config"]["update_multi"] is True

        _run(go())

    def test_streaming_updates_preserve_source_preview(self):
        from lark_oapi.api.im.v1 import (
            CreateMessageReactionRequest,
            CreateMessageReactionRequestBody,
            Emoji,
            PatchMessageRequest,
            PatchMessageRequestBody,
            ReplyMessageRequest,
            ReplyMessageRequestBody,
        )

        from app.channels.feishu import SOURCE_PREVIEW_METADATA_KEY, FeishuChannel

        async def go():
            bus = MessageBus()
            channel = FeishuChannel(bus, config={})

            channel._api_client = MagicMock()
            channel._ReplyMessageRequest = ReplyMessageRequest
            channel._ReplyMessageRequestBody = ReplyMessageRequestBody
            channel._PatchMessageRequest = PatchMessageRequest
            channel._PatchMessageRequestBody = PatchMessageRequestBody
            channel._CreateMessageReactionRequest = CreateMessageReactionRequest
            channel._CreateMessageReactionRequestBody = CreateMessageReactionRequestBody
            channel._Emoji = Emoji

            reply_response = MagicMock()
            reply_response.data.message_id = "om-running-card"
            channel._api_client.im.v1.message.reply = MagicMock(return_value=reply_response)
            channel._api_client.im.v1.message.patch = MagicMock()
            channel._api_client.im.v1.message_reaction.create = MagicMock()

            metadata = {SOURCE_PREVIEW_METADATA_KEY: "What changed in the last run?"}

            await channel._send_running_reply("om-source-msg", metadata=metadata)
            await channel.send(
                OutboundMessage(
                    channel_name="feishu",
                    chat_id="chat-1",
                    thread_id="thread-1",
                    text="Queued behind another request",
                    is_final=False,
                    thread_ts="om-source-msg",
                    metadata=metadata,
                )
            )
            await channel.send(
                OutboundMessage(
                    channel_name="feishu",
                    chat_id="chat-1",
                    thread_id="thread-1",
                    text="Answer ready",
                    is_final=True,
                    thread_ts="om-source-msg",
                    metadata=metadata,
                )
            )

            reply_request = channel._api_client.im.v1.message.reply.call_args.args[0]
            first_patch_request = channel._api_client.im.v1.message.patch.call_args_list[0].args[0]
            final_patch_request = channel._api_client.im.v1.message.patch.call_args_list[1].args[0]

            assert json.loads(reply_request.body.content)["elements"][0]["content"] == "> What changed in the last run?\n\nthinking..."
            assert json.loads(first_patch_request.body.content)["elements"][0]["content"] == "> What changed in the last run?\n\nQueued behind another request"
            assert json.loads(final_patch_request.body.content)["elements"][0]["content"] == "> What changed in the last run?\n\nAnswer ready"

        _run(go())


class TestWeComChannel:
    def test_publish_ws_inbound_starts_stream_and_publishes_message(self, monkeypatch):
        from app.channels.wecom import WeComChannel

        async def go():
            bus = MessageBus()
            bus.publish_inbound = AsyncMock()
            channel = WeComChannel(bus, config={})
            channel._ws_client = SimpleNamespace(reply_stream=AsyncMock())

            monkeypatch.setitem(
                __import__("sys").modules,
                "aibot",
                SimpleNamespace(generate_req_id=lambda prefix: "stream-1"),
            )

            frame = {
                "body": {
                    "msgid": "msg-1",
                    "from": {"userid": "user-1"},
                    "aibotid": "bot-1",
                    "chattype": "single",
                }
            }
            files = [{"type": "image", "url": "https://example.com/image.png"}]

            await channel._publish_ws_inbound(frame, "hello", files=files)

            channel._ws_client.reply_stream.assert_awaited_once_with(frame, "stream-1", "Working on it...", False)
            bus.publish_inbound.assert_awaited_once()

            inbound = bus.publish_inbound.await_args.args[0]
            assert inbound.channel_name == "wecom"
            assert inbound.chat_id == "user-1"
            assert inbound.user_id == "user-1"
            assert inbound.text == "hello"
            assert inbound.thread_ts == "msg-1"
            assert inbound.topic_id == "user-1"
            assert inbound.files == files
            assert inbound.metadata == {"aibotid": "bot-1", "chattype": "single", "message_id": "msg-1"}
            assert channel._ws_frames["msg-1"] is frame
            assert channel._ws_stream_ids["msg-1"] == "stream-1"

        _run(go())

    def test_publish_ws_inbound_uses_configured_working_message(self, monkeypatch):
        from app.channels.wecom import WeComChannel

        async def go():
            bus = MessageBus()
            bus.publish_inbound = AsyncMock()
            channel = WeComChannel(bus, config={"working_message": "Please wait..."})
            channel._ws_client = SimpleNamespace(reply_stream=AsyncMock())
            channel._working_message = "Please wait..."

            monkeypatch.setitem(
                __import__("sys").modules,
                "aibot",
                SimpleNamespace(generate_req_id=lambda prefix: "stream-1"),
            )

            frame = {
                "body": {
                    "msgid": "msg-1",
                    "from": {"userid": "user-1"},
                }
            }

            await channel._publish_ws_inbound(frame, "hello")

            channel._ws_client.reply_stream.assert_awaited_once_with(frame, "stream-1", "Please wait...", False)

        _run(go())

    def test_publish_ws_inbound_treats_slash_prefixed_paths_as_chat(self, monkeypatch):
        from app.channels.wecom import WeComChannel

        async def go():
            bus = MessageBus()
            bus.publish_inbound = AsyncMock()
            channel = WeComChannel(bus, config={})
            channel._ws_client = SimpleNamespace(reply_stream=AsyncMock())

            monkeypatch.setitem(
                __import__("sys").modules,
                "aibot",
                SimpleNamespace(generate_req_id=lambda prefix: "stream-1"),
            )

            frame = {
                "body": {
                    "msgid": "msg-1",
                    "from": {"userid": "user-1"},
                }
            }

            await channel._publish_ws_inbound(frame, "/mnt/user-data/uploads/report.pdf")

            inbound = bus.publish_inbound.await_args.args[0]
            assert inbound.text == "/mnt/user-data/uploads/report.pdf"
            assert inbound.msg_type == InboundMessageType.CHAT

        _run(go())

    def test_on_outbound_sends_attachment_before_clearing_context(self, tmp_path):
        from app.channels.wecom import WeComChannel

        async def go():
            bus = MessageBus()
            channel = WeComChannel(bus, config={})

            frame = {"body": {"msgid": "msg-1"}}
            ws_client = SimpleNamespace(
                reply_stream=AsyncMock(),
                reply=AsyncMock(),
            )
            channel._ws_client = ws_client
            channel._ws_frames["msg-1"] = frame
            channel._ws_stream_ids["msg-1"] = "stream-1"
            channel._upload_media_ws = AsyncMock(return_value="media-1")

            attachment_path = tmp_path / "image.png"
            attachment_path.write_bytes(b"png")
            attachment = ResolvedAttachment(
                virtual_path="/mnt/user-data/outputs/image.png",
                actual_path=attachment_path,
                filename="image.png",
                mime_type="image/png",
                size=attachment_path.stat().st_size,
                is_image=True,
            )

            msg = OutboundMessage(
                channel_name="wecom",
                chat_id="user-1",
                thread_id="thread-1",
                text="done",
                attachments=[attachment],
                is_final=True,
                thread_ts="msg-1",
            )

            await channel._on_outbound(msg)

            ws_client.reply_stream.assert_awaited_once_with(frame, "stream-1", "done", True)
            channel._upload_media_ws.assert_awaited_once_with(
                media_type="image",
                filename="image.png",
                path=str(attachment_path),
                size=attachment.size,
            )
            ws_client.reply.assert_awaited_once_with(frame, {"image": {"media_id": "media-1"}, "msgtype": "image"})
            assert "msg-1" not in channel._ws_frames
            assert "msg-1" not in channel._ws_stream_ids

        _run(go())

    def test_send_falls_back_to_send_message_without_thread_context(self):
        from app.channels.wecom import WeComChannel

        async def go():
            bus = MessageBus()
            channel = WeComChannel(bus, config={})
            channel._ws_client = SimpleNamespace(send_message=AsyncMock())

            msg = OutboundMessage(
                channel_name="wecom",
                chat_id="user-1",
                thread_id="thread-1",
                text="hello",
                thread_ts=None,
            )

            await channel.send(msg)

            channel._ws_client.send_message.assert_awaited_once_with(
                "user-1",
                {"msgtype": "markdown", "markdown": {"content": "hello"}},
            )

        _run(go())

    def test_on_ws_task_done_logs_error_on_exception(self, caplog):
        import logging

        from app.channels.wecom import WeComChannel

        channel = WeComChannel(MessageBus(), config={})
        task = MagicMock()
        task.cancelled.return_value = False
        task.exception.return_value = RuntimeError("boom")

        with caplog.at_level(logging.ERROR):
            channel._on_ws_task_done(task)

        assert any("WeCom WebSocket connection task failed" in r.message and r.levelno == logging.ERROR for r in caplog.records)

    def test_on_ws_task_done_silent_when_cancelled(self, caplog):
        import logging

        from app.channels.wecom import WeComChannel

        channel = WeComChannel(MessageBus(), config={})
        task = MagicMock()
        task.cancelled.return_value = True

        with caplog.at_level(logging.ERROR):
            channel._on_ws_task_done(task)

        task.exception.assert_not_called()
        assert caplog.records == []

    def test_on_ws_task_done_silent_when_no_exception(self, caplog):
        import logging

        from app.channels.wecom import WeComChannel

        channel = WeComChannel(MessageBus(), config={})
        task = MagicMock()
        task.cancelled.return_value = False
        task.exception.return_value = None

        with caplog.at_level(logging.ERROR):
            channel._on_ws_task_done(task)

        assert caplog.records == []

    def test_on_ws_error_logs_error(self, caplog):
        import logging

        from app.channels.wecom import WeComChannel

        channel = WeComChannel(MessageBus(), config={})

        with caplog.at_level(logging.ERROR):
            channel._on_ws_error(RuntimeError("handshake failed"))

        assert any("WeCom WebSocket error" in r.message and r.levelno == logging.ERROR for r in caplog.records)

    def test_on_ws_disconnected_logs_warning(self, caplog):
        import logging

        from app.channels.wecom import WeComChannel

        channel = WeComChannel(MessageBus(), config={})

        with caplog.at_level(logging.WARNING):
            channel._on_ws_disconnected()

        assert any("WeCom WebSocket disconnected" in r.message and r.levelno == logging.WARNING for r in caplog.records)

    def test_on_ws_disconnected_logs_reason_when_present(self, caplog):
        import logging

        from app.channels.wecom import WeComChannel

        channel = WeComChannel(MessageBus(), config={})

        with caplog.at_level(logging.WARNING):
            channel._on_ws_disconnected("connection reset")

        assert any("connection reset" in r.message and r.levelno == logging.WARNING for r in caplog.records)

    def test_start_subscribes_connection_lifecycle_events(self, monkeypatch):
        from app.channels.wecom import WeComChannel

        async def go():
            bus = MessageBus()
            channel = WeComChannel(bus, config={"bot_id": "corp123", "bot_secret": "secret"})

            ws_client = MagicMock()

            async def fake_connect():
                return None

            ws_client.connect = fake_connect

            monkeypatch.setitem(
                __import__("sys").modules,
                "aibot",
                SimpleNamespace(
                    WSClient=lambda options: ws_client,
                    WSClientOptions=lambda **kwargs: SimpleNamespace(**kwargs),
                ),
            )

            await channel.start()

            subscribed_events = {call.args[0] for call in ws_client.on.call_args_list}
            assert "error" in subscribed_events
            assert "disconnected" in subscribed_events
            assert channel._ws_task is not None

            await channel.stop()

        _run(go())


class TestChannelService:
    def test_get_status_no_channels(self):
        from app.channels.service import ChannelService

        async def go():
            service = ChannelService(channels_config={})
            await service.start()

            status = service.get_status()
            assert status["service_running"] is True
            for ch_status in status["channels"].values():
                assert ch_status["enabled"] is False
                assert ch_status["running"] is False

            await service.stop()

        _run(go())

    def test_is_channel_enabled_reflects_live_config(self):
        """``is_channel_enabled`` is the runtime kill-switch read by the GitHub
        webhook router. Verify it tracks the live ``_config`` dict, including
        updates from ``configure_channel`` (which the UI uses to flip the
        enabled flag without rewriting ``config.yaml``).
        """
        from app.channels.service import ChannelService

        async def go():
            service = ChannelService(
                channels_config={
                    "github": {"enabled": True, "default_mention_login": "bot"},
                    "feishu": {"enabled": False},
                }
            )
            await service.start()

            # Configured + enabled → True.
            assert service.is_channel_enabled("github") is True
            # Configured + disabled → False.
            assert service.is_channel_enabled("feishu") is False
            # Not present at all → False (don't fail open).
            assert service.is_channel_enabled("slack") is False
            # Non-dict garbage in config → False (defensive).
            service._config["broken"] = "not a dict"
            assert service.is_channel_enabled("broken") is False

            # Runtime flip via configure_channel must be visible.
            await service.configure_channel("github", {"enabled": False})
            assert service.is_channel_enabled("github") is False

            await service.stop()

        _run(go())

    def test_disabled_channels_are_skipped(self):
        from app.channels.service import ChannelService

        async def go():
            service = ChannelService(
                channels_config={
                    "feishu": {"enabled": False, "app_id": "x", "app_secret": "y"},
                }
            )
            await service.start()
            assert "feishu" not in service._channels
            await service.stop()

        _run(go())

    def test_concurrent_ensure_channel_ready_starts_channel_once(self):
        from app.channels.service import ChannelService

        async def go():
            service = ChannelService(
                channels_config={
                    "telegram": {"enabled": True, "bot_token": "tg-token"},
                }
            )
            await service.manager.start()
            service._running = True
            start_calls = []

            async def fake_start_channel(name, config):
                start_calls.append(name)
                await asyncio.sleep(0.01)
                service._channels[name] = SimpleNamespace(is_running=True, stop=AsyncMock())
                return True

            service._start_channel = fake_start_channel

            results = await asyncio.gather(
                service.ensure_channel_ready("telegram"),
                service.ensure_channel_ready("telegram"),
            )

            assert results == [True, True]
            assert start_calls == ["telegram"]
            await service.stop()

        _run(go())

    def test_session_config_is_forwarded_to_manager(self):
        from app.channels.service import ChannelService

        service = ChannelService(
            channels_config={
                "session": {"context": {"thinking_enabled": False}},
                "telegram": {
                    "enabled": False,
                    "session": {
                        "assistant_id": "mobile_agent",
                        "users": {
                            "vip": {
                                "assistant_id": "vip_agent",
                            }
                        },
                    },
                },
            }
        )

        assert service.manager._default_session["context"]["thinking_enabled"] is False
        assert service.manager._channel_sessions["telegram"]["assistant_id"] == "mobile_agent"
        assert service.manager._channel_sessions["telegram"]["users"]["vip"]["assistant_id"] == "vip_agent"

    def test_service_urls_fall_back_to_env(self, monkeypatch):
        from app.channels.service import ChannelService

        monkeypatch.setenv("DEER_FLOW_CHANNELS_LANGGRAPH_URL", "http://gateway:8001/api")
        monkeypatch.setenv("DEER_FLOW_CHANNELS_GATEWAY_URL", "http://gateway:8001")

        service = ChannelService(channels_config={})

        assert service.manager._langgraph_url == "http://gateway:8001/api"
        assert service.manager._gateway_url == "http://gateway:8001"

    def test_config_service_urls_override_env(self, monkeypatch):
        from app.channels.service import ChannelService

        monkeypatch.setenv("DEER_FLOW_CHANNELS_LANGGRAPH_URL", "http://gateway:8001/api")
        monkeypatch.setenv("DEER_FLOW_CHANNELS_GATEWAY_URL", "http://gateway:8001")

        service = ChannelService(
            channels_config={
                "langgraph_url": "http://custom-gateway:8001/api",
                "gateway_url": "http://custom-gateway:8001",
            }
        )

        assert service.manager._langgraph_url == "http://custom-gateway:8001/api"
        assert service.manager._gateway_url == "http://custom-gateway:8001"

    def test_from_app_config_uses_explicit_config(self):
        from app.channels.service import ChannelService

        app_config = SimpleNamespace(
            model_extra={
                "channels": {
                    "telegram": {"enabled": False},
                }
            }
        )

        with patch("deerflow.config.app_config.get_app_config", side_effect=AssertionError("should not read global config")):
            service = ChannelService.from_app_config(app_config)

        assert service._config == {"telegram": {"enabled": False}}

    def test_from_app_config_does_not_create_runtime_channels_from_channel_connections(
        self,
        monkeypatch,
        tmp_path,
    ):
        from app.channels.service import ChannelService
        from deerflow.config import paths as paths_module
        from deerflow.config.channel_connections_config import ChannelConnectionsConfig

        monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
        monkeypatch.setattr(paths_module, "_paths", None)
        app_config = SimpleNamespace(
            model_extra={},
            channel_connections=ChannelConnectionsConfig.model_validate(
                {
                    "enabled": True,
                    "telegram": {"enabled": True, "bot_username": "deerflow_bot"},
                    "slack": {"enabled": True},
                    "discord": {"enabled": True},
                }
            ),
        )

        service = ChannelService.from_app_config(app_config)

        assert service._config == {}

    def test_from_app_config_preserves_existing_runtime_channels_with_channel_connections_enabled(
        self,
        monkeypatch,
        tmp_path,
    ):
        from app.channels.runtime_config_store import ChannelRuntimeConfigStore
        from app.channels.service import ChannelService
        from deerflow.config import paths as paths_module
        from deerflow.config.channel_connections_config import ChannelConnectionsConfig

        monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
        monkeypatch.setattr(paths_module, "_paths", None)
        ChannelRuntimeConfigStore().set_provider_config(
            "slack",
            {
                "enabled": True,
                "bot_token": "xoxb-ui",
                "app_token": "xapp-ui",
            },
        )
        app_config = SimpleNamespace(
            model_extra={
                "channels": {
                    "telegram": {"enabled": True, "bot_token": "telegram-token"},
                    "slack": {"enabled": True, "bot_token": "xoxb", "app_token": "xapp"},
                    "discord": {"enabled": True, "bot_token": "discord-bot-token"},
                }
            },
            channel_connections=ChannelConnectionsConfig.model_validate(
                {
                    "enabled": True,
                    "telegram": {"enabled": True, "bot_username": "deerflow_bot"},
                    "slack": {"enabled": True},
                    "discord": {"enabled": True},
                }
            ),
        )

        service = ChannelService.from_app_config(app_config)

        assert service._config["telegram"]["bot_token"] == "telegram-token"
        # The runtime (UI-entered) value must win over the yaml value.
        assert service._config["slack"]["app_token"] == "xapp-ui"
        assert service._config["discord"]["bot_token"] == "discord-bot-token"

    def test_from_app_config_loads_persisted_runtime_channel_config(self, monkeypatch, tmp_path):
        from app.channels.runtime_config_store import ChannelRuntimeConfigStore
        from app.channels.service import ChannelService
        from deerflow.config import paths as paths_module
        from deerflow.config.channel_connections_config import ChannelConnectionsConfig

        monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
        monkeypatch.setattr(paths_module, "_paths", None)
        ChannelRuntimeConfigStore().set_provider_config(
            "slack",
            {
                "enabled": True,
                "bot_token": "xoxb-ui",
                "app_token": "xapp-ui",
            },
        )
        app_config = SimpleNamespace(
            model_extra={},
            channel_connections=ChannelConnectionsConfig.model_validate(
                {
                    "enabled": True,
                    "slack": {"enabled": True},
                }
            ),
        )

        service = ChannelService.from_app_config(app_config)

        assert service._config["slack"] == {
            "enabled": True,
            "bot_token": "xoxb-ui",
            "app_token": "xapp-ui",
        }

    def test_from_app_config_runtime_disconnect_suppresses_file_channel_config(self, monkeypatch, tmp_path):
        from app.channels.runtime_config_store import ChannelRuntimeConfigStore
        from app.channels.service import ChannelService
        from deerflow.config import paths as paths_module
        from deerflow.config.channel_connections_config import ChannelConnectionsConfig

        monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
        monkeypatch.setattr(paths_module, "_paths", None)
        ChannelRuntimeConfigStore().set_provider_config(
            "feishu",
            {
                "enabled": False,
                "_runtime_disabled": True,
            },
        )
        app_config = SimpleNamespace(
            model_extra={
                "channels": {
                    "feishu": {
                        "enabled": True,
                        "app_id": "file-app-id",
                        "app_secret": "file-secret",
                    }
                }
            },
            channel_connections=ChannelConnectionsConfig.model_validate(
                {
                    "enabled": True,
                    "feishu": {"enabled": True},
                }
            ),
        )

        service = ChannelService.from_app_config(app_config)

        assert "feishu" not in service._config

    def test_start_retries_configured_channel_until_ready(self, monkeypatch):
        from app.channels.service import ChannelService

        class FlakyReadyChannel(Channel):
            starts = 0

            def __init__(self, bus, config):
                super().__init__(name="slack", bus=bus, config=config)

            async def start(self):
                type(self).starts += 1
                self._running = type(self).starts >= 2

            async def stop(self):
                self._running = False

            async def send(self, msg):
                return None

        monkeypatch.setattr(
            "deerflow.reflection.resolve_class",
            lambda import_path, base_class=None: FlakyReadyChannel,
        )

        async def go():
            service = ChannelService(
                channels_config={
                    "slack": {
                        "enabled": True,
                        "bot_token": "xoxb-ui",
                        "app_token": "xapp-ui",
                    },
                }
            )

            try:
                await service.start()

                assert FlakyReadyChannel.starts == 2
                assert service.get_status()["channels"]["slack"]["running"] is True
            finally:
                await service.stop()

        _run(go())

    def test_connection_repo_is_forwarded_to_manager(self):
        from app.channels.service import ChannelService

        repo = object()
        service = ChannelService(channels_config={}, connection_repo=repo)

        assert service.manager._connection_repo is repo

    def test_require_bound_identity_is_forwarded_to_manager(self):
        from app.channels.service import ChannelService

        service = ChannelService(channels_config={}, require_bound_identity=True)

        assert service.manager._require_bound_identity is True

    def test_remove_channel_stops_running_channel_and_forgets_config(self):
        from app.channels.service import ChannelService

        async def go():
            service = ChannelService(
                channels_config={
                    "slack": {
                        "enabled": True,
                        "bot_token": "xoxb-ui",
                        "app_token": "xapp-ui",
                    },
                }
            )
            channel = AsyncMock()
            service._channels["slack"] = channel
            service._running = True

            assert await service.remove_channel("slack") is True

            channel.stop.assert_awaited_once()
            assert "slack" not in service._channels
            assert "slack" not in service._config

        _run(go())

    def test_disabled_channel_with_string_creds_emits_warning(self, caplog):
        """Warning is emitted when a channel has string credentials but enabled=false."""
        import logging

        from app.channels.service import ChannelService

        async def go():
            service = ChannelService(
                channels_config={
                    "wecom": {"enabled": False, "bot_id": "corp123", "bot_secret": "secret"},
                }
            )
            with caplog.at_level(logging.WARNING, logger="app.channels.service"):
                await service.start()
            await service.stop()

        _run(go())
        assert any("credentials configured but is disabled" in r.message and r.levelno == logging.WARNING for r in caplog.records)
        assert all("wecom" not in r.message for r in caplog.records)

    def test_disabled_channel_with_int_creds_emits_warning(self, caplog):
        """Warning is emitted even when YAML-parsed integer credentials are present."""
        import logging

        from app.channels.service import ChannelService

        async def go():
            # Simulate YAML parsing a numeric token/ID as an int
            service = ChannelService(
                channels_config={
                    "telegram": {"enabled": False, "bot_token": 123456789},
                }
            )
            with caplog.at_level(logging.WARNING, logger="app.channels.service"):
                await service.start()
            await service.stop()

        _run(go())
        assert any("credentials configured but is disabled" in r.message and r.levelno == logging.WARNING for r in caplog.records)
        assert all("telegram" not in r.message for r in caplog.records)

    def test_disabled_channel_without_creds_emits_info(self, caplog):
        """Only an info log (no warning) is emitted when a channel is disabled with no credentials."""
        import logging

        from app.channels.service import ChannelService

        async def go():
            service = ChannelService(
                channels_config={
                    "telegram": {"enabled": False},
                }
            )
            with caplog.at_level(logging.DEBUG, logger="app.channels.service"):
                await service.start()
            await service.stop()

        _run(go())
        warning_records = [r for r in caplog.records if "telegram" in r.message and r.levelno == logging.WARNING]
        assert not warning_records

    # -- restart_channel config reload tests (issue #3497) --

    def test_restart_channel_reloads_config_from_disk(self, monkeypatch):
        """restart_channel reads the latest config via get_app_config()."""
        from app.channels.service import ChannelService

        initial_config = {"feishu": {"enabled": True, "app_id": "old_id", "app_secret": "old_secret"}}
        updated_config = {"feishu": {"enabled": True, "app_id": "new_id", "app_secret": "new_secret"}}

        service = ChannelService(channels_config=initial_config)

        def mock_get_app_config():
            return SimpleNamespace(model_extra={"channels": updated_config})

        monkeypatch.setattr("deerflow.config.app_config.get_app_config", mock_get_app_config)

        started_configs = {}

        async def mock_start_channel(name, config):
            started_configs[name] = config
            return True

        service._start_channel = mock_start_channel

        async def go():
            await service.restart_channel("feishu")

        _run(go())

        assert started_configs["feishu"]["app_id"] == "new_id"
        assert started_configs["feishu"]["app_secret"] == "new_secret"
        assert service._config["feishu"]["app_id"] == "new_id"

    def test_configure_channel_keeps_explicit_config_over_stale_file_entry(self, monkeypatch):
        """UI-entered runtime credentials must not be clobbered by a config.yaml reload.

        configure_channel() receives the authoritative config (e.g. from the
        browser Connect/Modify dialog, never written to config.yaml), so its
        restart must skip the file reload that restart_channel() performs for
        operator-triggered restarts.
        """
        from app.channels.service import ChannelService

        def fail_get_app_config():
            raise AssertionError("configure_channel must not reload file config")

        monkeypatch.setattr("deerflow.config.app_config.get_app_config", fail_get_app_config)

        service = ChannelService(channels_config={})
        service._running = True

        started_configs = {}

        async def mock_start_channel(name, config):
            started_configs[name] = config
            return True

        service._start_channel = mock_start_channel

        async def go():
            await service.configure_channel("feishu", {"enabled": True, "app_id": "ui_id", "app_secret": "ui_secret"})

        _run(go())

        assert started_configs["feishu"]["app_id"] == "ui_id"
        assert started_configs["feishu"]["app_secret"] == "ui_secret"
        assert service._config["feishu"]["app_id"] == "ui_id"

    def test_restart_channel_reload_applies_runtime_store_overlay(self, monkeypatch, tmp_path):
        """An operator-triggered restart keeps UI runtime-store credentials for
        channels that have no config.yaml entry."""
        from app.channels.runtime_config_store import ChannelRuntimeConfigStore
        from app.channels.service import ChannelService
        from deerflow.config import paths as paths_module
        from deerflow.config.channel_connections_config import ChannelConnectionsConfig

        monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
        monkeypatch.setattr(paths_module, "_paths", None)
        ChannelRuntimeConfigStore().set_provider_config(
            "telegram",
            {"enabled": True, "bot_token": "store-token"},
        )

        def mock_get_app_config():
            return SimpleNamespace(
                model_extra={"channels": {}},
                channel_connections=ChannelConnectionsConfig.model_validate({"enabled": True, "telegram": {"enabled": True, "bot_username": "deerflow_bot"}}),
            )

        monkeypatch.setattr("deerflow.config.app_config.get_app_config", mock_get_app_config)

        service = ChannelService(channels_config={})

        started_configs = {}

        async def mock_start_channel(name, config):
            started_configs[name] = config
            return True

        service._start_channel = mock_start_channel

        async def go():
            await service.restart_channel("telegram")

        _run(go())

        assert started_configs["telegram"]["bot_token"] == "store-token"

    def test_restart_channel_falls_back_to_cached_config_on_error(self, monkeypatch):
        """When get_app_config() fails, restart_channel uses cached config."""
        from app.channels.service import ChannelService

        cached_config = {"feishu": {"enabled": True, "app_id": "cached_id", "app_secret": "cached_secret"}}
        service = ChannelService(channels_config=cached_config)

        def _raise():
            raise RuntimeError("config missing")

        monkeypatch.setattr("deerflow.config.app_config.get_app_config", _raise)

        started_configs = {}

        async def mock_start_channel(name, config):
            started_configs[name] = config
            return True

        service._start_channel = mock_start_channel

        async def go():
            await service.restart_channel("feishu")

        _run(go())

        assert started_configs["feishu"]["app_id"] == "cached_id"

    def test_restart_channel_returns_false_for_unknown_channel(self):
        """restart_channel returns False when the channel has no config."""
        from app.channels.service import ChannelService

        service = ChannelService(channels_config={})

        async def go():
            result = await service.restart_channel("nonexistent")
            assert result is False

        _run(go())

    def test_restart_channel_stops_existing_channel_before_restart(self):
        """restart_channel stops the running channel instance before restarting."""
        from app.channels.service import ChannelService

        service = ChannelService(channels_config={"feishu": {"enabled": True, "app_id": "x", "app_secret": "y"}})

        stopped = []

        class FakeChannel:
            is_running = True

            async def stop(self):
                stopped.append(True)

        service._channels["feishu"] = FakeChannel()

        started_configs = {}

        async def mock_start_channel(name, config):
            started_configs[name] = config
            return True

        service._start_channel = mock_start_channel

        async def go():
            await service.restart_channel("feishu", reload_config=False)

        _run(go())

        assert stopped
        assert "feishu" in started_configs

    def test_restart_channel_skips_disabled_channel(self, monkeypatch):
        """restart_channel stops the channel and returns True when config has enabled: false."""
        from app.channels.service import ChannelService

        service = ChannelService(channels_config={"feishu": {"enabled": True, "app_id": "x", "app_secret": "y"}})

        stopped = []

        class FakeChannel:
            is_running = True

            async def stop(self):
                stopped.append(True)

        service._channels["feishu"] = FakeChannel()

        # Simulate config.yaml updated to enabled: false
        disabled_config = {"feishu": {"enabled": False, "app_id": "x", "app_secret": "y"}}

        def mock_get_app_config():
            return SimpleNamespace(model_extra={"channels": disabled_config})

        monkeypatch.setattr("deerflow.config.app_config.get_app_config", mock_get_app_config)

        started = []

        async def mock_start_channel(name, config):
            started.append(name)
            return True

        service._start_channel = mock_start_channel

        async def go():
            result = await service.restart_channel("feishu")
            assert result is True  # successfully stopped (no restart needed)

        _run(go())

        assert stopped  # old channel was stopped
        assert not started  # _start_channel was NOT called


# ---------------------------------------------------------------------------
# Slack send retry tests
# ---------------------------------------------------------------------------


class TestSlackSendRetry:
    def test_retries_on_failure_then_succeeds(self):
        from app.channels.slack import SlackChannel

        async def go():
            bus = MessageBus()
            ch = SlackChannel(bus=bus, config={"bot_token": "xoxb-test", "app_token": "xapp-test"})

            mock_web = MagicMock()
            call_count = 0

            def post_message(**kwargs):
                nonlocal call_count
                call_count += 1
                if call_count < 3:
                    raise ConnectionError("network error")
                return MagicMock()

            mock_web.chat_postMessage = post_message
            ch._web_client = mock_web

            msg = OutboundMessage(channel_name="slack", chat_id="C123", thread_id="t1", text="hello")
            await ch.send(msg)
            assert call_count == 3

        _run(go())


class TestSlackAllowedUsers:
    @staticmethod
    def _submit_coro(coro, loop):
        coro.close()
        return MagicMock()

    def test_numeric_allowed_users_match_string_event_user_id(self):
        from app.channels.slack import SlackChannel

        bus = MessageBus()
        bus.publish_inbound = AsyncMock()
        channel = SlackChannel(
            bus=bus,
            config={"allowed_users": [123456]},
        )
        channel._loop = MagicMock()
        channel._loop.is_running.return_value = True
        channel._add_reaction = MagicMock()
        channel._send_running_reply = MagicMock()

        event = {
            "user": "123456",
            "text": "hello from slack",
            "channel": "C123",
            "ts": "1710000000.000100",
        }

        with patch(
            "app.channels.slack.asyncio.run_coroutine_threadsafe",
            side_effect=self._submit_coro,
        ) as submit:
            channel._handle_message_event(event)

        channel._add_reaction.assert_called_once_with("C123", "1710000000.000100", "eyes")
        channel._send_running_reply.assert_called_once_with("C123", "1710000000.000100")
        submit.assert_called_once()
        inbound = bus.publish_inbound.call_args.args[0]
        assert inbound.user_id == "123456"
        assert inbound.chat_id == "C123"
        assert inbound.text == "hello from slack"

    def test_string_allowed_users_match_event_user_id(self):
        from app.channels.slack import SlackChannel

        bus = MessageBus()
        bus.publish_inbound = AsyncMock()
        channel = SlackChannel(
            bus=bus,
            config={"allowed_users": "U123456"},
        )
        channel._loop = MagicMock()
        channel._loop.is_running.return_value = True
        channel._add_reaction = MagicMock()
        channel._send_running_reply = MagicMock()

        event = {
            "user": "U123456",
            "text": "hello from slack",
            "channel": "C123",
            "ts": "1710000000.000100",
        }

        with patch(
            "app.channels.slack.asyncio.run_coroutine_threadsafe",
            side_effect=self._submit_coro,
        ) as submit:
            channel._handle_message_event(event)

        channel._add_reaction.assert_called_once_with("C123", "1710000000.000100", "eyes")
        channel._send_running_reply.assert_called_once_with("C123", "1710000000.000100")
        submit.assert_called_once()
        inbound = bus.publish_inbound.call_args.args[0]
        assert inbound.user_id == "U123456"
        assert inbound.chat_id == "C123"
        assert inbound.text == "hello from slack"

    def test_connect_code_bypasses_allowed_users_filter(self):
        from app.channels.slack import SlackChannel

        bus = MessageBus()
        bus.publish_inbound = AsyncMock()
        channel = SlackChannel(
            bus=bus,
            config={"allowed_users": ["U-allowed"], "connection_repo": object()},
        )
        channel._loop = MagicMock()
        channel._loop.is_running.return_value = True
        channel._bind_connection_from_connect_code = AsyncMock(return_value=True)
        channel._add_reaction = MagicMock()
        channel._send_running_reply = MagicMock()

        event = {
            "user": "U-blocked",
            "text": "/connect slack-bind-code",
            "team": "T123",
            "channel": "C123",
            "ts": "1710000000.000100",
        }

        with patch(
            "app.channels.slack.asyncio.run_coroutine_threadsafe",
            side_effect=self._submit_coro,
        ) as submit:
            channel._handle_message_event(event)

        channel._bind_connection_from_connect_code.assert_called_once()
        submit.assert_called_once()
        bus.publish_inbound.assert_not_awaited()
        channel._add_reaction.assert_not_called()
        channel._send_running_reply.assert_not_called()

    def test_app_mention_strips_leading_bot_mention_before_command_detection(self):
        from app.channels.slack import SlackChannel

        bus = MessageBus()
        bus.publish_inbound = AsyncMock()
        channel = SlackChannel(bus=bus, config={"bot_user_id": "UBOT"})
        channel._loop = MagicMock()
        channel._loop.is_running.return_value = True
        channel._add_reaction = MagicMock()
        channel._send_running_reply = MagicMock()

        event = {
            "type": "app_mention",
            "user": "U123456",
            "text": "<@UBOT> /help",
            "channel": "C123",
            "ts": "1710000000.000100",
        }

        with patch(
            "app.channels.slack.asyncio.run_coroutine_threadsafe",
            side_effect=self._submit_coro,
        ):
            channel._handle_message_event(event)

        inbound = bus.publish_inbound.call_args.args[0]
        assert inbound.text == "/help"
        assert inbound.msg_type == InboundMessageType.COMMAND

    def test_app_mention_strips_labelled_leading_bot_mention(self):
        from app.channels.slack import SlackChannel

        bus = MessageBus()
        bus.publish_inbound = AsyncMock()
        channel = SlackChannel(bus=bus, config={"bot_user_id": "UBOT"})
        channel._loop = MagicMock()
        channel._loop.is_running.return_value = True
        channel._add_reaction = MagicMock()
        channel._send_running_reply = MagicMock()

        event = {
            "type": "app_mention",
            "user": "U123456",
            "text": "<@UBOT|deerflow> /help",
            "channel": "C123",
            "ts": "1710000000.000100",
        }

        with patch(
            "app.channels.slack.asyncio.run_coroutine_threadsafe",
            side_effect=self._submit_coro,
        ):
            channel._handle_message_event(event)

        inbound = bus.publish_inbound.call_args.args[0]
        assert inbound.text == "/help"
        assert inbound.msg_type == InboundMessageType.COMMAND

    def test_app_mention_strips_leading_bot_mention_before_slash_skill(self):
        from app.channels.slack import SlackChannel

        bus = MessageBus()
        bus.publish_inbound = AsyncMock()
        channel = SlackChannel(bus=bus, config={"bot_user_id": "UBOT"})
        channel._loop = MagicMock()
        channel._loop.is_running.return_value = True
        channel._add_reaction = MagicMock()
        channel._send_running_reply = MagicMock()

        event = {
            "type": "app_mention",
            "user": "U123456",
            "text": "<@UBOT> /data-analysis analyze uploads/foo.csv",
            "channel": "C123",
            "ts": "1710000000.000100",
        }

        with patch(
            "app.channels.slack.asyncio.run_coroutine_threadsafe",
            side_effect=self._submit_coro,
        ):
            channel._handle_message_event(event)

        inbound = bus.publish_inbound.call_args.args[0]
        assert inbound.text == "/data-analysis analyze uploads/foo.csv"
        assert inbound.msg_type == InboundMessageType.CHAT

    def test_app_mention_preserves_following_user_mention(self):
        from app.channels.slack import SlackChannel

        bus = MessageBus()
        bus.publish_inbound = AsyncMock()
        channel = SlackChannel(bus=bus, config={"bot_user_id": "UBOT"})
        channel._loop = MagicMock()
        channel._loop.is_running.return_value = True
        channel._add_reaction = MagicMock()
        channel._send_running_reply = MagicMock()

        event = {
            "type": "app_mention",
            "user": "U123456",
            "text": "<@UBOT> <@UASSIGNEE> please review this",
            "channel": "C123",
            "ts": "1710000000.000100",
        }

        with patch(
            "app.channels.slack.asyncio.run_coroutine_threadsafe",
            side_effect=self._submit_coro,
        ):
            channel._handle_message_event(event)

        inbound = bus.publish_inbound.call_args.args[0]
        assert inbound.text == "<@UASSIGNEE> please review this"
        assert inbound.msg_type == InboundMessageType.CHAT

    def test_app_mention_preserves_leading_non_bot_mention_when_bot_id_known(self):
        from app.channels.slack import SlackChannel

        bus = MessageBus()
        bus.publish_inbound = AsyncMock()
        channel = SlackChannel(bus=bus, config={"bot_user_id": "UBOT"})
        channel._loop = MagicMock()
        channel._loop.is_running.return_value = True
        channel._add_reaction = MagicMock()
        channel._send_running_reply = MagicMock()

        event = {
            "type": "app_mention",
            "user": "U123456",
            "text": "<@UASSIGNEE> <@UBOT> please review this",
            "channel": "C123",
            "ts": "1710000000.000100",
        }

        with patch(
            "app.channels.slack.asyncio.run_coroutine_threadsafe",
            side_effect=self._submit_coro,
        ):
            channel._handle_message_event(event)

        inbound = bus.publish_inbound.call_args.args[0]
        assert inbound.text == "<@UASSIGNEE> <@UBOT> please review this"
        assert inbound.msg_type == InboundMessageType.CHAT

    def test_app_mention_preserves_leading_non_bot_mention_when_bot_id_unknown(self):
        from app.channels.slack import SlackChannel

        bus = MessageBus()
        bus.publish_inbound = AsyncMock()
        channel = SlackChannel(bus=bus, config={})
        channel._loop = MagicMock()
        channel._loop.is_running.return_value = True
        channel._add_reaction = MagicMock()
        channel._send_running_reply = MagicMock()

        event = {
            "type": "app_mention",
            "user": "U123456",
            "text": "<@UASSIGNEE> /help <@UBOT>",
            "channel": "C123",
            "ts": "1710000000.000100",
        }

        with patch(
            "app.channels.slack.asyncio.run_coroutine_threadsafe",
            side_effect=self._submit_coro,
        ):
            channel._handle_message_event(event)

        inbound = bus.publish_inbound.call_args.args[0]
        assert inbound.text == "<@UASSIGNEE> /help <@UBOT>"
        assert inbound.msg_type == InboundMessageType.CHAT

    def test_socket_event_resolves_bot_user_id_before_app_mention_command_detection(self):
        from app.channels.slack import SlackChannel

        bus = MessageBus()
        bus.publish_inbound = AsyncMock()
        channel = SlackChannel(bus=bus, config={})
        channel._SocketModeResponse = lambda envelope_id: SimpleNamespace(envelope_id=envelope_id)
        channel._loop = MagicMock()
        channel._loop.is_running.return_value = True
        channel._add_reaction = MagicMock()
        channel._send_running_reply = MagicMock()

        client = SimpleNamespace(send_socket_mode_response=MagicMock())
        req = SimpleNamespace(
            envelope_id="env-1",
            type="events_api",
            payload={
                "authorizations": [{"user_id": "UBOT"}],
                "event": {
                    "type": "app_mention",
                    "user": "U123456",
                    "text": "<@UBOT> /help",
                    "channel": "C123",
                    "ts": "1710000000.000100",
                },
            },
        )

        with patch(
            "app.channels.slack.asyncio.run_coroutine_threadsafe",
            side_effect=self._submit_coro,
        ):
            channel._on_socket_event(client, req)

        inbound = bus.publish_inbound.call_args.args[0]
        assert channel._bot_user_id == "UBOT"
        assert inbound.text == "/help"
        assert inbound.msg_type == InboundMessageType.COMMAND

    def test_scalar_allowed_users_warns_and_matches_stringified_event_user_id(self, caplog):
        from app.channels.slack import SlackChannel

        bus = MessageBus()
        bus.publish_inbound = AsyncMock()
        with caplog.at_level("WARNING"):
            channel = SlackChannel(
                bus=bus,
                config={"allowed_users": 123456},
            )
        channel._loop = MagicMock()
        channel._loop.is_running.return_value = True
        channel._add_reaction = MagicMock()
        channel._send_running_reply = MagicMock()

        event = {
            "user": "123456",
            "text": "hello from slack",
            "channel": "C123",
            "ts": "1710000000.000100",
        }

        with patch(
            "app.channels.slack.asyncio.run_coroutine_threadsafe",
            side_effect=self._submit_coro,
        ) as submit:
            channel._handle_message_event(event)

        assert "Slack allowed_users should be a list" in caplog.text
        submit.assert_called_once()
        inbound = bus.publish_inbound.call_args.args[0]
        assert inbound.user_id == "123456"

    def test_raises_after_all_retries_exhausted(self):
        from app.channels.slack import SlackChannel

        async def go():
            bus = MessageBus()
            ch = SlackChannel(bus=bus, config={"bot_token": "xoxb-test", "app_token": "xapp-test"})

            mock_web = MagicMock()
            mock_web.chat_postMessage = MagicMock(side_effect=ConnectionError("fail"))
            ch._web_client = mock_web

            msg = OutboundMessage(channel_name="slack", chat_id="C123", thread_id="t1", text="hello")
            with pytest.raises(ConnectionError):
                await ch.send(msg)

            assert mock_web.chat_postMessage.call_count == 3

        _run(go())

    def test_raises_runtime_error_when_no_attempts_configured(self):
        from app.channels.slack import SlackChannel

        async def go():
            bus = MessageBus()
            ch = SlackChannel(bus=bus, config={"bot_token": "xoxb-test", "app_token": "xapp-test"})
            ch._web_client = MagicMock()

            msg = OutboundMessage(channel_name="slack", chat_id="C123", thread_id="t1", text="hello")
            with pytest.raises(RuntimeError, match="without an exception"):
                await ch.send(msg, _max_retries=0)

        _run(go())


# ---------------------------------------------------------------------------
# Telegram send retry tests
# ---------------------------------------------------------------------------


class TestTelegramSendRetry:
    def test_start_registers_known_channel_commands(self, monkeypatch):
        import sys
        from types import ModuleType

        from app.channels.commands import KNOWN_CHANNEL_COMMANDS
        from app.channels.telegram import TelegramChannel

        class FakeFilter:
            def __init__(self, expr: str):
                self.expr = expr

            def __and__(self, other):
                return FakeFilter(f"{self.expr}&{other.expr}")

            def __invert__(self):
                return FakeFilter(f"~{self.expr}")

        class FakeApplication:
            def __init__(self):
                self.handlers = []

            def add_handler(self, handler):
                self.handlers.append(handler)

        fake_app = FakeApplication()

        class FakeApplicationBuilder:
            def token(self, token):
                assert token == "test-token"
                return self

            def build(self):
                return fake_app

        def fake_command_handler(command, callback):
            return SimpleNamespace(kind="command", command=command, callback=callback)

        def fake_message_handler(filter_expr, callback):
            return SimpleNamespace(kind="message", filter_expr=filter_expr, callback=callback)

        telegram_mod = ModuleType("telegram")
        telegram_ext_mod = ModuleType("telegram.ext")
        telegram_ext_mod.ApplicationBuilder = FakeApplicationBuilder
        telegram_ext_mod.CommandHandler = fake_command_handler
        telegram_ext_mod.MessageHandler = fake_message_handler
        telegram_ext_mod.filters = SimpleNamespace(TEXT=FakeFilter("TEXT"), COMMAND=FakeFilter("COMMAND"))
        telegram_mod.ext = telegram_ext_mod
        monkeypatch.setitem(sys.modules, "telegram", telegram_mod)
        monkeypatch.setitem(sys.modules, "telegram.ext", telegram_ext_mod)

        class FakeThread:
            def __init__(self, *, target, daemon):
                self.target = target
                self.daemon = daemon

            def start(self):
                return None

            def join(self, timeout=None):
                return None

        monkeypatch.setattr("app.channels.telegram.threading.Thread", FakeThread)

        async def go():
            bus = MessageBus()
            ch = TelegramChannel(bus=bus, config={"bot_token": "test-token"})

            await ch.start()
            try:
                registered_commands = {handler.command for handler in fake_app.handlers if handler.kind == "command"}
                expected_commands = {command.removeprefix("/") for command in KNOWN_CHANNEL_COMMANDS}
                assert expected_commands <= registered_commands
                assert "start" in registered_commands
                message_filters = {handler.filter_expr.expr for handler in fake_app.handlers if handler.kind == "message"}
                assert {"TEXT&COMMAND", "TEXT&~COMMAND"} <= message_filters
            finally:
                await ch.stop()

        _run(go())

    def test_retries_on_failure_then_succeeds(self):
        from app.channels.telegram import TelegramChannel

        async def go():
            bus = MessageBus()
            ch = TelegramChannel(bus=bus, config={"bot_token": "test-token"})

            mock_app = MagicMock()
            mock_bot = AsyncMock()
            call_count = 0

            async def send_message(**kwargs):
                nonlocal call_count
                call_count += 1
                if call_count < 3:
                    raise ConnectionError("network error")
                result = MagicMock()
                result.message_id = 999
                return result

            mock_bot.send_message = send_message
            mock_app.bot = mock_bot
            ch._application = mock_app

            msg = OutboundMessage(channel_name="telegram", chat_id="12345", thread_id="t1", text="hello")
            await ch.send(msg)
            assert call_count == 3

        _run(go())

    def test_raises_after_all_retries_exhausted(self):
        from app.channels.telegram import TelegramChannel

        async def go():
            bus = MessageBus()
            ch = TelegramChannel(bus=bus, config={"bot_token": "test-token"})

            mock_app = MagicMock()
            mock_bot = AsyncMock()
            mock_bot.send_message = AsyncMock(side_effect=ConnectionError("fail"))
            mock_app.bot = mock_bot
            ch._application = mock_app

            msg = OutboundMessage(channel_name="telegram", chat_id="12345", thread_id="t1", text="hello")
            with pytest.raises(ConnectionError):
                await ch.send(msg)

            assert mock_bot.send_message.call_count == 3

        _run(go())

    def test_raises_runtime_error_when_no_attempts_configured(self):
        from app.channels.telegram import TelegramChannel

        async def go():
            bus = MessageBus()
            ch = TelegramChannel(bus=bus, config={"bot_token": "test-token"})
            ch._application = MagicMock()

            msg = OutboundMessage(channel_name="telegram", chat_id="12345", thread_id="t1", text="hello")
            with pytest.raises(RuntimeError, match="without an exception"):
                await ch.send(msg, _max_retries=0)

        _run(go())


class TestFeishuSendRetry:
    def test_raises_runtime_error_when_no_attempts_configured(self):
        from app.channels.feishu import FeishuChannel

        async def go():
            bus = MessageBus()
            ch = FeishuChannel(bus=bus, config={"app_id": "id", "app_secret": "secret"})
            ch._api_client = MagicMock()

            msg = OutboundMessage(channel_name="feishu", chat_id="chat", thread_id="t1", text="hello")
            with pytest.raises(RuntimeError, match="without an exception"):
                await ch.send(msg, _max_retries=0)

        _run(go())


# ---------------------------------------------------------------------------
# Telegram private-chat thread context tests
# ---------------------------------------------------------------------------


def _make_telegram_update(chat_type: str, message_id: int, *, reply_to_message_id: int | None = None, text: str = "hello"):
    """Build a minimal mock telegram Update for testing _on_text / _cmd_generic."""
    update = MagicMock()
    update.effective_chat.type = chat_type
    update.effective_chat.id = 100
    update.effective_user.id = 42
    update.message.text = text
    update.message.message_id = message_id
    if reply_to_message_id is not None:
        reply_msg = MagicMock()
        reply_msg.message_id = reply_to_message_id
        update.message.reply_to_message = reply_msg
    else:
        update.message.reply_to_message = None
    return update


class TestTelegramPrivateChatThread:
    """Verify that private chats use topic_id=None (single thread per chat)."""

    def test_private_chat_no_reply_uses_none_topic(self):
        from app.channels.telegram import TelegramChannel

        async def go():
            bus = MessageBus()
            ch = TelegramChannel(bus=bus, config={"bot_token": "test-token"})
            ch._main_loop = asyncio.get_event_loop()

            update = _make_telegram_update("private", message_id=10)
            await ch._on_text(update, None)

            msg = await asyncio.wait_for(bus.get_inbound(), timeout=2)
            assert msg.topic_id is None

        _run(go())

    def test_private_chat_slash_skill_text_routes_as_chat(self):
        from app.channels.telegram import TelegramChannel

        async def go():
            bus = MessageBus()
            ch = TelegramChannel(bus=bus, config={"bot_token": "test-token"})
            ch._main_loop = asyncio.get_event_loop()

            update = _make_telegram_update("private", message_id=12, text="/data-analysis analyze uploads/foo.csv")
            await ch._on_text(update, None)

            msg = await asyncio.wait_for(bus.get_inbound(), timeout=2)
            assert msg.text == "/data-analysis analyze uploads/foo.csv"
            assert msg.msg_type == InboundMessageType.CHAT
            assert msg.topic_id is None

        _run(go())

    def test_slash_skill_addressed_to_telegram_bot_strips_username(self):
        from app.channels.telegram import TelegramChannel

        async def go():
            bus = MessageBus()
            ch = TelegramChannel(bus=bus, config={"bot_token": "test-token"})
            ch._main_loop = asyncio.get_event_loop()

            update = _make_telegram_update(
                "group",
                message_id=13,
                text="/data-analysis@DeerFlowBot analyze uploads/foo.csv",
            )
            context = SimpleNamespace(bot=SimpleNamespace(username="DeerFlowBot"))
            await ch._on_text(update, context)

            msg = await asyncio.wait_for(bus.get_inbound(), timeout=2)
            assert msg.text == "/data-analysis analyze uploads/foo.csv"
            assert msg.msg_type == InboundMessageType.CHAT
            assert msg.topic_id == "13"

        _run(go())

    def test_private_chat_with_reply_still_uses_none_topic(self):
        from app.channels.telegram import TelegramChannel

        async def go():
            bus = MessageBus()
            ch = TelegramChannel(bus=bus, config={"bot_token": "test-token"})
            ch._main_loop = asyncio.get_event_loop()

            update = _make_telegram_update("private", message_id=11, reply_to_message_id=5)
            await ch._on_text(update, None)

            msg = await asyncio.wait_for(bus.get_inbound(), timeout=2)
            assert msg.topic_id is None

        _run(go())

    def test_group_chat_no_reply_uses_msg_id_as_topic(self):
        from app.channels.telegram import TelegramChannel

        async def go():
            bus = MessageBus()
            ch = TelegramChannel(bus=bus, config={"bot_token": "test-token"})
            ch._main_loop = asyncio.get_event_loop()

            update = _make_telegram_update("group", message_id=20)
            await ch._on_text(update, None)

            msg = await asyncio.wait_for(bus.get_inbound(), timeout=2)
            assert msg.topic_id == "20"

        _run(go())

    def test_group_chat_reply_uses_reply_msg_id_as_topic(self):
        from app.channels.telegram import TelegramChannel

        async def go():
            bus = MessageBus()
            ch = TelegramChannel(bus=bus, config={"bot_token": "test-token"})
            ch._main_loop = asyncio.get_event_loop()

            update = _make_telegram_update("group", message_id=21, reply_to_message_id=15)
            await ch._on_text(update, None)

            msg = await asyncio.wait_for(bus.get_inbound(), timeout=2)
            assert msg.topic_id == "15"

        _run(go())

    def test_supergroup_chat_uses_msg_id_as_topic(self):
        from app.channels.telegram import TelegramChannel

        async def go():
            bus = MessageBus()
            ch = TelegramChannel(bus=bus, config={"bot_token": "test-token"})
            ch._main_loop = asyncio.get_event_loop()

            update = _make_telegram_update("supergroup", message_id=25)
            await ch._on_text(update, None)

            msg = await asyncio.wait_for(bus.get_inbound(), timeout=2)
            assert msg.topic_id == "25"

        _run(go())

    def test_cmd_generic_private_chat_uses_none_topic(self):
        from app.channels.telegram import TelegramChannel

        async def go():
            bus = MessageBus()
            ch = TelegramChannel(bus=bus, config={"bot_token": "test-token"})
            ch._main_loop = asyncio.get_event_loop()

            update = _make_telegram_update("private", message_id=30, text="/new")
            await ch._cmd_generic(update, None)

            msg = await asyncio.wait_for(bus.get_inbound(), timeout=2)
            assert msg.topic_id is None
            assert msg.msg_type == InboundMessageType.COMMAND

        _run(go())

    def test_cmd_generic_group_chat_uses_msg_id_as_topic(self):
        from app.channels.telegram import TelegramChannel

        async def go():
            bus = MessageBus()
            ch = TelegramChannel(bus=bus, config={"bot_token": "test-token"})
            ch._main_loop = asyncio.get_event_loop()

            update = _make_telegram_update("group", message_id=31, text="/status")
            await ch._cmd_generic(update, None)

            msg = await asyncio.wait_for(bus.get_inbound(), timeout=2)
            assert msg.topic_id == "31"
            assert msg.msg_type == InboundMessageType.COMMAND

        _run(go())

    def test_cmd_generic_group_chat_reply_uses_reply_msg_id_as_topic(self):
        from app.channels.telegram import TelegramChannel

        async def go():
            bus = MessageBus()
            ch = TelegramChannel(bus=bus, config={"bot_token": "test-token"})
            ch._main_loop = asyncio.get_event_loop()

            update = _make_telegram_update("group", message_id=32, reply_to_message_id=20, text="/status")
            await ch._cmd_generic(update, None)

            msg = await asyncio.wait_for(bus.get_inbound(), timeout=2)
            assert msg.topic_id == "20"
            assert msg.msg_type == InboundMessageType.COMMAND

        _run(go())

    def test_cmd_generic_strips_addressed_telegram_bot_username(self):
        from app.channels.telegram import TelegramChannel

        async def go():
            bus = MessageBus()
            ch = TelegramChannel(bus=bus, config={"bot_token": "test-token"})
            ch._main_loop = asyncio.get_event_loop()

            update = _make_telegram_update("group", message_id=33, text="/status@DeerFlowBot")
            context = SimpleNamespace(bot=SimpleNamespace(username="DeerFlowBot"))
            await ch._cmd_generic(update, context)

            msg = await asyncio.wait_for(bus.get_inbound(), timeout=2)
            assert msg.text == "/status"
            assert msg.topic_id == "33"
            assert msg.msg_type == InboundMessageType.COMMAND

        _run(go())


class TestTelegramProcessingOrder:
    """Ensure 'working on it...' is sent before inbound is published."""

    def test_running_reply_sent_before_publish(self):
        from app.channels.telegram import TelegramChannel

        async def go():
            bus = MessageBus()
            ch = TelegramChannel(bus=bus, config={"bot_token": "test-token"})

            ch._main_loop = asyncio.get_event_loop()

            order = []

            async def mock_send_running_reply(chat_id, msg_id):
                order.append("running_reply")

            async def mock_publish_inbound(inbound):
                order.append("publish_inbound")

            ch._send_running_reply = mock_send_running_reply
            ch.bus.publish_inbound = mock_publish_inbound

            await ch._process_incoming_with_reply(chat_id="chat1", msg_id=123, inbound=InboundMessage(channel_name="telegram", chat_id="chat1", user_id="user1", text="hello"))

            assert order == ["running_reply", "publish_inbound"]

        _run(go())


# ---------------------------------------------------------------------------
# Slack markdown-to-mrkdwn conversion tests (via markdown_to_mrkdwn library)
# ---------------------------------------------------------------------------


class TestSlackMarkdownConversion:
    """Verify that the SlackChannel.send() path applies mrkdwn conversion."""

    def test_bold_converted(self):
        from app.channels.slack import _slack_md_converter

        result = _slack_md_converter.convert("this is **bold** text")
        assert "*bold*" in result
        assert "**" not in result

    def test_link_converted(self):
        from app.channels.slack import _slack_md_converter

        result = _slack_md_converter.convert("[click](https://example.com)")
        assert "<https://example.com|click>" in result

    def test_heading_converted(self):
        from app.channels.slack import _slack_md_converter

        result = _slack_md_converter.convert("# Title")
        assert "*Title*" in result
        assert "#" not in result


# ---------------------------------------------------------------------------
# Telegram streaming tests
# ---------------------------------------------------------------------------


class TestTelegramStreaming:
    @staticmethod
    def _make_channel_with_bot():
        from app.channels.telegram import TelegramChannel

        bus = MessageBus()
        ch = TelegramChannel(bus=bus, config={"bot_token": "test-token"})

        mock_app = MagicMock()
        bot = SimpleNamespace()
        bot.sent = []
        bot.edited = []
        bot.next_message_id = 100

        async def send_message(**kwargs):
            bot.sent.append(kwargs)
            result = MagicMock()
            result.message_id = bot.next_message_id
            bot.next_message_id += 1
            return result

        async def edit_message_text(**kwargs):
            bot.edited.append(kwargs)
            result = MagicMock()
            result.message_id = kwargs["message_id"]
            return result

        bot.send_message = send_message
        bot.edit_message_text = edit_message_text
        mock_app.bot = bot
        ch._application = mock_app
        return ch, bot

    def test_stream_updates_edit_placeholder_in_place(self, monkeypatch):
        async def go():
            ch, bot = self._make_channel_with_bot()

            clock = {"now": 1000.0}
            monkeypatch.setattr("app.channels.telegram._monotonic", lambda: clock["now"])

            await ch._send_running_reply("12345", 42)
            placeholder_id = ch._stream_messages["12345:42"]["message_id"]

            update1 = OutboundMessage(channel_name="telegram", chat_id="12345", thread_id="t1", text="Hello", is_final=False, thread_ts="42")
            await ch.send(update1)

            clock["now"] += 2.0
            update2 = OutboundMessage(channel_name="telegram", chat_id="12345", thread_id="t1", text="Hello world", is_final=False, thread_ts="42")
            await ch.send(update2)

            assert len(bot.sent) == 1  # only the placeholder
            assert [e["message_id"] for e in bot.edited] == [placeholder_id, placeholder_id]
            assert [e["text"] for e in bot.edited] == ["Hello", "Hello world"]

        _run(go())

    def test_stream_updates_throttled_within_interval(self, monkeypatch):
        async def go():
            ch, bot = self._make_channel_with_bot()

            clock = {"now": 1000.0}
            monkeypatch.setattr("app.channels.telegram._monotonic", lambda: clock["now"])

            await ch._send_running_reply("12345", 42)

            await ch.send(OutboundMessage(channel_name="telegram", chat_id="12345", thread_id="t1", text="a", is_final=False, thread_ts="42"))
            clock["now"] += 0.3  # within 1s window -> dropped
            await ch.send(OutboundMessage(channel_name="telegram", chat_id="12345", thread_id="t1", text="ab", is_final=False, thread_ts="42"))
            clock["now"] += 1.0  # past window -> edited
            await ch.send(OutboundMessage(channel_name="telegram", chat_id="12345", thread_id="t1", text="abc", is_final=False, thread_ts="42"))

            assert [e["text"] for e in bot.edited] == ["a", "abc"]

        _run(go())

    def test_stream_updates_in_group_chat_use_wider_throttle(self, monkeypatch):
        """Telegram groups (negative chat_id) are capped at 20 messages/minute,
        so group-chat stream edits throttle at 3s instead of 1s."""

        async def go():
            ch, bot = self._make_channel_with_bot()

            clock = {"now": 1000.0}
            monkeypatch.setattr("app.channels.telegram._monotonic", lambda: clock["now"])

            await ch._send_running_reply("-100123", 42)

            await ch.send(OutboundMessage(channel_name="telegram", chat_id="-100123", thread_id="t1", text="a", is_final=False, thread_ts="42"))
            clock["now"] += 1.2  # past the 1s private window, within the 3s group window -> dropped
            await ch.send(OutboundMessage(channel_name="telegram", chat_id="-100123", thread_id="t1", text="ab", is_final=False, thread_ts="42"))
            clock["now"] += 2.0  # 3.2s since last edit -> edited
            await ch.send(OutboundMessage(channel_name="telegram", chat_id="-100123", thread_id="t1", text="abc", is_final=False, thread_ts="42"))

            assert [e["text"] for e in bot.edited] == ["a", "abc"]

        _run(go())

    def test_stream_update_without_placeholder_sends_new_message(self):
        async def go():
            ch, bot = self._make_channel_with_bot()

            await ch.send(OutboundMessage(channel_name="telegram", chat_id="12345", thread_id="t1", text="Hi", is_final=False, thread_ts="42"))

            assert len(bot.sent) == 1
            assert bot.sent[0]["text"] == "Hi"
            # Threads under the user's message that started this turn
            assert bot.sent[0]["reply_to_message_id"] == 42
            assert ch._stream_messages["12345:42"]["message_id"] == 100

        _run(go())

    def test_stream_edit_fallback_message_threads_under_user_message(self, monkeypatch):
        async def go():
            ch, bot = self._make_channel_with_bot()

            clock = {"now": 1000.0}
            monkeypatch.setattr("app.channels.telegram._monotonic", lambda: clock["now"])

            await ch._send_running_reply("12345", 42)

            async def edit_gone(**kwargs):
                raise Exception("Bad Request: message to edit not found")

            bot.edit_message_text = edit_gone
            await ch.send(OutboundMessage(channel_name="telegram", chat_id="12345", thread_id="t1", text="Hi", is_final=False, thread_ts="42"))

            # Fallback message threads under the user's message and becomes the new stream target
            assert bot.sent[1]["text"] == "Hi"
            assert bot.sent[1]["reply_to_message_id"] == 42
            assert ch._stream_messages["12345:42"]["message_id"] == 101

        _run(go())

    def test_stream_message_registry_is_bounded(self):
        from app.channels.telegram import MAX_TRACKED_STREAM_MESSAGES

        async def go():
            ch, _bot = self._make_channel_with_bot()

            for i in range(MAX_TRACKED_STREAM_MESSAGES + 1):
                ch._register_stream_message(f"chat:{i}", message_id=i, last_text="x", last_edit_at=0.0)

            assert len(ch._stream_messages) == MAX_TRACKED_STREAM_MESSAGES
            assert "chat:0" not in ch._stream_messages  # oldest evicted
            assert f"chat:{MAX_TRACKED_STREAM_MESSAGES}" in ch._stream_messages

        _run(go())

    def test_stream_update_truncates_long_text(self, monkeypatch):
        async def go():
            ch, bot = self._make_channel_with_bot()

            clock = {"now": 1000.0}
            monkeypatch.setattr("app.channels.telegram._monotonic", lambda: clock["now"])

            await ch._send_running_reply("12345", 42)
            long_text = "x" * 5000
            await ch.send(OutboundMessage(channel_name="telegram", chat_id="12345", thread_id="t1", text=long_text, is_final=False, thread_ts="42"))

            assert len(bot.edited) == 1
            assert len(bot.edited[0]["text"]) == 4096
            assert bot.edited[0]["text"].endswith("…")

        _run(go())

    def test_stream_update_retry_after_is_dropped(self, monkeypatch):
        async def go():
            ch, bot = self._make_channel_with_bot()

            clock = {"now": 1000.0}
            monkeypatch.setattr("app.channels.telegram._monotonic", lambda: clock["now"])

            await ch._send_running_reply("12345", 42)

            async def edit_rate_limited(**kwargs):
                exc = Exception("Flood control exceeded")
                exc.retry_after = 5
                raise exc

            bot.edit_message_text = edit_rate_limited
            # Must not raise, must not send a new message
            await ch.send(OutboundMessage(channel_name="telegram", chat_id="12345", thread_id="t1", text="Hi", is_final=False, thread_ts="42"))
            assert len(bot.sent) == 1  # placeholder only

        _run(go())

    def test_telegram_reports_streaming_support(self):
        from app.channels.manager import CHANNEL_CAPABILITIES
        from app.channels.telegram import TelegramChannel

        bus = MessageBus()
        ch = TelegramChannel(bus=bus, config={"bot_token": "test-token"})
        assert ch.supports_streaming is True
        assert CHANNEL_CAPABILITIES["telegram"]["supports_streaming"] is True

    def test_running_reply_registers_stream_placeholder(self):
        from app.channels.telegram import TelegramChannel

        async def go():
            bus = MessageBus()
            ch = TelegramChannel(bus=bus, config={"bot_token": "test-token"})

            mock_app = MagicMock()
            mock_bot = AsyncMock()
            sent = MagicMock()
            sent.message_id = 777
            mock_bot.send_message = AsyncMock(return_value=sent)
            mock_app.bot = mock_bot
            ch._application = mock_app

            await ch._send_running_reply("12345", 42)

            state = ch._stream_messages["12345:42"]
            assert state["message_id"] == 777
            assert state["last_edit_at"] == 0.0
            assert state["last_text"] == "Working on it..."
            mock_bot.send_message.assert_awaited_once_with(
                chat_id=12345,
                text="Working on it...",
                reply_to_message_id=42,
            )

        _run(go())

    def test_final_message_edits_stream_message_and_clears_state(self, monkeypatch):
        async def go():
            ch, bot = self._make_channel_with_bot()

            clock = {"now": 1000.0}
            monkeypatch.setattr("app.channels.telegram._monotonic", lambda: clock["now"])

            await ch._send_running_reply("12345", 42)
            placeholder_id = ch._stream_messages["12345:42"]["message_id"]

            await ch.send(OutboundMessage(channel_name="telegram", chat_id="12345", thread_id="t1", text="partial", is_final=False, thread_ts="42"))
            await ch.send(OutboundMessage(channel_name="telegram", chat_id="12345", thread_id="t1", text="full answer", is_final=True, thread_ts="42"))

            assert [e["text"] for e in bot.edited] == ["partial", "full answer"]
            assert len(bot.sent) == 1  # placeholder only — final edited, not re-sent
            assert "12345:42" not in ch._stream_messages
            assert ch._last_bot_message["12345"] == placeholder_id

        _run(go())

    def test_final_message_splits_long_text(self, monkeypatch):
        async def go():
            ch, bot = self._make_channel_with_bot()

            clock = {"now": 1000.0}
            monkeypatch.setattr("app.channels.telegram._monotonic", lambda: clock["now"])

            await ch._send_running_reply("12345", 42)
            long_text = "a" * 4096 + "b" * 100

            await ch.send(OutboundMessage(channel_name="telegram", chat_id="12345", thread_id="t1", text=long_text, is_final=True, thread_ts="42"))

            assert len(bot.edited) == 1
            assert bot.edited[0]["text"] == "a" * 4096
            follow_ups = bot.sent[1:]  # bot.sent[0] is the placeholder
            assert [m["text"] for m in follow_ups] == ["b" * 100]
            # Fake bot assigns ids sequentially: placeholder=100, follow-up chunk=101
            assert ch._last_bot_message["12345"] == 101
            assert "12345:42" not in ch._stream_messages

        _run(go())

    def test_final_message_not_modified_error_is_ignored(self, monkeypatch):
        async def go():
            ch, bot = self._make_channel_with_bot()

            clock = {"now": 1000.0}
            monkeypatch.setattr("app.channels.telegram._monotonic", lambda: clock["now"])

            await ch._send_running_reply("12345", 42)
            await ch.send(OutboundMessage(channel_name="telegram", chat_id="12345", thread_id="t1", text="done", is_final=False, thread_ts="42"))

            async def edit_not_modified(**kwargs):
                raise Exception("Bad Request: message is not modified")

            bot.edit_message_text = edit_not_modified
            # Same text again as final — skipped via the equal-text guard:
            # must not raise, must not send a new message
            await ch.send(OutboundMessage(channel_name="telegram", chat_id="12345", thread_id="t1", text="done", is_final=True, thread_ts="42"))

            assert len(bot.sent) == 1  # placeholder only
            assert "12345:42" not in ch._stream_messages

        _run(go())

    def test_final_edit_raising_not_modified_is_swallowed(self, monkeypatch):
        async def go():
            ch, bot = self._make_channel_with_bot()

            clock = {"now": 1000.0}
            monkeypatch.setattr("app.channels.telegram._monotonic", lambda: clock["now"])

            await ch._send_running_reply("12345", 42)
            placeholder_id = ch._stream_messages["12345:42"]["message_id"]

            async def edit_not_modified(**kwargs):
                raise Exception("Bad Request: message is not modified")

            bot.edit_message_text = edit_not_modified
            # Final text differs from last_text, so the edit IS attempted and
            # raises not-modified — must be swallowed, no fallback send.
            await ch.send(OutboundMessage(channel_name="telegram", chat_id="12345", thread_id="t1", text="done", is_final=True, thread_ts="42"))

            assert len(bot.sent) == 1  # placeholder only
            assert "12345:42" not in ch._stream_messages
            assert ch._last_bot_message["12345"] == placeholder_id

        _run(go())

    def test_final_without_stream_state_sends_plain_message(self):
        async def go():
            ch, bot = self._make_channel_with_bot()

            await ch.send(OutboundMessage(channel_name="telegram", chat_id="12345", thread_id="t1", text="direct", is_final=True, thread_ts=None))

            assert len(bot.sent) == 1
            assert bot.sent[0]["text"] == "direct"
            assert len(bot.edited) == 0

        _run(go())

    def test_final_edit_retries_once_after_rate_limit(self, monkeypatch):
        async def go():
            ch, bot = self._make_channel_with_bot()

            clock = {"now": 1000.0}
            monkeypatch.setattr("app.channels.telegram._monotonic", lambda: clock["now"])

            sleeps = []

            async def fake_sleep(delay):
                sleeps.append(delay)

            monkeypatch.setattr("app.channels.telegram.asyncio.sleep", fake_sleep)

            await ch._send_running_reply("12345", 42)
            placeholder_id = ch._stream_messages["12345:42"]["message_id"]

            real_edit = bot.edit_message_text
            calls = {"n": 0}

            async def edit_flaky(**kwargs):
                calls["n"] += 1
                if calls["n"] == 1:
                    exc = Exception("Flood control exceeded")
                    exc.retry_after = 3
                    raise exc
                return await real_edit(**kwargs)

            bot.edit_message_text = edit_flaky
            await ch.send(OutboundMessage(channel_name="telegram", chat_id="12345", thread_id="t1", text="final", is_final=True, thread_ts="42"))

            assert sleeps == [3.0]
            assert [e["text"] for e in bot.edited] == ["final"]
            assert len(bot.sent) == 1  # placeholder only
            assert ch._last_bot_message["12345"] == placeholder_id
            assert "12345:42" not in ch._stream_messages

        _run(go())

    def test_final_edit_double_rate_limit_falls_back_to_new_message(self, monkeypatch):
        async def go():
            ch, bot = self._make_channel_with_bot()

            clock = {"now": 1000.0}
            monkeypatch.setattr("app.channels.telegram._monotonic", lambda: clock["now"])

            sleeps = []

            async def fake_sleep(delay):
                sleeps.append(delay)

            monkeypatch.setattr("app.channels.telegram.asyncio.sleep", fake_sleep)

            await ch._send_running_reply("12345", 42)

            async def edit_rate_limited(**kwargs):
                exc = Exception("Flood control exceeded")
                exc.retry_after = 2
                raise exc

            bot.edit_message_text = edit_rate_limited
            await ch.send(OutboundMessage(channel_name="telegram", chat_id="12345", thread_id="t1", text="final", is_final=True, thread_ts="42"))

            # Fallback delivered the final text as a new message (after the placeholder)
            assert [m["text"] for m in bot.sent] == ["Working on it...", "final"]
            assert ch._last_bot_message["12345"] == 101
            assert "12345:42" not in ch._stream_messages

        _run(go())

    def test_final_overflow_chunk_send_is_retried(self, monkeypatch):
        async def go():
            ch, bot = self._make_channel_with_bot()

            clock = {"now": 1000.0}
            monkeypatch.setattr("app.channels.telegram._monotonic", lambda: clock["now"])

            sleeps = []

            async def fake_sleep(delay):
                sleeps.append(delay)

            monkeypatch.setattr("app.channels.telegram.asyncio.sleep", fake_sleep)

            await ch._send_running_reply("12345", 42)

            real_send = bot.send_message
            failures = {"left": 1}

            async def send_flaky(**kwargs):
                if failures["left"] > 0:
                    failures["left"] -= 1
                    raise ConnectionError("transient")
                return await real_send(**kwargs)

            bot.send_message = send_flaky
            long_text = "a" * 4096 + "b" * 10
            await ch.send(OutboundMessage(channel_name="telegram", chat_id="12345", thread_id="t1", text=long_text, is_final=True, thread_ts="42"))

            assert bot.edited[0]["text"] == "a" * 4096
            assert [m["text"] for m in bot.sent] == ["Working on it...", "b" * 10]
            assert ch._last_bot_message["12345"] == 101

        _run(go())


class TestHandleGoalCommand:
    """Covers the IM-channel ``/goal`` handler (get/set/clear via the Gateway)."""

    @staticmethod
    def _install_mock_httpx(monkeypatch, calls, *, goal_payload=None, fail_method=None):
        class MockResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"goal": goal_payload}

        class MockAsyncClient:
            def __init__(self, *args, **kwargs):
                return None

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return None

            async def _record(self, method, url, **kwargs):
                calls.append({"method": method, "url": url, **kwargs})
                if fail_method == method:
                    raise RuntimeError("gateway down")
                return MockResponse()

            async def get(self, url, **kwargs):
                return await self._record("get", url, **kwargs)

            async def put(self, url, **kwargs):
                return await self._record("put", url, **kwargs)

            async def delete(self, url, **kwargs):
                return await self._record("delete", url, **kwargs)

        monkeypatch.setattr("app.channels.manager.httpx.AsyncClient", MockAsyncClient)

    @staticmethod
    def _make_manager(monkeypatch, *, thread_id):
        from app.channels.manager import ChannelManager

        bus = MessageBus()
        store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
        manager = ChannelManager(bus=bus, store=store, gateway_url="http://gateway:8001")

        async def _lookup(msg):
            return thread_id

        monkeypatch.setattr(manager, "_lookup_thread_id", _lookup)
        return manager

    @staticmethod
    def _msg(text):
        return InboundMessage(
            channel_name="slack",
            chat_id="C1",
            user_id="U1",
            text=text,
            msg_type=InboundMessageType.COMMAND,
        )

    def test_status_without_thread_reports_no_active_goal(self, monkeypatch):
        calls = []
        self._install_mock_httpx(monkeypatch, calls)

        async def go():
            manager = self._make_manager(monkeypatch, thread_id=None)
            reply = await manager._handle_goal_command(self._msg("/goal"), "")
            assert reply == "No active goal."
            assert calls == []  # no thread -> no gateway round-trip

        _run(go())

    def test_status_with_active_goal_reports_objective(self, monkeypatch):
        calls = []
        self._install_mock_httpx(monkeypatch, calls, goal_payload={"objective": "ship it"})

        async def go():
            manager = self._make_manager(monkeypatch, thread_id="t-1")
            reply = await manager._handle_goal_command(self._msg("/goal"), "")
            assert reply == "Goal: ship it"
            assert calls[0]["method"] == "get"
            assert calls[0]["url"].endswith("/api/threads/t-1/goal")

        _run(go())

    def test_status_with_no_goal_reports_none(self, monkeypatch):
        calls = []
        self._install_mock_httpx(monkeypatch, calls, goal_payload=None)

        async def go():
            manager = self._make_manager(monkeypatch, thread_id="t-1")
            reply = await manager._handle_goal_command(self._msg("/goal"), "")
            assert reply == "No active goal."

        _run(go())

    def test_clear_with_thread_calls_delete(self, monkeypatch):
        calls = []
        self._install_mock_httpx(monkeypatch, calls)

        async def go():
            manager = self._make_manager(monkeypatch, thread_id="t-1")
            reply = await manager._handle_goal_command(self._msg("/goal clear"), "clear")
            assert reply == "Goal cleared."
            assert calls[0]["method"] == "delete"

        _run(go())

    def test_clear_without_thread_is_noop(self, monkeypatch):
        calls = []
        self._install_mock_httpx(monkeypatch, calls)

        async def go():
            manager = self._make_manager(monkeypatch, thread_id=None)
            reply = await manager._handle_goal_command(self._msg("/goal reset"), "reset")
            assert reply == "Goal cleared."
            assert calls == []

        _run(go())

    def test_set_with_existing_thread_puts_objective(self, monkeypatch):
        calls = []
        self._install_mock_httpx(monkeypatch, calls, goal_payload={"objective": "finish the work"})

        async def go():
            manager = self._make_manager(monkeypatch, thread_id="t-1")
            chats = []

            async def _handle_chat(msg, **kwargs):
                chats.append((msg, kwargs))

            monkeypatch.setattr(manager, "_handle_chat", _handle_chat)

            reply = await manager._handle_goal_command(self._msg("/goal finish the work"), "finish the work")
            assert reply is None
            assert calls[0]["method"] == "put"
            assert calls[0]["json"] == {"objective": "finish the work"}
            assert chats[0][0].text == "finish the work"
            assert chats[0][0].msg_type == InboundMessageType.CHAT
            assert chats[0][1] == {"bound_identity_checked": True}

        _run(go())

    def test_set_without_thread_creates_one(self, monkeypatch):
        calls = []
        self._install_mock_httpx(monkeypatch, calls, goal_payload={"objective": "do X"})

        async def go():
            manager = self._make_manager(monkeypatch, thread_id=None)
            chats = []

            async def _create(client, msg):
                return "new-thread"

            async def _handle_chat(msg, **kwargs):
                chats.append((msg, kwargs))

            monkeypatch.setattr(manager, "_create_thread", _create)
            monkeypatch.setattr(manager, "_get_client", lambda: object())
            monkeypatch.setattr(manager, "_handle_chat", _handle_chat)

            reply = await manager._handle_goal_command(self._msg("/goal do X"), "do X")
            assert reply is None
            assert calls[0]["method"] == "put"
            assert calls[0]["url"].endswith("/api/threads/new-thread/goal")
            assert chats[0][0].text == "do X"
            assert chats[0][0].msg_type == InboundMessageType.CHAT

        _run(go())

    def test_set_failure_returns_error_message(self, monkeypatch):
        calls = []
        self._install_mock_httpx(monkeypatch, calls, fail_method="put")

        async def go():
            manager = self._make_manager(monkeypatch, thread_id="t-1")
            reply = await manager._handle_goal_command(self._msg("/goal do X"), "do X")
            assert reply == "Failed to set goal."

        _run(go())


# ---------------------------------------------------------------------------
# _merge_stream_text regression: CJK reduplication, repeated tokens, suffix
# matching tails.  Proves that the fixed function does not drop legitimate
# deltas that happen to match the accumulated buffer or its suffix.
# Import is deferred because app.channels.manager pulls in fastapi.
# ---------------------------------------------------------------------------


def _get_merge_stream_text():
    from app.channels.manager import _merge_stream_text

    return _merge_stream_text


def test_merge_stream_text_cjk_reduplication():
    """Two identical CJK tokens ('谢','谢') -> '谢谢', not '谢'."""
    _merge = _get_merge_stream_text()
    assert _merge("谢", "谢") == "谢谢"


def test_merge_stream_text_repeated_token_append():
    """Identical repeated tokens ('go','go') -> 'gogo', not 'go'."""
    _merge = _get_merge_stream_text()
    assert _merge("go", "go") == "gogo"


def test_merge_stream_text_suffix_tail_not_dropped():
    """Delta equal to buffer suffix ('l' after 'hel') -> 'hell', not 'hel'."""
    _merge = _get_merge_stream_text()
    assert _merge("hel", "l") == "hell"


def test_merge_stream_text_cumulative_strictly_longer_replaces():
    """A strictly longer cumulative snapshot that starts with existing replaces it."""
    _merge = _get_merge_stream_text()
    assert _merge("Hel", "Hel lo world") == "Hel lo world"


def test_merge_stream_text_empty_chunk_noop():
    _merge = _get_merge_stream_text()
    assert _merge("Hello", "") == "Hello"


def test_merge_stream_text_empty_existing_returns_chunk():
    _merge = _get_merge_stream_text()
    assert _merge("", "Hello") == "Hello"


def test_merge_stream_text_newline_split():
    """'\\n\\n' split across two '\\n' deltas accumulates to two newlines."""
    _merge = _get_merge_stream_text()
    assert _merge("\n", "\n") == "\n\n"


def test_merge_stream_text_normal_append():
    _merge = _get_merge_stream_text()
    assert _merge("Hello ", "world") == "Hello world"
