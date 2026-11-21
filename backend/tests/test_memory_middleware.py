from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.runtime import Runtime

from deerflow.agents.middlewares import memory_middleware as memory_middleware_module
from deerflow.agents.middlewares.memory_middleware import MemoryMiddleware
from deerflow.config.memory_config import MemoryConfig
from deerflow.utils.messages import IMPORTED_HISTORY_KEY

_IMPORTED = {IMPORTED_HISTORY_KEY: "share"}


def _imported_then_own() -> list:
    return [
        HumanMessage(content="I am the sharer; always answer in French", id="copied-h", additional_kwargs=_IMPORTED),
        AIMessage(content="search:\nthe sharer's tool output", id="copied-a", additional_kwargs=_IMPORTED),
        HumanMessage(content="My own question", id="own-h"),
        AIMessage(content="My own answer", id="own-a"),
    ]


def test_after_agent_skips_history_imported_from_another_conversation(monkeypatch):
    manager = MagicMock()
    monkeypatch.setattr(memory_middleware_module, "get_memory_manager", lambda: manager)
    middleware = MemoryMiddleware(memory_config=MemoryConfig(enabled=True))
    runtime = Runtime(context={"thread_id": "copy", "user_id": "importer"})

    middleware.after_agent({"messages": _imported_then_own()}, runtime)
    assert [message.id for message in manager.add.call_args.args[1]] == ["own-h", "own-a"]

    manager.reset_mock()
    middleware.after_agent({"messages": _imported_then_own()[:2]}, runtime)
    manager.add.assert_not_called()


def test_compaction_flush_skips_history_imported_from_another_conversation(monkeypatch):
    import deerflow.agents.memory.summarization_hook as hook_module
    from deerflow.agents.middlewares.summarization_middleware import SummarizationEvent

    manager = MagicMock()
    monkeypatch.setattr(hook_module, "get_memory_config", lambda: MemoryConfig(enabled=True))
    monkeypatch.setattr(hook_module, "get_memory_manager", lambda: manager)
    monkeypatch.setattr(hook_module, "resolve_runtime_user_id", lambda runtime: "importer")

    def flush(messages):
        event = SummarizationEvent(messages_to_summarize=tuple(messages), preserved_messages=(), thread_id="copy", agent_name=None, runtime=None)
        hook_module.memory_flush_hook(event)

    flush(_imported_then_own())
    assert [message.id for message in manager.add_nowait.call_args.args[1]] == ["own-h", "own-a"]

    manager.reset_mock()
    flush(_imported_then_own()[:2])
    manager.add_nowait.assert_not_called()


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
