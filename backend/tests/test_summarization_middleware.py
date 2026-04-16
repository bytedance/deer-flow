from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage

from deerflow.agents.memory.summarization_hook import memory_flush_hook
from deerflow.agents.middlewares.summarization_middleware import DeerFlowSummarizationMiddleware, SummarizationEvent
from deerflow.config.memory_config import MemoryConfig


def _messages() -> list:
    return [
        HumanMessage(content="user-1"),
        AIMessage(content="assistant-1"),
        HumanMessage(content="user-2"),
        AIMessage(content="assistant-2"),
    ]


def _runtime(thread_id: str | None = "thread-1", agent_name: str | None = None) -> SimpleNamespace:
    context = {}
    if thread_id is not None:
        context["thread_id"] = thread_id
    if agent_name is not None:
        context["agent_name"] = agent_name
    return SimpleNamespace(context=context)


def _middleware(*, before_summarization=None, trigger=("messages", 4), keep=("messages", 2)) -> DeerFlowSummarizationMiddleware:
    model = MagicMock()
    model.invoke.return_value = SimpleNamespace(text="compressed summary")
    return DeerFlowSummarizationMiddleware(
        model=model,
        trigger=trigger,
        keep=keep,
        token_counter=len,
        before_summarization=before_summarization,
    )


def test_before_summarization_hook_receives_messages_before_compression() -> None:
    captured: list[SummarizationEvent] = []
    middleware = _middleware(before_summarization=[captured.append])

    result = middleware.before_model({"messages": _messages()}, _runtime())

    assert len(captured) == 1
    assert [message.content for message in captured[0].messages_to_summarize] == ["user-1", "assistant-1"]
    assert [message.content for message in captured[0].preserved_messages] == ["user-2", "assistant-2"]
    assert captured[0].thread_id == "thread-1"
    assert captured[0].agent_name is None
    assert isinstance(result["messages"][0], RemoveMessage)
    assert result["messages"][1].content.startswith("Here is a summary")


def test_before_summarization_hook_not_called_when_threshold_not_met() -> None:
    captured: list[SummarizationEvent] = []
    middleware = _middleware(before_summarization=[captured.append], trigger=("messages", 10))

    result = middleware.before_model({"messages": _messages()}, _runtime())

    assert captured == []
    assert result is None


def test_before_summarization_hook_exception_does_not_block_compression(caplog: pytest.LogCaptureFixture) -> None:
    def _broken_hook(_: SummarizationEvent) -> None:
        raise RuntimeError("hook failure")

    middleware = _middleware(before_summarization=[_broken_hook])

    with caplog.at_level("ERROR"):
        result = middleware.before_model({"messages": _messages()}, _runtime())

    assert "before_summarization hook _broken_hook failed" in caplog.text
    assert isinstance(result["messages"][0], RemoveMessage)


def test_multiple_before_summarization_hooks_run_in_registration_order() -> None:
    call_order: list[str] = []

    def _hook(name: str):
        return lambda _: call_order.append(name)

    middleware = _middleware(before_summarization=[_hook("first"), _hook("second"), _hook("third")])

    middleware.before_model({"messages": _messages()}, _runtime())

    assert call_order == ["first", "second", "third"]


@pytest.mark.anyio
async def test_abefore_model_calls_hooks_same_as_sync() -> None:
    captured: list[SummarizationEvent] = []
    middleware = _middleware(before_summarization=[captured.append])

    await middleware.abefore_model({"messages": _messages()}, _runtime())

    assert len(captured) == 1
    assert [message.content for message in captured[0].messages_to_summarize] == ["user-1", "assistant-1"]


def test_memory_flush_hook_skips_when_memory_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    queue = MagicMock()
    monkeypatch.setattr("deerflow.agents.memory.summarization_hook.get_memory_config", lambda: MemoryConfig(enabled=False))
    monkeypatch.setattr("deerflow.agents.memory.summarization_hook.get_memory_queue", lambda: queue)

    memory_flush_hook(
        SummarizationEvent(
            messages_to_summarize=tuple(_messages()[:2]),
            preserved_messages=(),
            thread_id="thread-1",
            agent_name=None,
            runtime=_runtime(),
        )
    )

    queue.add_nowait.assert_not_called()


def test_memory_flush_hook_skips_when_thread_id_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    queue = MagicMock()
    monkeypatch.setattr("deerflow.agents.memory.summarization_hook.get_memory_config", lambda: MemoryConfig(enabled=True))
    monkeypatch.setattr("deerflow.agents.memory.summarization_hook.get_memory_queue", lambda: queue)

    memory_flush_hook(
        SummarizationEvent(
            messages_to_summarize=tuple(_messages()[:2]),
            preserved_messages=(),
            thread_id=None,
            agent_name=None,
            runtime=_runtime(None),
        )
    )

    queue.add_nowait.assert_not_called()


def test_memory_flush_hook_enqueues_filtered_messages_and_flushes(monkeypatch: pytest.MonkeyPatch) -> None:
    queue = MagicMock()
    messages = [
        HumanMessage(content="Question"),
        AIMessage(content="Calling tool", tool_calls=[{"name": "search", "id": "tool-1", "args": {}}]),
        AIMessage(content="Final answer"),
    ]
    monkeypatch.setattr("deerflow.agents.memory.summarization_hook.get_memory_config", lambda: MemoryConfig(enabled=True))
    monkeypatch.setattr("deerflow.agents.memory.summarization_hook.get_memory_queue", lambda: queue)

    memory_flush_hook(
        SummarizationEvent(
            messages_to_summarize=tuple(messages),
            preserved_messages=(),
            thread_id="thread-1",
            agent_name=None,
            runtime=_runtime(),
        )
    )

    queue.add_nowait.assert_called_once()
    add_kwargs = queue.add_nowait.call_args.kwargs
    assert add_kwargs["thread_id"] == "thread-1"
    assert [message.content for message in add_kwargs["messages"]] == ["Question", "Final answer"]
    assert add_kwargs["correction_detected"] is False
    assert add_kwargs["reinforcement_detected"] is False


def test_memory_flush_hook_preserves_agent_scoped_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    queue = MagicMock()
    monkeypatch.setattr("deerflow.agents.memory.summarization_hook.get_memory_config", lambda: MemoryConfig(enabled=True))
    monkeypatch.setattr("deerflow.agents.memory.summarization_hook.get_memory_queue", lambda: queue)

    memory_flush_hook(
        SummarizationEvent(
            messages_to_summarize=tuple(_messages()[:2]),
            preserved_messages=(),
            thread_id="thread-1",
            agent_name="research-agent",
            runtime=_runtime(agent_name="research-agent"),
        )
    )

    queue.add_nowait.assert_called_once()
    assert queue.add_nowait.call_args.kwargs["agent_name"] == "research-agent"
