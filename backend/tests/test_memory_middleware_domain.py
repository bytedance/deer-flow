"""Unit tests for MemoryMiddleware domain memory integration."""

from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.middlewares.memory_middleware import MemoryMiddleware
from deerflow.config.memory_config import MemoryConfig
from deerflow.config.session_memory_config import SessionMemoryConfig
from deerflow.config.domain_memory_config import DomainMemoryConfig


def _make_state(messages):
    return {"messages": messages}


def _make_runtime(thread_id="thread-123"):
    runtime = MagicMock()
    runtime.context = {"thread_id": thread_id}
    return runtime


class TestMemoryMiddlewareDomainIntegration:
    """Tests for domain memory queueing in MemoryMiddleware.after_agent()."""

    def test_after_agent_queues_domain_memory_when_enabled(self):
        """after_agent() queues to domain memory queue when domain memory is enabled."""
        mw = MemoryMiddleware()
        state = _make_state([HumanMessage(content="Pump A has flow rate 500 GPM"), AIMessage(content="Noted")])
        runtime = _make_runtime()

        mock_memory_queue = MagicMock()
        mock_session_queue = MagicMock()
        mock_domain_queue = MagicMock()

        with (
            patch("deerflow.agents.middlewares.memory_middleware.get_memory_config", return_value=MemoryConfig(enabled=True)),
            patch("deerflow.agents.middlewares.memory_middleware.get_session_memory_config", return_value=SessionMemoryConfig(enabled=False)),
            patch("deerflow.agents.middlewares.memory_middleware.get_domain_memory_config", return_value=DomainMemoryConfig(enabled=True)),
            patch("deerflow.agents.middlewares.memory_middleware.get_memory_queue", return_value=mock_memory_queue),
            patch("deerflow.agents.middlewares.memory_middleware.get_session_memory_queue", return_value=mock_session_queue),
            patch("deerflow.agents.middlewares.memory_middleware.get_domain_memory_queue", return_value=mock_domain_queue),
            patch("deerflow.agents.middlewares.memory_middleware.get_effective_user_id", return_value="user-1"),
            patch("deerflow.agents.middlewares.memory_middleware.get_current_tenant_id", return_value="tenant-xyz"),
        ):
            mw.after_agent(state, runtime)

        mock_memory_queue.add.assert_called_once()
        mock_domain_queue.add.assert_called_once()
        domain_call = mock_domain_queue.add.call_args
        assert domain_call.kwargs["thread_id"] == "thread-123"
        assert domain_call.kwargs["tenant_id"] == "tenant-xyz"
        assert domain_call.kwargs["user_id"] == "user-1"

    def test_after_agent_skips_domain_memory_when_disabled(self):
        """after_agent() does not queue to domain memory when domain memory is disabled."""
        mw = MemoryMiddleware()
        state = _make_state([HumanMessage(content="hello"), AIMessage(content="hi")])
        runtime = _make_runtime()

        mock_memory_queue = MagicMock()
        mock_domain_queue = MagicMock()

        with (
            patch("deerflow.agents.middlewares.memory_middleware.get_memory_config", return_value=MemoryConfig(enabled=True)),
            patch("deerflow.agents.middlewares.memory_middleware.get_session_memory_config", return_value=SessionMemoryConfig(enabled=False)),
            patch("deerflow.agents.middlewares.memory_middleware.get_domain_memory_config", return_value=DomainMemoryConfig(enabled=False)),
            patch("deerflow.agents.middlewares.memory_middleware.get_memory_queue", return_value=mock_memory_queue),
            patch("deerflow.agents.middlewares.memory_middleware.get_domain_memory_queue", return_value=mock_domain_queue),
            patch("deerflow.agents.middlewares.memory_middleware.get_effective_user_id", return_value="user-1"),
        ):
            mw.after_agent(state, runtime)

        mock_memory_queue.add.assert_called_once()
        mock_domain_queue.add.assert_not_called()

    def test_after_agent_domain_queue_failure_does_not_affect_user_memory(self):
        """after_agent() continues even if domain queue raises an exception."""
        mw = MemoryMiddleware()
        state = _make_state([HumanMessage(content="hello"), AIMessage(content="hi")])
        runtime = _make_runtime()

        mock_memory_queue = MagicMock()
        mock_session_queue = MagicMock()
        mock_domain_queue = MagicMock()
        mock_domain_queue.add.side_effect = RuntimeError("domain queue boom")

        with (
            patch("deerflow.agents.middlewares.memory_middleware.get_memory_config", return_value=MemoryConfig(enabled=True)),
            patch("deerflow.agents.middlewares.memory_middleware.get_session_memory_config", return_value=SessionMemoryConfig(enabled=False)),
            patch("deerflow.agents.middlewares.memory_middleware.get_domain_memory_config", return_value=DomainMemoryConfig(enabled=True)),
            patch("deerflow.agents.middlewares.memory_middleware.get_memory_queue", return_value=mock_memory_queue),
            patch("deerflow.agents.middlewares.memory_middleware.get_session_memory_queue", return_value=mock_session_queue),
            patch("deerflow.agents.middlewares.memory_middleware.get_domain_memory_queue", return_value=mock_domain_queue),
            patch("deerflow.agents.middlewares.memory_middleware.get_effective_user_id", return_value="user-1"),
            patch("deerflow.agents.middlewares.memory_middleware.get_current_tenant_id", return_value="tenant-1"),
        ):
            result = mw.after_agent(state, runtime)

        assert result is None
        mock_memory_queue.add.assert_called_once()

    def test_after_agent_domain_queue_failure_does_not_affect_session_memory(self):
        """after_agent() session memory still works if domain queue raises an exception."""
        mw = MemoryMiddleware()
        state = _make_state([HumanMessage(content="hello"), AIMessage(content="hi")])
        runtime = _make_runtime()

        mock_memory_queue = MagicMock()
        mock_session_queue = MagicMock()
        mock_domain_queue = MagicMock()
        mock_domain_queue.add.side_effect = RuntimeError("domain queue boom")

        with (
            patch("deerflow.agents.middlewares.memory_middleware.get_memory_config", return_value=MemoryConfig(enabled=True)),
            patch("deerflow.agents.middlewares.memory_middleware.get_session_memory_config", return_value=SessionMemoryConfig(enabled=True)),
            patch("deerflow.agents.middlewares.memory_middleware.get_domain_memory_config", return_value=DomainMemoryConfig(enabled=True)),
            patch("deerflow.agents.middlewares.memory_middleware.get_memory_queue", return_value=mock_memory_queue),
            patch("deerflow.agents.middlewares.memory_middleware.get_session_memory_queue", return_value=mock_session_queue),
            patch("deerflow.agents.middlewares.memory_middleware.get_domain_memory_queue", return_value=mock_domain_queue),
            patch("deerflow.agents.middlewares.memory_middleware.get_effective_user_id", return_value="user-1"),
            patch("deerflow.agents.middlewares.memory_middleware.get_current_tenant_id", return_value="tenant-1"),
        ):
            result = mw.after_agent(state, runtime)

        assert result is None
        mock_memory_queue.add.assert_called_once()
        mock_session_queue.add.assert_called_once()

    def test_after_agent_all_three_queues_when_all_enabled(self):
        """after_agent() queues to user, session, and domain memory when all enabled."""
        mw = MemoryMiddleware()
        state = _make_state([HumanMessage(content="Pump A info"), AIMessage(content="Noted")])
        runtime = _make_runtime()

        mock_memory_queue = MagicMock()
        mock_session_queue = MagicMock()
        mock_domain_queue = MagicMock()

        with (
            patch("deerflow.agents.middlewares.memory_middleware.get_memory_config", return_value=MemoryConfig(enabled=True)),
            patch("deerflow.agents.middlewares.memory_middleware.get_session_memory_config", return_value=SessionMemoryConfig(enabled=True)),
            patch("deerflow.agents.middlewares.memory_middleware.get_domain_memory_config", return_value=DomainMemoryConfig(enabled=True)),
            patch("deerflow.agents.middlewares.memory_middleware.get_memory_queue", return_value=mock_memory_queue),
            patch("deerflow.agents.middlewares.memory_middleware.get_session_memory_queue", return_value=mock_session_queue),
            patch("deerflow.agents.middlewares.memory_middleware.get_domain_memory_queue", return_value=mock_domain_queue),
            patch("deerflow.agents.middlewares.memory_middleware.get_effective_user_id", return_value="user-1"),
            patch("deerflow.agents.middlewares.memory_middleware.get_current_tenant_id", return_value="tenant-1"),
        ):
            mw.after_agent(state, runtime)

        mock_memory_queue.add.assert_called_once()
        mock_session_queue.add.assert_called_once()
        mock_domain_queue.add.assert_called_once()
