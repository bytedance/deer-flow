from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.runtime import Runtime

from deerflow.agents.middlewares import memory_middleware as memory_middleware_module
from deerflow.agents.middlewares.memory_middleware import MemoryMiddleware
from deerflow.config.memory_config import MemoryConfig


def test_after_agent_queues_memory_under_runtime_user(monkeypatch):
    manager = MagicMock()
    monkeypatch.setattr(memory_middleware_module, "get_memory_manager", lambda: manager)

    middleware = MemoryMiddleware(
        agent_name="researcher",
        memory_config=MemoryConfig(enabled=True),
    )
    runtime = Runtime(
        context={
            "thread_id": "thread-123",
            "user_id": "runtime-user",
        }
    )

    result = middleware.after_agent(
        {
            "messages": [
                HumanMessage(content="Remember this"),
                AIMessage(content="Understood"),
            ]
        },
        runtime,
    )

    assert result is None
    manager.add.assert_called_once()
    call = manager.add.call_args
    assert call.args[:2] == (
        "thread-123",
        [
            HumanMessage(content="Remember this"),
            AIMessage(content="Understood"),
        ],
    )
    assert call.kwargs["agent_name"] == "researcher"
    assert call.kwargs["user_id"] == "runtime-user"
    # Entry points always bind a trace id, so the memory queue -- which fires
    # on a Timer thread that inherits no ContextVars -- always gets a real one
    # captured at enqueue time rather than a None it would have to guard.
    assert call.kwargs["trace_id"]
