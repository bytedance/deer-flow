from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.runtime import Runtime

from deerflow.agents.middlewares import memory_middleware as memory_middleware_module
from deerflow.agents.middlewares.memory_middleware import MemoryMiddleware
from deerflow.config.memory_config import MemoryConfig
from deerflow.utils.messages import FOLLOWS_IMPORTED_HISTORY_KEY, IMPORTED_HISTORY_KEY

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

    state_messages = _imported_then_own()
    middleware.after_agent({"messages": state_messages}, runtime)
    queued = manager.add.call_args.args[1]
    assert [message.id for message in queued] == ["own-h", "own-a"]
    # Extraction learns that the conversation continues someone else's; the
    # thread state does not change.
    assert all(message.additional_kwargs[FOLLOWS_IMPORTED_HISTORY_KEY] is True for message in queued)
    assert not any(FOLLOWS_IMPORTED_HISTORY_KEY in message.additional_kwargs for message in state_messages)

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
    queued = manager.add_nowait.call_args.args[1]
    assert [message.id for message in queued] == ["own-h", "own-a"]
    assert all(message.additional_kwargs[FOLLOWS_IMPORTED_HISTORY_KEY] is True for message in queued)

    manager.reset_mock()
    flush(_imported_then_own()[:2])
    manager.add_nowait.assert_not_called()


def test_own_conversation_is_queued_without_the_imported_history_mark(monkeypatch):
    manager = MagicMock()
    monkeypatch.setattr(memory_middleware_module, "get_memory_manager", lambda: manager)
    middleware = MemoryMiddleware(memory_config=MemoryConfig(enabled=True))

    middleware.after_agent({"messages": _imported_then_own()[2:]}, Runtime(context={"thread_id": "own", "user_id": "u"}))

    assert not any(FOLLOWS_IMPORTED_HISTORY_KEY in message.additional_kwargs for message in manager.add.call_args.args[1])


def test_share_copy_channel_marks_capture_after_compaction(monkeypatch):
    from deerflow.utils.messages import IMPORTED_HISTORY_CHANNEL

    manager = MagicMock()
    monkeypatch.setattr(memory_middleware_module, "get_memory_manager", lambda: manager)
    middleware = MemoryMiddleware(memory_config=MemoryConfig(enabled=True))

    # Compaction removed the copied turns; only the state channel says this is a copy.
    state = {"messages": _imported_then_own()[2:], IMPORTED_HISTORY_CHANNEL: "share"}
    middleware.after_agent(state, Runtime(context={"thread_id": "copy", "user_id": "u"}))

    assert all(message.additional_kwargs[FOLLOWS_IMPORTED_HISTORY_KEY] is True for message in manager.add.call_args.args[1])


def test_compaction_flush_marks_capture_from_the_share_copy_channel(monkeypatch):
    import deerflow.agents.memory.summarization_hook as hook_module
    from deerflow.agents.middlewares.summarization_middleware import SummarizationEvent

    manager = MagicMock()
    monkeypatch.setattr(hook_module, "get_memory_config", lambda: MemoryConfig(enabled=True))
    monkeypatch.setattr(hook_module, "get_memory_manager", lambda: manager)
    monkeypatch.setattr(hook_module, "resolve_runtime_user_id", lambda runtime: "importer")

    # The batch holds only the visitor's turns; only the event's channel value says this is a copy.
    runtime = Runtime(context={"thread_id": "copy"})
    event = SummarizationEvent(messages_to_summarize=tuple(_imported_then_own()[2:]), preserved_messages=(), thread_id="copy", agent_name=None, runtime=runtime, imported_history="share")
    hook_module.memory_flush_hook(event)

    assert all(message.additional_kwargs[FOLLOWS_IMPORTED_HISTORY_KEY] is True for message in manager.add_nowait.call_args.args[1])


def test_unresolved_share_copy_is_not_captured(monkeypatch):
    import deerflow.agents.memory.summarization_hook as hook_module
    from deerflow.agents.middlewares.summarization_middleware import SummarizationEvent
    from deerflow.utils.messages import IMPORTED_HISTORY_CHANNEL, IMPORTED_HISTORY_UNRESOLVED

    manager = MagicMock()
    monkeypatch.setattr(memory_middleware_module, "get_memory_manager", lambda: manager)
    monkeypatch.setattr(hook_module, "get_memory_config", lambda: MemoryConfig(enabled=True))
    monkeypatch.setattr(hook_module, "get_memory_manager", lambda: manager)
    monkeypatch.setattr(hook_module, "resolve_runtime_user_id", lambda runtime: "importer")
    # Unmarked copied turns cannot be told from the owner's, so neither path queues anything.
    unmarked = [HumanMessage(content="I am the sharer", id="h"), AIMessage(content="Hello, sharer", id="a")]

    MemoryMiddleware(memory_config=MemoryConfig(enabled=True)).after_agent({"messages": unmarked, IMPORTED_HISTORY_CHANNEL: IMPORTED_HISTORY_UNRESOLVED}, Runtime(context={"thread_id": "copy", "user_id": "u"}))
    hook_module.memory_flush_hook(
        SummarizationEvent(messages_to_summarize=tuple(unmarked), preserved_messages=(), thread_id="copy", agent_name=None, runtime=Runtime(context={"thread_id": "copy"}), imported_history=IMPORTED_HISTORY_UNRESOLVED)
    )

    manager.add.assert_not_called()
    manager.add_nowait.assert_not_called()


def test_deermem_prompt_warns_that_restated_copied_details_are_not_the_users():
    from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig
    from deerflow.agents.memory.backends.deermem.deermem.core.storage import create_empty_memory
    from deerflow.agents.memory.backends.deermem.deermem.core.updater import MemoryUpdater

    storage = MagicMock()
    storage.load.return_value = create_empty_memory()
    updater = MemoryUpdater(DeerMemConfig(), storage)
    own = [HumanMessage(content="Summarize this conversation", id="h"), AIMessage(content="Lin, CFO at Contoso, asked for French.", id="a")]
    marked = [message.model_copy(update={"additional_kwargs": {FOLLOWS_IMPORTED_HISTORY_KEY: True}}) for message in own]

    _, plain_prompt = updater._prepare_update_prompt(own, None, frozenset())
    _, marked_prompt = updater._prepare_update_prompt(marked, None, frozenset())

    assert "another person's conversation" not in plain_prompt[1].content
    assert "another person's conversation" in marked_prompt[1].content
    # The note is per-conversation data, so the cached system text stays the same.
    assert marked_prompt[0].content == plain_prompt[0].content


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
