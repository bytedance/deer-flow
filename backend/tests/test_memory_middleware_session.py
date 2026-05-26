"""Unit tests for MemoryMiddleware session memory integration."""

from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.middlewares.memory_middleware import MemoryMiddleware
from deerflow.config.memory_config import MemoryConfig
from deerflow.config.session_memory_config import SessionMemoryConfig


def _make_state(messages):
    return {"messages": messages}


def _make_runtime(thread_id="thread-123"):
    runtime = MagicMock()
    runtime.context = {"thread_id": thread_id}
    return runtime


class TestMemoryMiddlewareSessionIntegration:
    """Tests for session memory queueing in MemoryMiddleware.after_agent()."""

    def test_after_agent_queues_session_memory_when_enabled(self):
        """after_agent() queues to session memory queue when session memory is enabled."""
        mw = MemoryMiddleware()
        state = _make_state([HumanMessage(content="hello"), AIMessage(content="hi")])
        runtime = _make_runtime()

        mock_memory_queue = MagicMock()
        mock_session_queue = MagicMock()

        with (
            patch("deerflow.agents.middlewares.memory_middleware.get_memory_config", return_value=MemoryConfig(enabled=True)),
            patch("deerflow.agents.middlewares.memory_middleware.get_session_memory_config", return_value=SessionMemoryConfig(enabled=True)),
            patch("deerflow.agents.middlewares.memory_middleware.get_memory_queue", return_value=mock_memory_queue),
            patch("deerflow.agents.middlewares.memory_middleware.get_session_memory_queue", return_value=mock_session_queue),
            patch("deerflow.agents.middlewares.memory_middleware.get_effective_user_id", return_value="user-1"),
        ):
            mw.after_agent(state, runtime)

        mock_memory_queue.add.assert_called_once()
        mock_session_queue.add.assert_called_once()
        session_call = mock_session_queue.add.call_args
        assert session_call.kwargs["thread_id"] == "thread-123"
        assert session_call.kwargs["user_id"] == "user-1"

    def test_after_agent_skips_session_memory_when_disabled(self):
        """after_agent() does not queue to session memory when session memory is disabled."""
        mw = MemoryMiddleware()
        state = _make_state([HumanMessage(content="hello"), AIMessage(content="hi")])
        runtime = _make_runtime()

        mock_memory_queue = MagicMock()
        mock_session_queue = MagicMock()

        with (
            patch("deerflow.agents.middlewares.memory_middleware.get_memory_config", return_value=MemoryConfig(enabled=True)),
            patch("deerflow.agents.middlewares.memory_middleware.get_session_memory_config", return_value=SessionMemoryConfig(enabled=False)),
            patch("deerflow.agents.middlewares.memory_middleware.get_memory_queue", return_value=mock_memory_queue),
            patch("deerflow.agents.middlewares.memory_middleware.get_session_memory_queue", return_value=mock_session_queue),
            patch("deerflow.agents.middlewares.memory_middleware.get_effective_user_id", return_value="user-1"),
        ):
            mw.after_agent(state, runtime)

        mock_memory_queue.add.assert_called_once()
        mock_session_queue.add.assert_not_called()

    def test_after_agent_passes_correction_and_reinforcement_to_session_queue(self):
        """after_agent() forwards correction/reinforcement flags to session queue."""
        mw = MemoryMiddleware()
        state = _make_state([
            HumanMessage(content="No, that's wrong, use JWT instead"),
            AIMessage(content="You're right, JWT is better"),
        ])
        runtime = _make_runtime()

        mock_memory_queue = MagicMock()
        mock_session_queue = MagicMock()

        with (
            patch("deerflow.agents.middlewares.memory_middleware.get_memory_config", return_value=MemoryConfig(enabled=True)),
            patch("deerflow.agents.middlewares.memory_middleware.get_session_memory_config", return_value=SessionMemoryConfig(enabled=True)),
            patch("deerflow.agents.middlewares.memory_middleware.get_memory_queue", return_value=mock_memory_queue),
            patch("deerflow.agents.middlewares.memory_middleware.get_session_memory_queue", return_value=mock_session_queue),
            patch("deerflow.agents.middlewares.memory_middleware.get_effective_user_id", return_value="user-1"),
            patch("deerflow.agents.middlewares.memory_middleware.detect_correction", return_value=True),
            patch("deerflow.agents.middlewares.memory_middleware.detect_reinforcement", return_value=False),
        ):
            mw.after_agent(state, runtime)

        session_call = mock_session_queue.add.call_args
        assert session_call.kwargs["correction_detected"] is True
        assert session_call.kwargs["reinforcement_detected"] is False

    def test_after_agent_session_queue_failure_does_not_affect_user_memory(self):
        """after_agent() continues even if session queue raises an exception."""
        mw = MemoryMiddleware()
        state = _make_state([HumanMessage(content="hello"), AIMessage(content="hi")])
        runtime = _make_runtime()

        mock_memory_queue = MagicMock()
        mock_session_queue = MagicMock()
        mock_session_queue.add.side_effect = RuntimeError("session queue boom")

        with (
            patch("deerflow.agents.middlewares.memory_middleware.get_memory_config", return_value=MemoryConfig(enabled=True)),
            patch("deerflow.agents.middlewares.memory_middleware.get_session_memory_config", return_value=SessionMemoryConfig(enabled=True)),
            patch("deerflow.agents.middlewares.memory_middleware.get_memory_queue", return_value=mock_memory_queue),
            patch("deerflow.agents.middlewares.memory_middleware.get_session_memory_queue", return_value=mock_session_queue),
            patch("deerflow.agents.middlewares.memory_middleware.get_effective_user_id", return_value="user-1"),
        ):
            # Should not raise
            result = mw.after_agent(state, runtime)

        assert result is None
        mock_memory_queue.add.assert_called_once()

    def test_after_agent_skips_when_no_messages(self):
        """after_agent() returns None when no messages in state."""
        mw = MemoryMiddleware()
        state = _make_state([])
        runtime = _make_runtime()

        with (
            patch("deerflow.agents.middlewares.memory_middleware.get_memory_config", return_value=MemoryConfig(enabled=True)),
        ):
            result = mw.after_agent(state, runtime)

        assert result is None

    def test_after_agent_skips_when_memory_disabled(self):
        """after_agent() returns None when user memory is disabled."""
        mw = MemoryMiddleware()
        state = _make_state([HumanMessage(content="hello"), AIMessage(content="hi")])
        runtime = _make_runtime()

        with (
            patch("deerflow.agents.middlewares.memory_middleware.get_memory_config", return_value=MemoryConfig(enabled=False)),
        ):
            result = mw.after_agent(state, runtime)

        assert result is None
