from __future__ import annotations

from types import SimpleNamespace
from typing import Annotated, NotRequired, TypedDict

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph.message import add_messages
from langgraph.types import Overwrite

from app.gateway import services as gateway_services
from deerflow.agents.middlewares.summarization_middleware import SummaryGenerationError
from deerflow.runtime import context_compaction
from deerflow.runtime.checkpoint_state import CheckpointStateAccessor
from deerflow.runtime.context_compaction import ContextCompactionFailed, compact_thread_context


class _FakeAccessor:
    def __init__(self, values: dict) -> None:
        self.snapshot = SimpleNamespace(
            values=values,
            config={
                "configurable": {
                    "thread_id": "thread-1",
                    "checkpoint_id": "ckpt-old",
                    "checkpoint_ns": "",
                }
            },
            metadata={"step": 4, "created_at": "2026-07-06T00:00:00+00:00"},
        )
        self.update_args = None

    async def aget(self, _config):
        return self.snapshot

    async def aupdate(self, config, values, *, as_node=None):
        self.update_args = (config, values, as_node)
        return {
            "configurable": {
                "thread_id": config["configurable"]["thread_id"],
                "checkpoint_ns": "",
                "checkpoint_id": "ckpt-compacted",
            }
        }


class _FakeCompactionMiddleware:
    def __init__(self, *, should_compact: bool = True) -> None:
        self.should_compact = should_compact
        self.prepare_calls = 0
        self.runtime_contexts: list[dict] = []

    def _prepare_compaction(self, state, *, force=False):
        self.prepare_calls += 1
        if not self.should_compact:
            return None
        return (state["messages"][:-1], state["messages"][-1:], state.get("summary_text"), 123)

    async def acompact_state(self, state, runtime, *, force=False, raise_on_failure=False):
        self.runtime_contexts.append(dict(runtime.context))
        prepared = self._prepare_compaction(state, force=force)
        if prepared is None:
            return None
        messages_to_summarize, preserved_messages, _previous_summary, total_tokens = prepared
        return SimpleNamespace(
            summary_text="COMPRESSED SUMMARY",
            messages_to_summarize=tuple(messages_to_summarize),
            preserved_messages=tuple(preserved_messages),
            total_tokens=total_tokens,
        )


@pytest.mark.asyncio
async def test_compact_thread_context_reads_materialized_state_and_overwrites_messages(monkeypatch):
    messages = [
        HumanMessage(content="old question"),
        AIMessage(content="old answer"),
        HumanMessage(content="latest question"),
    ]
    accessor = _FakeAccessor(
        {
            "messages": messages,
            "summary_text": "OLD SUMMARY",
            "sandbox": object(),
        }
    )
    middleware = _FakeCompactionMiddleware()
    monkeypatch.setattr(
        context_compaction,
        "_create_compaction_middleware",
        lambda **_kwargs: middleware,
    )

    result = await compact_thread_context(
        accessor,
        "thread-1",
        app_config=SimpleNamespace(),
        user_id="user-1",
        agent_name="research-agent",
    )

    assert result.compacted is True
    assert result.removed_message_count == 2
    assert result.preserved_message_count == 1
    assert result.summary_updated is True
    assert result.checkpoint_id == "ckpt-compacted"
    assert result.total_tokens == 123

    assert accessor.update_args is not None
    update_config, written_values, as_node = accessor.update_args
    assert update_config == accessor.snapshot.config
    assert isinstance(written_values["messages"], Overwrite)
    assert written_values["messages"].value == [messages[-1]]
    assert written_values["summary_text"] == "COMPRESSED SUMMARY"
    assert as_node == "manual_compaction"
    assert middleware.prepare_calls == 1
    assert middleware.runtime_contexts == [
        {"thread_id": "thread-1", "user_id": "user-1", "agent_name": "research-agent"},
    ]


@pytest.mark.asyncio
async def test_compact_thread_context_real_mutation_graph_finishes_without_scheduling(monkeypatch):
    messages = [
        HumanMessage(id="h1", content="old question"),
        AIMessage(id="a1", content="old answer"),
        HumanMessage(id="h2", content="latest question"),
    ]
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                checkpointer=InMemorySaver(),
                checkpoint_channel_mode="delta",
                store=None,
            )
        )
    )
    seed_accessor, seed_config = gateway_services.build_checkpoint_state_mutation_accessor(
        request,
        thread_id="thread-real-compaction",
        as_node="seed",
    )
    await seed_accessor.aupdate(
        seed_config,
        {
            "messages": Overwrite(messages),
            "summary_text": "OLD SUMMARY",
        },
        as_node="seed",
    )
    accessor, config = gateway_services.build_checkpoint_state_mutation_accessor(
        request,
        thread_id="thread-real-compaction",
        as_node="manual_compaction",
    )
    monkeypatch.setattr(
        context_compaction,
        "_create_compaction_middleware",
        lambda **_kwargs: _FakeCompactionMiddleware(),
    )

    result = await compact_thread_context(
        accessor,
        "thread-real-compaction",
        app_config=SimpleNamespace(),
    )
    snapshot = await accessor.aget(config)

    assert result.compacted is True
    assert [message.id for message in snapshot.values["messages"]] == ["h2"]
    assert snapshot.values["summary_text"] == "COMPRESSED SUMMARY"
    assert snapshot.next == ()


@pytest.mark.asyncio
async def test_compact_thread_context_preserves_middleware_contributed_channels(monkeypatch):
    """Compaction must not drop channels the base ThreadState does not know.

    Contract lock for fork inheritance: the compaction write carries only
    messages + summary_text (base channels), so a middleware-contributed
    channel survives even though the mutation graph compiles with the base
    schema. If LangGraph ever stops cloning unknown channels into forked
    checkpoints, this test fails before production state is lost.
    """
    from deerflow.runtime.checkpoint_state import build_state_mutation_graph

    class ExtensionState(TypedDict):
        messages: Annotated[list, add_messages]
        memory_notes: NotRequired[str]

    messages = [
        HumanMessage(id="h1", content="old question"),
        AIMessage(id="a1", content="old answer"),
        HumanMessage(id="h2", content="latest question"),
    ]
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                checkpointer=InMemorySaver(),
                checkpoint_channel_mode="full",
                store=None,
            )
        )
    )
    seed_graph = build_state_mutation_graph("seed", "full", ExtensionState)
    seed_accessor = CheckpointStateAccessor.bind(seed_graph, request.app.state.checkpointer, mode="full")
    seed_config = {"configurable": {"thread_id": "thread-ext-compaction", "checkpoint_ns": ""}}
    await seed_accessor.aupdate(
        seed_config,
        {"messages": messages, "memory_notes": "extension-value"},
        as_node="seed",
    )

    # Production path: compact uses the base-schema mutation accessor.
    accessor, config = gateway_services.build_checkpoint_state_mutation_accessor(
        request,
        thread_id="thread-ext-compaction",
        as_node="manual_compaction",
    )
    monkeypatch.setattr(
        context_compaction,
        "_create_compaction_middleware",
        lambda **_kwargs: _FakeCompactionMiddleware(),
    )

    result = await compact_thread_context(
        accessor,
        "thread-ext-compaction",
        app_config=SimpleNamespace(),
    )
    snapshot = await seed_accessor.aget(config)

    assert result.compacted is True
    assert [message.id for message in snapshot.values["messages"]] == ["h2"]
    assert snapshot.values["memory_notes"] == "extension-value"


@pytest.mark.asyncio
async def test_compact_thread_context_returns_noop_without_writing(monkeypatch):
    accessor = _FakeAccessor(
        {
            "messages": [HumanMessage(content="latest only")],
        }
    )
    middleware = _FakeCompactionMiddleware(should_compact=False)
    monkeypatch.setattr(
        context_compaction,
        "_create_compaction_middleware",
        lambda **_kwargs: middleware,
    )

    result = await compact_thread_context(accessor, "thread-1", app_config=SimpleNamespace())

    assert result.compacted is False
    assert result.reason == "not_enough_messages"
    assert accessor.update_args is None
    assert middleware.prepare_calls == 1


@pytest.mark.asyncio
async def test_compact_thread_context_raises_on_summary_generation_failure(monkeypatch):
    """A compressible thread whose summary LLM fails (after the run-model fallback) is
    a real failure: it must surface via the already-consumed ``ContextCompactionFailed``
    path (HTTP 500 -> frontend error toast), not a ``compacted=False`` result that the
    frontend renders as the benign "does not need compaction" toast."""
    accessor = _FakeAccessor(
        {
            "messages": [
                HumanMessage(content="old question"),
                AIMessage(content="old answer"),
                HumanMessage(content="latest question"),
            ],
        }
    )

    captured: dict[str, object] = {}

    class _FailingMiddleware:
        async def acompact_state(self, state, runtime, *, force=False, raise_on_failure=False):
            # The manual path must opt into raise_on_failure regardless of force.
            captured["raise_on_failure"] = raise_on_failure
            raise SummaryGenerationError("summary generation failed")

    monkeypatch.setattr(
        context_compaction,
        "_create_compaction_middleware",
        lambda **_kwargs: _FailingMiddleware(),
    )

    with pytest.raises(ContextCompactionFailed):
        await compact_thread_context(accessor, "thread-1", app_config=SimpleNamespace())

    assert captured["raise_on_failure"] is True
    assert accessor.update_args is None


def _model_app_config(*names):
    models = [SimpleNamespace(name=n) for n in names]
    return SimpleNamespace(
        models=models,
        get_model_config=lambda n: next((m for m in models if m.name == n), None),
    )


def test_resolve_thread_model_name_prefers_agent_model(monkeypatch):
    """Manual /compact resolves the thread agent's own model so a custom-agent thread
    summarizes with its model, not config.models[0] — the manual-path ownership rule."""
    import deerflow.config.agents_config as agents_config

    monkeypatch.setattr(agents_config, "load_agent_config", lambda name, **_kw: SimpleNamespace(model="agent-model"))
    app_config = _model_app_config("default-model", "agent-model")

    assert context_compaction._resolve_thread_model_name("research-agent", app_config) == "agent-model"


def test_resolve_thread_model_name_falls_back_to_default(monkeypatch):
    """No agent, an unloadable agent config, or an agent whose model is not configured
    all resolve to the default model rather than failing compaction."""
    import deerflow.config.agents_config as agents_config

    app_config = _model_app_config("default-model")

    # No agent name → default.
    assert context_compaction._resolve_thread_model_name(None, app_config) == "default-model"

    # Agent config cannot be loaded (missing/unparseable) → default, not a crash.
    def _raise(name, **_kw):
        raise FileNotFoundError("agent directory not found")

    monkeypatch.setattr(agents_config, "load_agent_config", _raise)
    assert context_compaction._resolve_thread_model_name("ghost-agent", app_config) == "default-model"

    # Agent's model is not a configured model → default.
    monkeypatch.setattr(agents_config, "load_agent_config", lambda name, **_kw: SimpleNamespace(model="unconfigured"))
    assert context_compaction._resolve_thread_model_name("x-agent", app_config) == "default-model"
