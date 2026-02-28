"""Tests for subagent executor async/sync execution paths.

Covers:
- SubagentExecutor.execute() synchronous execution path
- SubagentExecutor._aexecute() asynchronous execution path
- asyncio.run() properly executes async workflow within thread pool context
- Error handling in both sync and async paths
- Async tool support (MCP tools)

Note: Due to circular import issues in the main codebase, conftest.py mocks
src.subagents.executor. This test file must work around that by testing the
real implementation in isolation.
"""

import asyncio
import sys
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

# Remove the mocked executor module if it exists
if "src.subagents.executor" in sys.modules:
    del sys.modules["src.subagents.executor"]

# Pre-mock dependencies BEFORE importing the real executor
sys.modules["src.agents"] = MagicMock()
sys.modules["src.agents.thread_state"] = MagicMock()
sys.modules["src.agents.middlewares"] = MagicMock()
sys.modules["src.agents.middlewares.thread_data_middleware"] = MagicMock()
sys.modules["src.sandbox"] = MagicMock()
sys.modules["src.sandbox.middleware"] = MagicMock()
sys.modules["src.models"] = MagicMock()

# Now import the real executor module
from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402

from src.subagents.config import SubagentConfig  # noqa: E402
from src.subagents.executor import (  # noqa: E402
    SubagentExecutor,
    SubagentResult,
    SubagentStatus,
)

# -----------------------------------------------------------------------------
# Helper Classes for Testing
# -----------------------------------------------------------------------------


class MockHumanMessage(HumanMessage):
    """Mock HumanMessage for testing."""

    def __init__(self, content):
        super().__init__(content=content)


class MockAIMessage(AIMessage):
    """Mock AIMessage for testing."""

    def __init__(self, content, msg_id=None):
        # Support both string and list content
        super().__init__(content=content)
        self.id = msg_id

    def model_dump(self):
        return {"content": self.content, "id": self.id, "type": "ai"}


async def async_iterator(items):
    """Helper to create an async iterator from a list."""
    for item in items:
        yield item


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def base_config():
    """Return a basic subagent config for testing."""
    return SubagentConfig(
        name="test-agent",
        description="Test agent",
        system_prompt="You are a test agent.",
        max_turns=10,
        timeout_seconds=60,
    )


@pytest.fixture
def mock_agent():
    """Return a properly configured mock agent with async stream."""
    agent = MagicMock()
    # Don't use AsyncMock for astream - we'll set its side_effect directly
    agent.astream = MagicMock()
    return agent


# -----------------------------------------------------------------------------
# Async Execution Path Tests
# -----------------------------------------------------------------------------


class TestAsyncExecutionPath:
    """Test _aexecute() async execution path."""

    @pytest.mark.anyio
    async def test_aexecute_success(self, base_config, mock_agent):
        """Test successful async execution returns completed result."""
        final_message = MockAIMessage("Task completed successfully", "msg-1")
        final_state = {
            "messages": [
                MockHumanMessage("Do something"),
                final_message,
            ]
        }
        mock_agent.astream = lambda *args, **kwargs: async_iterator([final_state])

        executor = SubagentExecutor(
            config=base_config,
            tools=[],
            thread_id="test-thread",
            trace_id="test-trace",
        )

        with patch.object(executor, "_create_agent", return_value=mock_agent):
            result = await executor._aexecute("Do something")

        assert result.status == SubagentStatus.COMPLETED
        assert result.result == "Task completed successfully"
        assert result.error is None
        assert result.started_at is not None
        assert result.completed_at is not None

    @pytest.mark.anyio
    async def test_aexecute_collects_ai_messages(self, base_config, mock_agent):
        """Test that AI messages are collected during streaming."""
        msg1 = MockAIMessage("First response", "msg-1")
        msg2 = MockAIMessage("Second response", "msg-2")

        chunk1 = {"messages": [MockHumanMessage("Task"), msg1]}
        chunk2 = {"messages": [MockHumanMessage("Task"), msg1, msg2]}

        mock_agent.astream = lambda *args, **kwargs: async_iterator([chunk1, chunk2])

        executor = SubagentExecutor(
            config=base_config,
            tools=[],
            thread_id="test-thread",
        )

        with patch.object(executor, "_create_agent", return_value=mock_agent):
            result = await executor._aexecute("Task")

        assert result.status == SubagentStatus.COMPLETED
        assert len(result.ai_messages) == 2
        assert result.ai_messages[0]["id"] == "msg-1"
        assert result.ai_messages[1]["id"] == "msg-2"

    @pytest.mark.anyio
    async def test_aexecute_handles_duplicate_messages(self, base_config, mock_agent):
        """Test that duplicate AI messages are not added."""
        msg1 = MockAIMessage("Response", "msg-1")

        # Same message appears in multiple chunks
        chunk1 = {"messages": [MockHumanMessage("Task"), msg1]}
        chunk2 = {"messages": [MockHumanMessage("Task"), msg1]}

        mock_agent.astream = lambda *args, **kwargs: async_iterator([chunk1, chunk2])

        executor = SubagentExecutor(
            config=base_config,
            tools=[],
            thread_id="test-thread",
        )

        with patch.object(executor, "_create_agent", return_value=mock_agent):
            result = await executor._aexecute("Task")

        assert len(result.ai_messages) == 1

    @pytest.mark.anyio
    async def test_aexecute_handles_list_content(self, base_config, mock_agent):
        """Test handling of list-type content in AIMessage."""
        final_message = MockAIMessage(content=[{"text": "Part 1"}, {"text": "Part 2"}])
        final_state = {
            "messages": [
                MockHumanMessage("Task"),
                final_message,
            ]
        }
        mock_agent.astream = lambda *args, **kwargs: async_iterator([final_state])

        executor = SubagentExecutor(
            config=base_config,
            tools=[],
            thread_id="test-thread",
        )

        with patch.object(executor, "_create_agent", return_value=mock_agent):
            result = await executor._aexecute("Task")

        assert result.status == SubagentStatus.COMPLETED
        assert "Part 1" in result.result
        assert "Part 2" in result.result

    @pytest.mark.anyio
    async def test_aexecute_handles_agent_exception(self, base_config, mock_agent):
        """Test that exceptions during execution are caught and returned as FAILED."""
        mock_agent.astream.side_effect = Exception("Agent error")

        executor = SubagentExecutor(
            config=base_config,
            tools=[],
            thread_id="test-thread",
        )

        with patch.object(executor, "_create_agent", return_value=mock_agent):
            result = await executor._aexecute("Task")

        assert result.status == SubagentStatus.FAILED
        assert "Agent error" in result.error
        assert result.completed_at is not None

    @pytest.mark.anyio
    async def test_aexecute_no_final_state(self, base_config, mock_agent):
        """Test handling when no final state is returned."""
        mock_agent.astream = lambda *args, **kwargs: async_iterator([])

        executor = SubagentExecutor(
            config=base_config,
            tools=[],
            thread_id="test-thread",
        )

        with patch.object(executor, "_create_agent", return_value=mock_agent):
            result = await executor._aexecute("Task")

        assert result.status == SubagentStatus.COMPLETED
        assert result.result == "No response generated"

    @pytest.mark.anyio
    async def test_aexecute_no_ai_message_in_state(self, base_config, mock_agent):
        """Test fallback when no AIMessage found in final state."""
        final_state = {"messages": [MockHumanMessage("Task")]}
        mock_agent.astream = lambda *args, **kwargs: async_iterator([final_state])

        executor = SubagentExecutor(
            config=base_config,
            tools=[],
            thread_id="test-thread",
        )

        with patch.object(executor, "_create_agent", return_value=mock_agent):
            result = await executor._aexecute("Task")

        # Should fallback to string representation of last message
        assert result.status == SubagentStatus.COMPLETED
        assert "Task" in result.result


# -----------------------------------------------------------------------------
# Sync Execution Path Tests
# -----------------------------------------------------------------------------


class TestSyncExecutionPath:
    """Test execute() synchronous execution path with asyncio.run()."""

    def test_execute_runs_async_in_event_loop(self, base_config, mock_agent):
        """Test that execute() runs _aexecute() in a new event loop via asyncio.run()."""
        final_message = MockAIMessage("Sync result", "msg-1")
        final_state = {
            "messages": [
                MockHumanMessage("Task"),
                final_message,
            ]
        }
        mock_agent.astream = lambda *args, **kwargs: async_iterator([final_state])

        executor = SubagentExecutor(
            config=base_config,
            tools=[],
            thread_id="test-thread",
        )

        with patch.object(executor, "_create_agent", return_value=mock_agent):
            result = executor.execute("Task")

        assert result.status == SubagentStatus.COMPLETED
        assert result.result == "Sync result"

    def test_execute_in_thread_pool_context(self, base_config):
        """Test that execute() works correctly when called from a thread pool.

        This simulates the real-world usage where execute() is called from
        _execution_pool in execute_async().
        """
        from concurrent.futures import ThreadPoolExecutor

        final_message = MockAIMessage("Thread pool result", "msg-1")
        final_state = {
            "messages": [
                MockHumanMessage("Task"),
                final_message,
            ]
        }

        def run_in_thread():
            mock_agent = MagicMock()
            mock_agent.astream = lambda *args, **kwargs: async_iterator([final_state])

            executor = SubagentExecutor(
                config=base_config,
                tools=[],
                thread_id="test-thread",
            )

            with patch.object(executor, "_create_agent", return_value=mock_agent):
                return executor.execute("Task")

        # Execute in thread pool (simulating _execution_pool usage)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(run_in_thread)
            result = future.result(timeout=5)

        assert result.status == SubagentStatus.COMPLETED
        assert result.result == "Thread pool result"

    def test_execute_handles_asyncio_run_failure(self, base_config):
        """Test handling when asyncio.run() itself fails."""
        executor = SubagentExecutor(
            config=base_config,
            tools=[],
            thread_id="test-thread",
        )

        with patch.object(executor, "_aexecute") as mock_aexecute:
            mock_aexecute.side_effect = Exception("Asyncio run error")

            result = executor.execute("Task")

        assert result.status == SubagentStatus.FAILED
        assert "Asyncio run error" in result.error
        assert result.completed_at is not None

    def test_execute_with_result_holder(self, base_config, mock_agent):
        """Test execute() updates provided result_holder in real-time."""
        msg1 = MockAIMessage("Step 1", "msg-1")
        chunk1 = {"messages": [MockHumanMessage("Task"), msg1]}

        mock_agent.astream = lambda *args, **kwargs: async_iterator([chunk1])

        # Pre-create result holder (as done in execute_async)
        result_holder = SubagentResult(
            task_id="predefined-id",
            trace_id="test-trace",
            status=SubagentStatus.RUNNING,
            started_at=datetime.now(),
        )

        executor = SubagentExecutor(
            config=base_config,
            tools=[],
            thread_id="test-thread",
        )

        with patch.object(executor, "_create_agent", return_value=mock_agent):
            result = executor.execute("Task", result_holder=result_holder)

        # Should be the same object
        assert result is result_holder
        assert result.task_id == "predefined-id"
        assert result.status == SubagentStatus.COMPLETED


# -----------------------------------------------------------------------------
# Async Tool Support Tests (MCP Tools)
# -----------------------------------------------------------------------------


class TestAsyncToolSupport:
    """Test that async-only tools (like MCP tools) work correctly."""

    @pytest.mark.anyio
    async def test_async_tool_called_in_astream(self, base_config):
        """Test that async tools are properly awaited in astream.

        This verifies the fix for: async MCP tools not being executed properly
        because they were being called synchronously.
        """
        async_tool_calls = []

        async def mock_async_tool(*args, **kwargs):
            async_tool_calls.append("called")
            await asyncio.sleep(0.01)  # Simulate async work
            return {"result": "async tool result"}

        mock_agent = MagicMock()

        # Simulate agent that calls async tools during streaming
        async def mock_astream(*args, **kwargs):
            await mock_async_tool()
            yield {
                "messages": [
                    MockHumanMessage("Task"),
                    MockAIMessage("Done", "msg-1"),
                ]
            }

        mock_agent.astream = mock_astream

        executor = SubagentExecutor(
            config=base_config,
            tools=[],
            thread_id="test-thread",
        )

        with patch.object(executor, "_create_agent", return_value=mock_agent):
            result = await executor._aexecute("Task")

        assert len(async_tool_calls) == 1
        assert result.status == SubagentStatus.COMPLETED

    def test_sync_execute_with_async_tools(self, base_config):
        """Test that sync execute() properly runs async tools via asyncio.run()."""
        async_tool_calls = []

        async def mock_async_tool():
            async_tool_calls.append("called")
            await asyncio.sleep(0.01)
            return {"result": "async result"}

        mock_agent = MagicMock()

        async def mock_astream(*args, **kwargs):
            await mock_async_tool()
            yield {
                "messages": [
                    MockHumanMessage("Task"),
                    MockAIMessage("Done", "msg-1"),
                ]
            }

        mock_agent.astream = mock_astream

        executor = SubagentExecutor(
            config=base_config,
            tools=[],
            thread_id="test-thread",
        )

        with patch.object(executor, "_create_agent", return_value=mock_agent):
            result = executor.execute("Task")

        assert len(async_tool_calls) == 1
        assert result.status == SubagentStatus.COMPLETED


# -----------------------------------------------------------------------------
# Thread Safety Tests
# -----------------------------------------------------------------------------


class TestThreadSafety:
    """Test thread safety of executor operations."""

    def test_multiple_executors_in_parallel(self, base_config):
        """Test multiple executors running in parallel via thread pool."""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        results = []

        def execute_task(task_id: int):
            def make_astream(*args, **kwargs):
                return async_iterator(
                    [
                        {
                            "messages": [
                                MockHumanMessage(f"Task {task_id}"),
                                MockAIMessage(f"Result {task_id}", f"msg-{task_id}"),
                            ]
                        }
                    ]
                )

            mock_agent = MagicMock()
            mock_agent.astream = make_astream

            executor = SubagentExecutor(
                config=base_config,
                tools=[],
                thread_id=f"thread-{task_id}",
            )

            with patch.object(executor, "_create_agent", return_value=mock_agent):
                return executor.execute(f"Task {task_id}")

        # Execute multiple tasks in parallel
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(execute_task, i) for i in range(5)]
            for future in as_completed(futures):
                results.append(future.result())

        assert len(results) == 5
        for result in results:
            assert result.status == SubagentStatus.COMPLETED
            assert "Result" in result.result


# -----------------------------------------------------------------------------
# Cleanup: Remove mocked modules to avoid interfering with other tests
# -----------------------------------------------------------------------------

# Delete the mocked modules so other tests can import the real ones
del sys.modules["src.agents"]
del sys.modules["src.agents.thread_state"]
del sys.modules["src.agents.middlewares"]
del sys.modules["src.agents.middlewares.thread_data_middleware"]
del sys.modules["src.sandbox"]
del sys.modules["src.sandbox.middleware"]
del sys.modules["src.models"]
# Also remove executor so it gets re-imported fresh for other tests
if "src.subagents.executor" in sys.modules:
    del sys.modules["src.subagents.executor"]
