"""Tests for channel command handling."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import replace

from app.channels.manager import ChannelManager
from app.channels.message_bus import InboundMessage, InboundMessageType, MessageBus
from app.channels.store import ChannelStore


@pytest.fixture
def bus():
    return MessageBus()


@pytest.fixture
def store(tmp_path):
    return ChannelStore(path=tmp_path / "store.json")


@pytest.fixture
def manager(bus, store):
    return ChannelManager(
        bus=bus,
        store=store,
        langgraph_url="http://localhost:2024",
        gateway_url="http://localhost:8001",
    )


@pytest.fixture
def mock_message():
    return InboundMessage(
        channel_name="feishu",
        chat_id="test_chat",
        user_id="test_user",
        text="/help",
        msg_type=InboundMessageType.COMMAND,
        thread_ts="12345",
    )


class TestCommandHandling:
    """Test command handling in ChannelManager."""

    @pytest.mark.asyncio
    async def test_help_command(self, manager, mock_message, bus):
        """Test /help command returns formatted help text."""
        received_messages = []
        bus.subscribe_outbound(lambda msg: received_messages.append(msg))

        await manager._handle_command(mock_message)

        assert len(received_messages) == 1
        msg = received_messages[0]
        assert "Available commands" in msg.text
        assert "/new" in msg.text
        assert "/agent" in msg.text
        assert "/agents" in msg.text
        assert "/clear" in msg.text

    @pytest.mark.asyncio
    async def test_new_command_creates_thread(self, manager, mock_message, bus):
        """Test /new command creates a new thread."""
        mock_client = AsyncMock()
        mock_client.threads.create.return_value = {"thread_id": "test-thread-123"}
        manager._client = mock_client

        received_messages = []
        bus.subscribe_outbound(lambda msg: received_messages.append(msg))

        new_msg = replace(mock_message, text="/new")
        await manager._handle_command(new_msg)

        assert len(received_messages) == 1
        assert "New conversation started" in received_messages[0].text
        assert manager.store.get_thread_id("feishu", "test_chat") == "test-thread-123"

    @pytest.mark.asyncio
    async def test_clear_command_removes_thread(self, manager, mock_message, bus):
        """Test /clear command removes thread mapping."""
        # Setup: create a thread first
        manager.store.set_thread_id("feishu", "test_chat", "existing-thread")

        received_messages = []
        bus.subscribe_outbound(lambda msg: received_messages.append(msg))

        clear_msg = replace(mock_message, text="/clear")
        await manager._handle_command(clear_msg)

        assert len(received_messages) == 1
        assert "cleared" in received_messages[0].text
        assert manager.store.get_thread_id("feishu", "test_chat") is None

    @pytest.mark.asyncio
    async def test_clear_command_no_active_thread(self, manager, mock_message, bus):
        """Test /clear command when no active thread."""
        received_messages = []
        bus.subscribe_outbound(lambda msg: received_messages.append(msg))

        clear_msg = replace(mock_message, text="/clear")
        await manager._handle_command(clear_msg)

        assert len(received_messages) == 1
        assert "No active conversation" in received_messages[0].text

    @pytest.mark.asyncio
    async def test_status_command_no_thread(self, manager, mock_message, bus):
        """Test /status command when no thread exists."""
        received_messages = []
        bus.subscribe_outbound(lambda msg: received_messages.append(msg))

        status_msg = replace(mock_message, text="/status")
        await manager._handle_command(status_msg)

        assert len(received_messages) == 1
        assert "No active conversation" in received_messages[0].text

    @pytest.mark.asyncio
    async def test_agent_command_no_thread(self, manager, mock_message, bus):
        """Test /agent command when no thread exists."""
        received_messages = []
        bus.subscribe_outbound(lambda msg: received_messages.append(msg))

        agent_msg = replace(mock_message, text="/agent")
        await manager._handle_command(agent_msg)

        assert len(received_messages) == 1
        assert "No active conversation" in received_messages[0].text

    @pytest.mark.asyncio
    async def test_agent_command_shows_current(self, manager, mock_message, bus):
        """Test /agent command shows current agent."""
        # Setup: create a thread
        manager.store.set_thread_id("feishu", "test_chat", "test-thread")

        received_messages = []
        bus.subscribe_outbound(lambda msg: received_messages.append(msg))

        agent_msg = replace(mock_message, text="/agent")
        await manager._handle_command(agent_msg)

        assert len(received_messages) == 1
        assert "Current agent" in received_messages[0].text
        assert "lead_agent" in received_messages[0].text

    @pytest.mark.asyncio
    async def test_agent_command_switch(self, manager, mock_message, bus):
        """Test /agent <id> command switches agent."""
        # Setup: create a thread
        manager.store.set_thread_id("feishu", "test_chat", "test-thread")

        received_messages = []
        bus.subscribe_outbound(lambda msg: received_messages.append(msg))

        agent_msg = replace(mock_message, text="/agent custom_agent")
        await manager._handle_command(agent_msg)

        assert len(received_messages) == 1
        assert "Agent switched to: custom_agent" in received_messages[0].text

        # Verify the switch was stored
        assistant_id, _, _ = manager._resolve_run_params(
            replace(mock_message, text="test"), "test-thread"
        )
        assert assistant_id == "custom_agent"

    @pytest.mark.asyncio
    async def test_agents_command_fallback(self, manager, mock_message, bus):
        """Test /agents command fallback when gateway fails."""
        received_messages = []
        bus.subscribe_outbound(lambda msg: received_messages.append(msg))

        agents_msg = replace(mock_message, text="/agents")
        await manager._handle_command(agents_msg)

        assert len(received_messages) == 1
        # Should show fallback message with default agent
        assert "Default agent" in received_messages[0].text

    @pytest.mark.asyncio
    async def test_unknown_command(self, manager, mock_message, bus):
        """Test unknown command returns error message."""
        received_messages = []
        bus.subscribe_outbound(lambda msg: received_messages.append(msg))

        unknown_msg = replace(mock_message, text="/unknown")
        await manager._handle_command(unknown_msg)

        assert len(received_messages) == 1
        assert "Unknown command" in received_messages[0].text
        assert "/help" in received_messages[0].text


class TestAgentSwitching:
    """Test agent switching functionality."""

    @pytest.mark.asyncio
    async def test_agent_per_user_isolation(self, manager, bus):
        """Test that agent selection is per-user."""
        manager.store.set_thread_id("feishu", "chat1", "thread1")

        msg1 = InboundMessage(
            channel_name="feishu",
            chat_id="chat1",
            user_id="user1",
            text="/agent agent_a",
            msg_type=InboundMessageType.COMMAND,
        )
        msg2 = InboundMessage(
            channel_name="feishu",
            chat_id="chat1",
            user_id="user2",
            text="/agent agent_b",
            msg_type=InboundMessageType.COMMAND,
        )

        bus.subscribe_outbound(lambda msg: None)

        await manager._handle_command(msg1)
        await manager._handle_command(msg2)

        # Verify each user has their own agent
        assistant_id1, _, _ = manager._resolve_run_params(
            replace(msg1, text="test"), "thread1"
        )
        assistant_id2, _, _ = manager._resolve_run_params(
            replace(msg2, text="test"), "thread1"
        )

        assert assistant_id1 == "agent_a"
        assert assistant_id2 == "agent_b"
