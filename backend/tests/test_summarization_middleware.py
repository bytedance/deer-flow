from __future__ import annotations

from types import SimpleNamespace
from unittest import mock
from unittest.mock import MagicMock

import pytest
from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.constants import TAG_NOSTREAM

from deerflow.agents.memory.summarization_hook import memory_flush_hook
from deerflow.agents.middlewares.dynamic_context_middleware import _DYNAMIC_CONTEXT_REMINDER_KEY, DynamicContextMiddleware, is_dynamic_context_reminder
from deerflow.agents.middlewares.summarization_middleware import DeerFlowSummarizationMiddleware, SummarizationEvent, create_summarization_middleware
from deerflow.agents.thread_state import ThreadState
from deerflow.config.memory_config import MemoryConfig
from deerflow.config.summarization_config import SummarizationConfig


def _messages() -> list:
    return [
        HumanMessage(content="user-1"),
        AIMessage(content="assistant-1"),
        HumanMessage(content="user-2"),
        AIMessage(content="assistant-2"),
    ]


class _StaticChatModel(BaseChatModel):
    text: str = "ok"

    @property
    def _llm_type(self) -> str:
        return "static-test-chat-model"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self.text))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def _dynamic_context_reminder(msg_id: str = "reminder-1") -> SystemMessage:
    # Current production shape: a date SystemMessage carrying the authoritative
    # date in additional_kwargs (see DynamicContextMiddleware).
    return SystemMessage(
        content="<system-reminder>\n<current_date>2026-05-08, Friday</current_date>\n</system-reminder>",
        id=msg_id,
        additional_kwargs={"hide_from_ui": True, _DYNAMIC_CONTEXT_REMINDER_KEY: True, "reminder_date": "2026-05-08, Friday"},
    )


def _runtime(
    thread_id: str | None = "thread-1",
    agent_name: str | None = None,
    user_id: str | None = None,
) -> SimpleNamespace:
    context = {}
    if thread_id is not None:
        context["thread_id"] = thread_id
    if agent_name is not None:
        context["agent_name"] = agent_name
    if user_id is not None:
        context["user_id"] = user_id
    return SimpleNamespace(context=context)


def _middleware(
    *,
    before_summarization=None,
    trigger=("messages", 4),
    keep=("messages", 2),
) -> DeerFlowSummarizationMiddleware:
    model = MagicMock()
    model.invoke.return_value = SimpleNamespace(text="compressed summary")
    model.with_config.return_value = model
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
    assert result["summary_text"] == "compressed summary"
    assert [message.content for message in result["messages"][1:]] == ["user-2", "assistant-2"]


def test_summarization_middleware_emits_frontend_update_key_in_agent_stream() -> None:
    middleware = DeerFlowSummarizationMiddleware(
        model=_StaticChatModel(text="compressed summary"),
        trigger=("messages", 4),
        keep=("messages", 2),
        token_counter=len,
    )
    agent = create_agent(
        model=_StaticChatModel(text="done"),
        tools=[],
        middleware=[middleware],
        state_schema=ThreadState,
    )

    chunks = list(agent.stream({"messages": _messages()}, stream_mode="updates"))
    update = next(
        (chunk["DeerFlowSummarizationMiddleware.before_model"] for chunk in chunks if "DeerFlowSummarizationMiddleware.before_model" in chunk),
        None,
    )

    assert update is not None
    assert update["summary_text"] == "compressed summary"
    emitted = update["messages"]
    assert isinstance(emitted[0], RemoveMessage)
    assert all(not (isinstance(message, HumanMessage) and message.name == "summary") for message in emitted)


def test_summary_model_is_tagged_nostream_to_avoid_stream_pollution() -> None:
    tags_during_summary: list[list[str]] = []

    class _RecordingChatModel(_StaticChatModel):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            tags_during_summary.append(list(run_manager.tags) if run_manager else [])
            return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    model = _RecordingChatModel(text="compressed summary")
    middleware = DeerFlowSummarizationMiddleware(
        model=model,
        trigger=("messages", 4),
        keep=("messages", 2),
        token_counter=len,
    )

    # The dedicated summary model must carry TAG_NOSTREAM so LangGraph's
    # messages-tuple stream handler skips its tokens, while the raw model used by
    # the parent for profile / token inspection stays untagged.
    assert TAG_NOSTREAM in (middleware._summary_model.config.get("tags") or [])
    assert TAG_NOSTREAM not in (getattr(middleware.model, "config", {}).get("tags") or [])

    result = middleware.before_model({"messages": _messages()}, _runtime())

    # The summary LLM call must actually run with the nostream tag (this is what the
    # stream handler inspects), and the shared self.model must remain the raw,
    # untagged model so parent logic (profile / _get_ls_params) keeps working.
    assert tags_during_summary == [[TAG_NOSTREAM]]
    assert middleware.model is model
    assert result["summary_text"] == "compressed summary"


def test_summarization_does_not_mutate_shared_model_across_concurrent_runs() -> None:
    """Concurrent runs must not observe a swapped-out self.model during summarization.

    The agent/middleware instance is cached and reused, so summarization must never
    temporarily replace the shared self.model: doing so would leak the nostream
    RunnableBinding to other coroutines mid-flight and break parent logic that
    inspects the raw model (profile / _get_ls_params).
    """
    import asyncio

    observed_models: list[object] = []
    started = asyncio.Event()
    release = asyncio.Event()

    class _BlockingChatModel(_StaticChatModel):
        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            # Hold the summary call open so a concurrent run can inspect self.model.
            started.set()
            await release.wait()
            return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    model = _BlockingChatModel(text="compressed summary")
    middleware = DeerFlowSummarizationMiddleware(
        model=model,
        trigger=("messages", 4),
        keep=("messages", 2),
        token_counter=len,
    )

    async def _run() -> None:
        summarizing = asyncio.create_task(middleware.abefore_model({"messages": _messages()}, _runtime()))
        # Wait until the summary task reaches the blocked LLM call.
        await started.wait()
        # A concurrent run reads the shared model while summarization is in flight.
        observed_models.append(middleware.model)
        release.set()
        await summarizing

    asyncio.run(_run())

    assert observed_models == [model]


def test_raw_model_is_preserved_for_parent_profile_inspection() -> None:
    """self.model must stay the original model so attribute access does not drift."""
    model = _StaticChatModel(text="compressed summary")
    middleware = DeerFlowSummarizationMiddleware(
        model=model,
        trigger=("messages", 4),
        keep=("messages", 2),
        token_counter=len,
    )

    middleware.before_model({"messages": _messages()}, _runtime())

    # The shared field is never reassigned to the RunnableBinding.
    assert middleware.model is model
    assert middleware._summary_model is not model


def test_summary_model_preserves_existing_tags_when_adding_nostream() -> None:
    """Adding TAG_NOSTREAM must not clobber tags already bound on the model.

    lead_agent/agent.py binds "middleware:summarize" for RunJournal attribution. Because
    RunnableBinding.with_config shallow-merges config, the summary model must explicitly
    preserve existing tags instead of overwriting them with just [TAG_NOSTREAM].
    """
    tagged_model = _StaticChatModel(text="compressed summary").with_config(tags=["middleware:summarize"])
    middleware = DeerFlowSummarizationMiddleware(
        model=tagged_model,
        trigger=("messages", 4),
        keep=("messages", 2),
        token_counter=len,
    )

    summary_tags = middleware._summary_model.config.get("tags") or []
    assert "middleware:summarize" in summary_tags
    assert TAG_NOSTREAM in summary_tags
    # No duplicate TAG_NOSTREAM even if invoked when one was already present.
    assert summary_tags.count(TAG_NOSTREAM) == 1


def test_dynamic_context_reminder_is_preserved_across_summarization() -> None:
    captured: list[SummarizationEvent] = []
    middleware = _middleware(before_summarization=[captured.append])
    reminder = _dynamic_context_reminder()

    result = middleware.before_model(
        {
            "messages": [
                reminder,
                HumanMessage(content="user-1"),
                AIMessage(content="assistant-1"),
                HumanMessage(content="user-2"),
            ]
        },
        _runtime(),
    )

    assert len(captured) == 1
    assert [message.content for message in captured[0].messages_to_summarize] == ["user-1"]
    assert captured[0].preserved_messages[0] is reminder

    emitted = result["messages"]
    assert isinstance(emitted[0], RemoveMessage)
    assert emitted[1] is reminder

    followup_state = {"messages": [*emitted[1:], HumanMessage(content="Follow-up", id="msg-2")]}
    with mock.patch("deerflow.agents.middlewares.dynamic_context_middleware.datetime") as mock_dt:
        mock_dt.now.return_value.strftime.return_value = "2026-05-08, Friday"
        assert DynamicContextMiddleware().before_agent(followup_state, _runtime()) is None


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


def test_memory_flush_hook_passes_runtime_user_id(monkeypatch: pytest.MonkeyPatch) -> None:
    queue = MagicMock()
    monkeypatch.setattr("deerflow.agents.memory.summarization_hook.get_memory_config", lambda: MemoryConfig(enabled=True))
    monkeypatch.setattr("deerflow.agents.memory.summarization_hook.get_memory_queue", lambda: queue)

    memory_flush_hook(
        SummarizationEvent(
            messages_to_summarize=tuple(_messages()[:2]),
            preserved_messages=(),
            thread_id="main",
            agent_name="researcher",
            runtime=_runtime(thread_id="main", agent_name="researcher", user_id="alice"),
        )
    )

    queue.add_nowait.assert_called_once()
    assert queue.add_nowait.call_args.kwargs["user_id"] == "alice"


def test_id_swap_user_peer_is_preserved_across_summarization() -> None:
    """__user (untagged) must be rescued alongside its tagged ID-swap peers.

    The ID-swap triplet from _make_reminder_and_user_messages is:
    [SystemMessage(id=X, reminder=True), HumanMessage(id=X__memory, reminder=True),
     HumanMessage(id=X__user)] — only the first two are tagged. Without peer
    rescue, __user stays in to_summarize and is compressed into prose, orphaning
    the tagged messages and losing the user question from direct model context.
    """
    captured: list[SummarizationEvent] = []
    middleware = _middleware(before_summarization=[captured.append])

    # Build an ID-swap triplet (SystemMessage + __memory + __user)
    stable_id = "ctx-001"
    reminder_system = SystemMessage(
        content="<system-reminder>\n<current_date>2026-05-08, Friday</current_date>\n</system-reminder>",
        id=stable_id,
        additional_kwargs={"hide_from_ui": True, _DYNAMIC_CONTEXT_REMINDER_KEY: True},
    )
    memory_msg = HumanMessage(
        content="<memory>user preferences</memory>",
        id=f"{stable_id}__memory",
        additional_kwargs={"hide_from_ui": True, _DYNAMIC_CONTEXT_REMINDER_KEY: True},
    )
    user_msg = HumanMessage(
        content="What is the weather in Tokyo?",
        id=f"{stable_id}__user",
    )

    result = middleware.before_model(
        {
            "messages": [
                HumanMessage(content="older context"),
                reminder_system,
                memory_msg,
                user_msg,
                AIMessage(content="The weather is sunny.", id="ai-1"),
                HumanMessage(content="user-2"),
            ]
        },
        _runtime(),
    )

    assert len(captured) == 1
    # The __user message should NOT be in messages_to_summarize
    summarized_contents = [m.content for m in captured[0].messages_to_summarize]
    assert "What is the weather in Tokyo?" not in summarized_contents

    # All three triplet members should be in preserved_messages
    preserved_ids = [m.id for m in captured[0].preserved_messages]
    assert stable_id in preserved_ids
    assert f"{stable_id}__memory" in preserved_ids
    assert f"{stable_id}__user" in preserved_ids

    # The emitted state includes all three triplet members
    emitted = result["messages"]
    assert isinstance(emitted[0], RemoveMessage)
    # Find the triplet members in the emitted messages
    emitted_ids = [m.id for m in emitted[1:]]  # Skip RemoveMessage
    assert stable_id in emitted_ids
    assert f"{stable_id}__memory" in emitted_ids
    assert f"{stable_id}__user" in emitted_ids


def test_id_swap_user_peer_preserved_without_memory() -> None:
    """When there's no __memory in the triplet, __user is still rescued."""
    captured: list[SummarizationEvent] = []
    middleware = _middleware(before_summarization=[captured.append])

    stable_id = "ctx-002"
    reminder_system = SystemMessage(
        content="<system-reminder>\n<current_date>2026-05-09, Saturday</current_date>\n</system-reminder>",
        id=stable_id,
        additional_kwargs={"hide_from_ui": True, _DYNAMIC_CONTEXT_REMINDER_KEY: True},
    )
    user_msg = HumanMessage(
        content="How are you?",
        id=f"{stable_id}__user",
    )

    middleware.before_model(
        {
            "messages": [
                HumanMessage(content="older context"),
                reminder_system,
                user_msg,
                AIMessage(content="I'm fine.", id="ai-2"),
                HumanMessage(content="user-3"),
            ]
        },
        _runtime(),
    )

    assert len(captured) == 1
    summarized_contents = [m.content for m in captured[0].messages_to_summarize]
    assert "How are you?" not in summarized_contents

    preserved_ids = [m.id for m in captured[0].preserved_messages]
    assert stable_id in preserved_ids
    assert f"{stable_id}__user" in preserved_ids


def test_non_reminder_messages_with_double_underscore_id_not_rescued() -> None:
    """Messages whose IDs contain "__" but are NOT ID-swap peers are not rescued."""
    captured: list[SummarizationEvent] = []
    middleware = _middleware(before_summarization=[captured.append])

    # A normal reminder without any ID-swap peers
    reminder = _dynamic_context_reminder("standalone-reminder")
    # A message whose ID happens to contain "__" but is unrelated
    unrelated = HumanMessage(content="unrelated question", id="some-other__msg")

    middleware.before_model(
        {
            "messages": [
                reminder,
                unrelated,
                AIMessage(content="answer"),
                HumanMessage(content="user-2"),
            ]
        },
        _runtime(),
    )

    assert len(captured) == 1
    # The unrelated message is NOT rescued — it stays in to_summarize
    preserved_ids = [m.id for m in captured[0].preserved_messages]
    assert "some-other__msg" not in preserved_ids
    # Only the standalone reminder is rescued (no peer lookup triggered)
    assert "standalone-reminder" in preserved_ids


def test_multiple_id_swap_triplets_preserve_chronological_order() -> None:
    """When multiple ID-swap triplets sit in one summarization window, rescued
    messages must retain their original chronological order — not be scrambled
    by separating tagged reminders from untagged peers.

    Regression: the previous reminders+peers concatenation rescued as
    [Sys(base1), Sys(base2), Mem(base1), Mem(base2), User(base1), User(base2)],
    detaching each user question from its AI answer. The single-pass partition
    preserves [Sys(base1), Mem(base1), User(base1), Sys(base2), Mem(base2), User(base2)].
    """
    captured: list[SummarizationEvent] = []
    middleware = _middleware(before_summarization=[captured.append])

    # Two complete triplets (first-turn + midnight crossing) plus an AI reply
    # between them, all sitting before the summarization cutoff.
    base1 = "ctx-001"
    base2 = "ctx-002"
    reminder_1 = SystemMessage(
        content="<system-reminder>\n<current_date>2026-05-08, Friday</current_date>\n</system-reminder>",
        id=base1,
        additional_kwargs={"hide_from_ui": True, _DYNAMIC_CONTEXT_REMINDER_KEY: True},
    )
    memory_1 = HumanMessage(
        content="<memory>prefs v1</memory>",
        id=f"{base1}__memory",
        additional_kwargs={"hide_from_ui": True, _DYNAMIC_CONTEXT_REMINDER_KEY: True},
    )
    user_1 = HumanMessage(content="What is the weather?", id=f"{base1}__user")
    ai_1 = AIMessage(content="Sunny.", id="ai-1")

    reminder_2 = SystemMessage(
        content="<system-reminder>\n<current_date>2026-05-09, Saturday</current_date>\n</system-reminder>",
        id=base2,
        additional_kwargs={"hide_from_ui": True, _DYNAMIC_CONTEXT_REMINDER_KEY: True},
    )
    memory_2 = HumanMessage(
        content="<memory>prefs v2</memory>",
        id=f"{base2}__memory",
        additional_kwargs={"hide_from_ui": True, _DYNAMIC_CONTEXT_REMINDER_KEY: True},
    )
    user_2 = HumanMessage(content="How are you?", id=f"{base2}__user")
    ai_2 = AIMessage(content="Fine.", id="ai-2")

    middleware.before_model(
        {
            "messages": [
                reminder_1,
                memory_1,
                user_1,
                ai_1,
                reminder_2,
                memory_2,
                user_2,
                ai_2,
                HumanMessage(content="latest question"),
            ]
        },
        _runtime(),
    )

    assert len(captured) == 1
    # Rescued messages must appear in their original chronological order:
    # each triplet stays contiguous, not re-grouped by role.
    preserved = captured[0].preserved_messages
    rescued_ids = [m.id for m in preserved if m.id and (is_dynamic_context_reminder(m) or m.id in (f"{base1}__user", f"{base2}__user"))]
    assert rescued_ids == [
        base1,
        f"{base1}__memory",
        f"{base1}__user",
        base2,
        f"{base2}__memory",
        f"{base2}__user",
    ]


def test_factory_attaches_memory_flush_hook_by_default(monkeypatch):
    """The lead path keeps ``memory_flush_hook`` so pre-compaction messages
    persist into durable memory. Verified via the factory with memory enabled
    and the default ``skip_memory_flush=False``."""
    fake_model = MagicMock()
    fake_model.with_config.return_value = fake_model
    monkeypatch.setattr("deerflow.agents.middlewares.summarization_middleware.create_chat_model", lambda **kw: fake_model)

    app_config = SimpleNamespace(
        summarization=SummarizationConfig(enabled=True),
        memory=MemoryConfig(enabled=True),
    )
    middleware = create_summarization_middleware(app_config=app_config)

    assert middleware is not None
    assert memory_flush_hook in middleware._before_summarization_hooks


def test_factory_skip_memory_flush_omits_hook(monkeypatch):
    """``skip_memory_flush=True`` (the subagent path) must omit
    ``memory_flush_hook``: subagents share the parent's ``thread_id``, so
    without skipping the hook a subagent's internal turns would flush into the
    PARENT thread's durable memory (#3875 Phase 3 review)."""
    fake_model = MagicMock()
    fake_model.with_config.return_value = fake_model
    monkeypatch.setattr("deerflow.agents.middlewares.summarization_middleware.create_chat_model", lambda **kw: fake_model)

    app_config = SimpleNamespace(
        summarization=SummarizationConfig(enabled=True),
        memory=MemoryConfig(enabled=True),
    )
    middleware = create_summarization_middleware(app_config=app_config, skip_memory_flush=True)

    assert middleware is not None
    # memory.enabled is True but the hook is skipped — the whole point.
    assert memory_flush_hook not in middleware._before_summarization_hooks
    assert middleware._before_summarization_hooks == []
