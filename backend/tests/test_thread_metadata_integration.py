"""Test thread metadata injection in channel manager."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from app.channels.message_bus import InboundMessage, MessageBus
from app.channels.store import ChannelStore


class TestThreadMetadataInjection:
    """Test that thread metadata is properly injected with user_id."""

    def test_create_thread_injects_user_id_metadata(self):
        """Thread creation should inject user_id into metadata."""
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
                user_id="user-123",
                text="hi"
            )
            await bus.publish_inbound(inbound)
            await _wait_for(lambda: len(outbound_received) >= 1)
            await manager.stop()

            # Thread should be created on the LangGraph Server
            mock_client.threads.create.assert_called_once()

            # Verify that metadata with user_id was passed
            call_args = mock_client.threads.create.call_args
            assert call_args is not None
            assert len(call_args) > 0

            # Check if config parameter was passed
            if call_args[1]:
                config = call_args[1].get("config", {})
                metadata = config.get("metadata", {})
                assert "user_id" in metadata
                assert metadata["user_id"] == "user-123"

        _run(go())

    def test_new_command_injects_user_id_metadata(self):
        """The /new command should also inject user_id into metadata."""
        from app.channels.manager import ChannelManager

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(bus=bus, store=store)

            outbound_received = []

            async def capture_outbound(msg):
                outbound_received.append(msg)

            bus.subscribe_outbound(capture_outbound)

            mock_client = _make_mock_langgraph_client(thread_id="new-thread-456")
            manager._client = mock_client

            await manager.start()

            inbound = InboundMessage(
                channel_name="test",
                chat_id="chat1",
                user_id="user-456",
                text="/new"
            )
            await bus.publish_inbound(inbound)
            await _wait_for(lambda: len(outbound_received) >= 1)
            await manager.stop()

            # Thread should be created for /new command
            mock_client.threads.create.assert_called_once()

            # Verify that metadata with user_id was passed
            call_args = mock_client.threads.create.call_args
            assert call_args is not None
            assert len(call_args) > 0

            # Check if config parameter was passed
            if call_args[1]:
                config = call_args[1].get("config", {})
                metadata = config.get("metadata", {})
                assert "user_id" in metadata
                assert metadata["user_id"] == "user-456"

        _run(go())


def _make_mock_langgraph_client(thread_id="test-thread-123", run_result=None):
    """Create a mock langgraph_sdk async client."""
    mock_client = MagicMock()

    # threads.create() returns a Thread-like dict
    mock_client.threads.create = AsyncMock(return_value={"thread_id": thread_id})

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


def _run(coroutine):
    """Helper to run async tests."""
    import asyncio

    return asyncio.run(coroutine)


async def _wait_for(condition, *, timeout=5.0, interval=0.05):
    """Poll *condition* until it returns True, or raise after *timeout* seconds."""
    import asyncio
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        await asyncio.sleep(interval)
    raise TimeoutError(f"Condition not met within {timeout}s")
