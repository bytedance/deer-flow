from types import SimpleNamespace
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.memory.runtime import is_runtime_memory_injection_enabled
from deerflow.agents.middlewares.memory_middleware import MemoryMiddleware
from deerflow.config.memory_config import MemoryConfig


def _state():
    return {
        "messages": [
            HumanMessage(content="Remember that I prefer Python."),
            AIMessage(content="Noted."),
        ]
    }


def test_runtime_memory_injection_only_skips_explicit_false():
    assert is_runtime_memory_injection_enabled(SimpleNamespace(context={})) is True
    assert is_runtime_memory_injection_enabled(SimpleNamespace(context={"memory_enabled": False})) is False
    assert is_runtime_memory_injection_enabled(SimpleNamespace(context={"memory_enabled": True})) is True


def test_memory_middleware_queues_when_runtime_memory_context_is_absent(monkeypatch):
    queue = MagicMock()
    monkeypatch.setattr("deerflow.agents.middlewares.memory_middleware.get_memory_queue", lambda: queue)
    monkeypatch.setattr("deerflow.agents.middlewares.memory_middleware.get_effective_user_id", lambda: "user-1")

    middleware = MemoryMiddleware(memory_config=MemoryConfig(enabled=True))
    middleware.after_agent(_state(), runtime=SimpleNamespace(context={"thread_id": "thread-1"}))

    queue.add.assert_called_once()
    assert queue.add.call_args.kwargs["thread_id"] == "thread-1"
    assert queue.add.call_args.kwargs["user_id"] == "user-1"


def test_memory_middleware_queues_when_runtime_memory_enabled(monkeypatch):
    queue = MagicMock()
    monkeypatch.setattr("deerflow.agents.middlewares.memory_middleware.get_memory_queue", lambda: queue)
    monkeypatch.setattr("deerflow.agents.middlewares.memory_middleware.get_effective_user_id", lambda: "user-1")

    middleware = MemoryMiddleware(memory_config=MemoryConfig(enabled=True))
    middleware.after_agent(
        _state(),
        runtime=SimpleNamespace(context={"thread_id": "thread-1", "memory_enabled": True}),
    )

    queue.add.assert_called_once()
    assert queue.add.call_args.kwargs["thread_id"] == "thread-1"
    assert queue.add.call_args.kwargs["user_id"] == "user-1"
