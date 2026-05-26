"""Integration tests for session memory layer.

These tests verify end-to-end behavior of the session memory system
using mocked storage backends.
"""

import json
from unittest.mock import MagicMock, Mock, patch

import pytest

from deerflow.agents.memory.retrieval import (
    _session_cache,
    compose_memory_for_prompt,
    get_session_context,
)
from deerflow.agents.memory.session_queue import SessionMemoryUpdateQueue
from deerflow.agents.memory.session_storage import (
    SessionStorage,
    create_empty_session_memory,
)
from deerflow.agents.memory.updater import MemoryUpdater
from deerflow.config.memory_config import MemoryConfig
from deerflow.config.session_memory_config import (
    SessionMemoryConfig,
    set_session_memory_config,
)


@pytest.fixture(autouse=True)
def _reset_cache():
    _session_cache.clear()
    yield
    _session_cache.clear()


@pytest.fixture(autouse=True)
def _enable_session_memory():
    original = SessionMemoryConfig(enabled=True)
    set_session_memory_config(original)
    yield
    set_session_memory_config(SessionMemoryConfig())


def _make_mock_storage(data_store: dict):
    """Create a mock SessionStorage backed by a dict."""
    storage = Mock(spec=SessionStorage)

    def load(thread_id, *, user_id=None, agent_name=None):
        key = (user_id or "", thread_id)
        return data_store.get(key, create_empty_session_memory())

    def save(memory_data, thread_id, *, user_id=None, agent_name=None):
        key = (user_id or "", thread_id)
        data_store[key] = memory_data
        return True

    storage.load = Mock(side_effect=load)
    storage.save = Mock(side_effect=save)
    return storage


class TestSessionMemoryIntegration:
    """End-to-end session memory integration tests."""

    def test_new_thread_creates_session_memory(self):
        """New thread with messages creates session memory."""
        store: dict = {}
        mock_storage = _make_mock_storage(store)

        updater = MemoryUpdater()
        messages = [
            Mock(type="human", content="Debug the auth issue"),
            Mock(type="ai", content="I'll help investigate the JWT token"),
        ]

        mock_model = Mock()
        mock_model.invoke = Mock(return_value=Mock(content=json.dumps({
            "sessionContext": {
                "summary": "Debugging JWT auth issue",
                "shouldUpdate": True,
            },
            "newFacts": [
                {"content": "JWT token issue in auth module", "category": "context", "confidence": 0.9},
            ],
            "factsToRemove": [],
        })))

        with (
            patch("deerflow.agents.memory.updater.get_session_storage", return_value=mock_storage),
            patch.object(updater, "_get_model", return_value=mock_model),
        ):
            result = updater.update_session_memory(
                messages=messages,
                thread_id="thread-new",
                user_id="user-1",
            )

        assert result is True
        saved = store[("user-1", "thread-new")]
        assert saved["session_context"]["summary"] == "Debugging JWT auth issue"
        assert len(saved["facts"]) == 1

    def test_multiple_threads_isolated(self):
        """Session memory is isolated between different threads."""
        store: dict = {}
        mock_storage = _make_mock_storage(store)

        with patch("deerflow.agents.memory.session_storage.get_session_storage", return_value=mock_storage):
            ctx1 = get_session_context("thread-a", user_id="user-1")
            ctx2 = get_session_context("thread-b", user_id="user-1")

        assert ctx1 == ""
        assert ctx2 == ""
        assert mock_storage.load.call_count == 2

    def test_session_memory_write_failure_does_not_affect_user_memory(self):
        """Session memory failure is isolated from user memory writes."""
        from deerflow.agents.memory.queue import get_memory_queue
        from deerflow.agents.memory.session_queue import get_session_memory_queue
        from deerflow.agents.middlewares.memory_middleware import MemoryMiddleware
        from langchain_core.messages import AIMessage, HumanMessage

        mw = MemoryMiddleware()
        state = {"messages": [HumanMessage(content="hello"), AIMessage(content="hi")]}
        runtime = MagicMock()
        runtime.context = {"thread_id": "thread-1"}

        mock_memory_queue = MagicMock()
        mock_session_queue = MagicMock()
        mock_session_queue.add.side_effect = RuntimeError("session write failed")

        with (
            patch("deerflow.agents.middlewares.memory_middleware.get_memory_config", return_value=MemoryConfig(enabled=True)),
            patch("deerflow.agents.middlewares.memory_middleware.get_session_memory_config", return_value=SessionMemoryConfig(enabled=True)),
            patch("deerflow.agents.middlewares.memory_middleware.get_memory_queue", return_value=mock_memory_queue),
            patch("deerflow.agents.middlewares.memory_middleware.get_session_memory_queue", return_value=mock_session_queue),
            patch("deerflow.agents.middlewares.memory_middleware.get_effective_user_id", return_value="user-1"),
        ):
            result = mw.after_agent(state, runtime)

        assert result is None
        mock_memory_queue.add.assert_called_once()

    def test_prompt_composition_with_both_memories(self):
        """Prompt composition includes both User and Session memory."""
        store: dict = {
            ("user-1", "thread-1"): {
                "session_context": {"summary": "Working on API integration"},
                "facts": [
                    {"content": "REST endpoint at /api/v2", "category": "context", "confidence": 0.9},
                ],
            },
        }
        mock_storage = _make_mock_storage(store)

        with (
            patch("deerflow.config.memory_config.get_memory_config", return_value=MemoryConfig(enabled=True, injection_enabled=True)),
            patch("deerflow.agents.memory.retrieval.get_session_memory_config", return_value=SessionMemoryConfig(enabled=True, injection_enabled=True)),
            patch("deerflow.agents.memory.get_memory_data", return_value={"user": {"workContext": {"summary": "Backend dev"}}}),
            patch("deerflow.agents.memory.format_memory_for_injection", return_value="Work: Backend dev"),
            patch("deerflow.agents.memory.session_storage.get_session_storage", return_value=mock_storage),
        ):
            result = compose_memory_for_prompt(thread_id="thread-1", user_id="user-1")

        assert "User context:" in result
        assert "Work: Backend dev" in result
        assert "Session context:" in result
        assert "API integration" in result
        assert "REST endpoint" in result


class TestSessionMemoryQueueIntegration:
    """Integration tests for session memory queue processing."""

    def test_queue_processes_and_calls_updater(self):
        """Queue processes messages and calls update_session_from_conversation."""
        set_session_memory_config(SessionMemoryConfig(enabled=True, debounce_seconds=1))

        queue = SessionMemoryUpdateQueue()
        mock_update = MagicMock(return_value=True)

        with patch("deerflow.agents.memory.updater.update_session_from_conversation", mock_update):
            with (
                patch("deerflow.agents.memory.session_queue.get_session_memory_config", return_value=SessionMemoryConfig(enabled=True, debounce_seconds=1)),
                patch.object(queue, "_reset_timer"),
            ):
                queue.add(
                    thread_id="thread-1",
                    messages=[Mock(type="human", content="test")],
                    user_id="user-1",
                )

            queue.flush()

        mock_update.assert_called_once()
        call_kwargs = mock_update.call_args.kwargs
        assert call_kwargs["thread_id"] == "thread-1"
        assert call_kwargs["user_id"] == "user-1"
