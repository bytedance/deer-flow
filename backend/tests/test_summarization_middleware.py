from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, ToolMessage

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


def _middleware(
    *,
    before_summarization=None,
    trigger=("messages", 4),
    keep=("messages", 2),
    skill_file_read_tool_names=None,
    preserve_recent_skill_count: int = 0,
    preserve_recent_skill_tokens: int = 0,
    preserve_recent_skill_tokens_per_skill: int = 0,
) -> DeerFlowSummarizationMiddleware:
    model = MagicMock()
    model.invoke.return_value = SimpleNamespace(text="compressed summary")
    return DeerFlowSummarizationMiddleware(
        model=model,
        trigger=trigger,
        keep=keep,
        token_counter=len,
        before_summarization=before_summarization,
        skill_file_read_tool_names=skill_file_read_tool_names,
        preserve_recent_skill_count=preserve_recent_skill_count,
        preserve_recent_skill_tokens=preserve_recent_skill_tokens,
        preserve_recent_skill_tokens_per_skill=preserve_recent_skill_tokens_per_skill,
    )


def _skill_read_call(tool_id: str, skill: str) -> dict:
    return {
        "name": "read_file",
        "id": tool_id,
        "args": {"path": f"/mnt/skills/public/{skill}/SKILL.md"},
    }


def _skill_conversation() -> list:
    return [
        HumanMessage(content="u1"),
        AIMessage(content="", tool_calls=[_skill_read_call("t1", "alpha")]),
        ToolMessage(content="alpha skill body", tool_call_id="t1"),
        HumanMessage(content="u2"),
        AIMessage(content="", tool_calls=[_skill_read_call("t2", "beta")]),
        ToolMessage(content="beta skill body", tool_call_id="t2"),
        HumanMessage(content="u3"),
        AIMessage(content="final"),
    ]


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


def test_skill_rescue_keeps_recent_skill_reads_out_of_summary() -> None:
    captured: list[SummarizationEvent] = []
    middleware = _middleware(
        before_summarization=[captured.append],
        trigger=("messages", 4),
        keep=("messages", 2),
        preserve_recent_skill_count=5,
        preserve_recent_skill_tokens=10_000,
        preserve_recent_skill_tokens_per_skill=10_000,
    )

    result = middleware.before_model({"messages": _skill_conversation()}, _runtime())

    assert len(captured) == 1
    summarized_ids = {id(m) for m in captured[0].messages_to_summarize}
    preserved = captured[0].preserved_messages

    # Both skill-read bundles should be rescued into preserved_messages,
    # tool_call ↔ tool_result pairs stay intact.
    assert any(isinstance(m, ToolMessage) and m.content == "alpha skill body" for m in preserved)
    assert any(isinstance(m, ToolMessage) and m.content == "beta skill body" for m in preserved)
    for m in preserved:
        if isinstance(m, ToolMessage) and m.content in {"alpha skill body", "beta skill body"}:
            assert id(m) not in summarized_ids

    # Preserved output order: rescued bundles first, then the tail kept by parent cutoff.
    contents = [getattr(m, "content", None) for m in preserved]
    assert contents[-2:] == ["u3", "final"]

    # The final emitted state should start with RemoveMessage + summary, then preserved messages.
    emitted = result["messages"]
    assert isinstance(emitted[0], RemoveMessage)
    assert emitted[1].content.startswith("Here is a summary")
    assert list(emitted[-2:]) == list(preserved[-2:])


def test_skill_rescue_respects_count_budget() -> None:
    captured: list[SummarizationEvent] = []
    middleware = _middleware(
        before_summarization=[captured.append],
        trigger=("messages", 4),
        keep=("messages", 2),
        preserve_recent_skill_count=1,
        preserve_recent_skill_tokens=10_000,
        preserve_recent_skill_tokens_per_skill=10_000,
    )

    middleware.before_model({"messages": _skill_conversation()}, _runtime())

    preserved = captured[0].preserved_messages
    summarized = captured[0].messages_to_summarize
    # Newest skill (beta) rescued; older skill (alpha) falls into summary.
    assert any(isinstance(m, ToolMessage) and m.content == "beta skill body" for m in preserved)
    assert not any(isinstance(m, ToolMessage) and m.content == "alpha skill body" for m in preserved)
    assert any(isinstance(m, ToolMessage) and m.content == "alpha skill body" for m in summarized)


def test_skill_rescue_uses_injected_skills_container_path() -> None:
    captured: list[SummarizationEvent] = []
    middleware = _middleware(
        before_summarization=[captured.append],
        trigger=("messages", 4),
        keep=("messages", 2),
        preserve_recent_skill_count=5,
        preserve_recent_skill_tokens=10_000,
        preserve_recent_skill_tokens_per_skill=10_000,
    )
    middleware._skills_container_path = "/custom/skills"
    messages = [
        HumanMessage(content="u1"),
        AIMessage(content="", tool_calls=[{"name": "read_file", "id": "t1", "args": {"path": "/custom/skills/demo/SKILL.md"}}]),
        ToolMessage(content="demo skill body", tool_call_id="t1"),
        HumanMessage(content="u2"),
        AIMessage(content="final"),
    ]

    middleware.before_model({"messages": messages}, _runtime())

    preserved = captured[0].preserved_messages
    assert any(isinstance(m, ToolMessage) and m.content == "demo skill body" for m in preserved)


def test_skill_rescue_uses_configured_skill_read_tool_names() -> None:
    captured: list[SummarizationEvent] = []
    middleware = _middleware(
        before_summarization=[captured.append],
        trigger=("messages", 4),
        keep=("messages", 2),
        skill_file_read_tool_names=["custom_read"],
        preserve_recent_skill_count=5,
        preserve_recent_skill_tokens=10_000,
        preserve_recent_skill_tokens_per_skill=10_000,
    )
    middleware._skills_container_path = "/custom/skills"
    messages = [
        HumanMessage(content="u1"),
        AIMessage(content="", tool_calls=[{"name": "custom_read", "id": "t1", "args": {"path": "/custom/skills/demo/SKILL.md"}}]),
        ToolMessage(content="demo skill body", tool_call_id="t1"),
        HumanMessage(content="u2"),
        AIMessage(content="final"),
    ]

    middleware.before_model({"messages": messages}, _runtime())

    preserved = captured[0].preserved_messages
    assert any(isinstance(m, ToolMessage) and m.content == "demo skill body" for m in preserved)


def test_skill_rescue_respects_per_skill_token_cap() -> None:
    captured: list[SummarizationEvent] = []
    middleware = _middleware(
        before_summarization=[captured.append],
        trigger=("messages", 4),
        keep=("messages", 2),
        preserve_recent_skill_count=5,
        preserve_recent_skill_tokens=10_000,
        # token_counter=len counts one token per message; per-skill cap of 0 rejects every bundle.
        preserve_recent_skill_tokens_per_skill=0,
    )

    middleware.before_model({"messages": _skill_conversation()}, _runtime())

    preserved = captured[0].preserved_messages
    assert not any(isinstance(m, ToolMessage) and m.content in {"alpha skill body", "beta skill body"} for m in preserved)


def test_skill_rescue_disabled_when_count_zero() -> None:
    captured: list[SummarizationEvent] = []
    middleware = _middleware(
        before_summarization=[captured.append],
        trigger=("messages", 4),
        keep=("messages", 2),
        preserve_recent_skill_count=0,
        preserve_recent_skill_tokens=10_000,
        preserve_recent_skill_tokens_per_skill=10_000,
    )

    middleware.before_model({"messages": _skill_conversation()}, _runtime())

    preserved = captured[0].preserved_messages
    assert not any(isinstance(m, ToolMessage) for m in preserved)


def test_skill_rescue_ignores_non_skill_tool_reads() -> None:
    captured: list[SummarizationEvent] = []
    middleware = _middleware(
        before_summarization=[captured.append],
        trigger=("messages", 4),
        keep=("messages", 2),
        preserve_recent_skill_count=5,
        preserve_recent_skill_tokens=10_000,
        preserve_recent_skill_tokens_per_skill=10_000,
    )

    messages = [
        HumanMessage(content="u1"),
        AIMessage(
            content="",
            tool_calls=[{"name": "read_file", "id": "t1", "args": {"path": "/mnt/user-data/workspace/notes.md"}}],
        ),
        ToolMessage(content="user notes", tool_call_id="t1"),
        HumanMessage(content="u2"),
        AIMessage(content="done"),
    ]

    middleware.before_model({"messages": messages}, _runtime())

    preserved = captured[0].preserved_messages
    assert not any(isinstance(m, ToolMessage) and m.content == "user notes" for m in preserved)


def test_skill_rescue_does_not_preserve_non_skill_outputs_from_mixed_tool_calls() -> None:
    captured: list[SummarizationEvent] = []
    middleware = _middleware(
        before_summarization=[captured.append],
        trigger=("messages", 4),
        keep=("messages", 2),
        preserve_recent_skill_count=5,
        preserve_recent_skill_tokens=10_000,
        preserve_recent_skill_tokens_per_skill=10_000,
    )

    messages = [
        HumanMessage(content="u1"),
        AIMessage(
            content="",
            tool_calls=[
                _skill_read_call("skill-1", "alpha"),
                {"name": "read_file", "id": "file-1", "args": {"path": "/mnt/user-data/workspace/notes.md"}},
            ],
        ),
        ToolMessage(content="alpha skill body", tool_call_id="skill-1"),
        ToolMessage(content="user notes", tool_call_id="file-1"),
        HumanMessage(content="u2"),
        AIMessage(content="done"),
    ]

    middleware.before_model({"messages": messages}, _runtime())

    preserved = captured[0].preserved_messages
    summarized = captured[0].messages_to_summarize

    preserved_ai = next(m for m in preserved if isinstance(m, AIMessage) and m.tool_calls)
    summarized_ai = next(m for m in summarized if isinstance(m, AIMessage) and m.tool_calls)

    assert [tc["id"] for tc in preserved_ai.tool_calls] == ["skill-1"]
    assert [tc["id"] for tc in summarized_ai.tool_calls] == ["file-1"]
    assert any(isinstance(m, ToolMessage) and m.content == "alpha skill body" for m in preserved)
    assert not any(isinstance(m, ToolMessage) and m.content == "user notes" for m in preserved)
    assert any(isinstance(m, ToolMessage) and m.content == "user notes" for m in summarized)


def test_skill_rescue_clears_content_on_rescued_ai_clone() -> None:
    captured: list[SummarizationEvent] = []
    middleware = _middleware(
        before_summarization=[captured.append],
        trigger=("messages", 4),
        keep=("messages", 2),
        preserve_recent_skill_count=5,
        preserve_recent_skill_tokens=10_000,
        preserve_recent_skill_tokens_per_skill=10_000,
    )

    messages = [
        HumanMessage(content="u1"),
        AIMessage(
            content="reading skill and notes",
            tool_calls=[
                _skill_read_call("skill-1", "alpha"),
                {"name": "read_file", "id": "file-1", "args": {"path": "/mnt/user-data/workspace/notes.md"}},
            ],
        ),
        ToolMessage(content="alpha skill body", tool_call_id="skill-1"),
        ToolMessage(content="user notes", tool_call_id="file-1"),
        HumanMessage(content="u2"),
        AIMessage(content="done"),
    ]

    middleware.before_model({"messages": messages}, _runtime())

    preserved = captured[0].preserved_messages
    summarized = captured[0].messages_to_summarize

    preserved_ai = next(m for m in preserved if isinstance(m, AIMessage) and m.tool_calls)
    summarized_ai = next(m for m in summarized if isinstance(m, AIMessage) and m.tool_calls)

    assert preserved_ai.content == ""
    assert summarized_ai.content == "reading skill and notes"


def test_skill_rescue_only_preserves_skill_calls_with_matched_tool_results() -> None:
    captured: list[SummarizationEvent] = []
    middleware = _middleware(
        before_summarization=[captured.append],
        trigger=("messages", 4),
        keep=("messages", 2),
        preserve_recent_skill_count=5,
        preserve_recent_skill_tokens=10_000,
        preserve_recent_skill_tokens_per_skill=10_000,
    )

    messages = [
        HumanMessage(content="u1"),
        AIMessage(
            content="",
            tool_calls=[
                _skill_read_call("skill-1", "alpha"),
                _skill_read_call("skill-2", "beta"),
            ],
        ),
        ToolMessage(content="alpha skill body", tool_call_id="skill-1"),
        HumanMessage(content="u2"),
        AIMessage(content="done"),
    ]

    middleware.before_model({"messages": messages}, _runtime())

    preserved = captured[0].preserved_messages
    summarized = captured[0].messages_to_summarize

    preserved_ai = next(m for m in preserved if isinstance(m, AIMessage) and m.tool_calls)
    summarized_ai = next(m for m in summarized if isinstance(m, AIMessage) and m.tool_calls)

    assert [tc["id"] for tc in preserved_ai.tool_calls] == ["skill-1"]
    assert [tc["id"] for tc in summarized_ai.tool_calls] == ["skill-2"]
    assert any(isinstance(m, ToolMessage) and m.content == "alpha skill body" for m in preserved)
    assert not any(isinstance(m, ToolMessage) and getattr(m, "tool_call_id", None) == "skill-2" for m in preserved)


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
