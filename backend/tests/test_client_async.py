"""Native asynchronous embedded-client contracts, using compiled LangGraph graphs."""

import asyncio
import threading
from collections.abc import Callable
from typing import Annotated, TypedDict
from unittest.mock import AsyncMock, Mock

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, AnyMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.runtime import Runtime

from deerflow.client import DeerFlowClient
from deerflow.trace_context import get_current_trace_id


class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


def make_client(monkeypatch, node: Callable, *, checkpointer=None):
    graph = StateGraph(State, context_schema=dict)
    graph.add_node("answer", node)
    graph.add_edge(START, "answer")
    graph.add_edge("answer", END)
    compiled = graph.compile(checkpointer=checkpointer if checkpointer is not None else InMemorySaver())
    # Keep the real native graph, reducer, streaming and checkpoint paths. Only
    # model/tool assembly is replaced: these tests must not discover live MCPs.
    client = object.__new__(DeerFlowClient)
    client._agent = compiled
    client._checkpointer = compiled.checkpointer
    client._checkpoint_channel_mode = "full"
    client._checkpoint_snapshot_frequency = 10
    client._model_name = "test-model"
    client._effective_model_name = "test-model"
    client._thinking_enabled = True
    client._subagent_enabled = False
    client._plan_mode = False
    client._agent_name = None
    client._environment = None
    client._thread_incarnations = {}
    client._assembly_lock = threading.RLock()
    client._ensure_agent = Mock()
    monkeypatch.setattr("deerflow.client.build_tracing_callbacks", lambda: [])
    monkeypatch.setattr(compiled, "stream", Mock(side_effect=AssertionError("use the native async graph")))
    return client


@pytest.mark.asyncio
async def test_native_async_stream_preserves_deltas_custom_events_and_history(monkeypatch):
    model = FakeListChatModel(responses=["first answer", "second answer"])
    contexts = []

    async def answer(state: State, runtime: Runtime[dict]):
        contexts.append(dict(runtime.context))
        get_stream_writer()({"type": "test.progress", "phase": "answer"})
        return {"messages": [await model.ainvoke(state["messages"])]}

    client = make_client(monkeypatch, answer)
    events = [event async for event in client.astream("hello", thread_id="async-turns", user_id="alice")]
    deltas = [event.data["content"] for event in events if event.type == "messages-tuple" and event.data["type"] == "ai"]
    assert "".join(deltas) == "first answer"
    assert any(event.type == "custom" and event.data["type"] == "test.progress" for event in events)
    assert events[-1].type == "end"
    assert contexts[0]["user_id"] == "alice"
    assert await client.achat("again", thread_id="async-turns", user_id="alice") == "second answer"
    snapshot = await client._agent.aget_state({"configurable": {"thread_id": "async-turns"}})
    assert len(snapshot.values["messages"]) == 4


@pytest.mark.asyncio
async def test_async_assembly_does_not_block_loop_or_mix_callers(monkeypatch):
    loop_thread = threading.get_ident()
    assembly_threads = []
    observed = []

    async def answer(state: State, runtime: Runtime[dict]):
        observed.append((runtime.context["user_id"], get_current_trace_id()))
        return {"messages": [AIMessage(content=runtime.context["user_id"])]}

    client = make_client(monkeypatch, answer)

    def ensure(config, *, context):
        assembly_threads.append(threading.get_ident())
        assert threading.get_ident() != loop_thread

    client._ensure_agent = ensure
    assert await asyncio.gather(
        client.achat("hello", thread_id="alice-thread", user_id="alice"),
        client.achat("hello", thread_id="bob-thread", user_id="bob"),
    ) == ["alice", "bob"]
    assert len(assembly_threads) == 2
    assert {owner for owner, _ in observed} == {"alice", "bob"}
    assert all(trace for _, trace in observed)
    assert observed[0][1] != observed[1][1]
    assert get_current_trace_id() is None


@pytest.mark.asyncio
async def test_cancelling_async_stream_cancels_graph_and_releases_lease(monkeypatch):
    started = asyncio.Event()
    cancelled = asyncio.Event()
    release = AsyncMock()
    monkeypatch.setattr("deerflow.sandbox.lease.release_sandbox_execution_lease_async", release)

    async def answer(state: State):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    client = make_client(monkeypatch, answer)
    emitted = []

    async def consume():
        async for event in client.astream("hello", thread_id="cancel-thread"):
            emitted.append(event)

    task = asyncio.create_task(consume())
    waiting = asyncio.create_task(started.wait())
    try:
        done, _ = await asyncio.wait({task, waiting}, timeout=5, return_when=asyncio.FIRST_COMPLETED)
        if task in done:
            await task
        assert started.is_set()
    finally:
        waiting.cancel()
        await asyncio.gather(waiting, return_exceptions=True)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled.is_set()
    release.assert_awaited_once()
    assert release.call_args.args[0]["thread_id"] == "cancel-thread"
    assert not any(event.type == "end" for event in emitted)


@pytest.mark.asyncio
async def test_explicit_async_close_releases_lease_and_restores_caller_trace(monkeypatch):
    release = AsyncMock()
    monkeypatch.setattr("deerflow.sandbox.lease.release_sandbox_execution_lease_async", release)

    async def answer(state: State):
        return {"messages": [AIMessage(content="answer")]}

    client = make_client(monkeypatch, answer)
    events = client.astream("hello", thread_id="closed-thread")
    await anext(events)
    assert get_current_trace_id() is None
    await events.aclose()
    await events.aclose()
    release.assert_awaited_once()
    assert get_current_trace_id() is None


@pytest.mark.asyncio
async def test_async_graph_failure_propagates_and_still_releases_lease(monkeypatch):
    release = AsyncMock()
    monkeypatch.setattr("deerflow.sandbox.lease.release_sandbox_execution_lease_async", release)

    async def answer(state: State):
        raise ValueError("synthetic graph failure")

    client = make_client(monkeypatch, answer)
    with pytest.raises(ValueError, match="synthetic graph failure"):
        await client.achat("hello", thread_id="failed-thread")
    release.assert_awaited_once()


@pytest.mark.asyncio
async def test_native_async_sqlite_checkpoints_keep_both_turns(monkeypatch, tmp_path):
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    async def answer(state: State):
        return {"messages": [AIMessage(content="answer")]}

    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "checkpoints.sqlite")) as saver:
        client = make_client(monkeypatch, answer, checkpointer=saver)
        assert await client.achat("first", thread_id="sqlite-thread") == "answer"
        assert await client.achat("second", thread_id="sqlite-thread") == "answer"
        snapshot = await client._agent.aget_state({"configurable": {"thread_id": "sqlite-thread"}})
        assert len(snapshot.values["messages"]) == 4


@pytest.mark.asyncio
async def test_sync_only_checkpointer_is_rejected_before_graph_execution(monkeypatch, tmp_path):
    from langgraph.checkpoint.sqlite import SqliteSaver

    called = Mock()

    async def answer(state: State):
        called()
        return {"messages": [AIMessage(content="answer")]}

    with SqliteSaver.from_conn_string(str(tmp_path / "sync.sqlite")) as saver:
        client = make_client(monkeypatch, answer, checkpointer=saver)
        with pytest.raises(ValueError, match="async-capable checkpointer"):
            await client.achat("hello", thread_id="sync-checkpointer")
    called.assert_not_called()


@pytest.mark.asyncio
async def test_repeated_cancellation_drains_async_lease_cleanup(monkeypatch):
    started = asyncio.Event()
    releasing = asyncio.Event()
    finish_release = asyncio.Event()

    async def release(context):
        releasing.set()
        await finish_release.wait()

    release_mock = AsyncMock(side_effect=release)
    monkeypatch.setattr("deerflow.sandbox.lease.release_sandbox_execution_lease_async", release_mock)

    async def answer(state: State):
        started.set()
        await asyncio.Event().wait()

    client = make_client(monkeypatch, answer)
    task = asyncio.create_task(client.achat("hello", thread_id="repeated-cancel"))
    try:
        await asyncio.wait_for(started.wait(), 5)
        task.cancel()
        await asyncio.wait_for(releasing.wait(), 5)
        task.cancel()
        assert not task.done()
    finally:
        finish_release.set()
        if not task.done():
            task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    release_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_cleanup_failure_does_not_replace_successful_answer(monkeypatch):
    monkeypatch.setattr(
        "deerflow.sandbox.lease.release_sandbox_execution_lease_async",
        AsyncMock(side_effect=RuntimeError("synthetic cleanup failure")),
    )

    async def answer(state: State):
        return {"messages": [AIMessage(content="answer")]}

    assert await make_client(monkeypatch, answer).achat("hello", thread_id="cleanup-failure") == "answer"


@pytest.mark.asyncio
async def test_overlapping_assembly_keeps_each_callers_graph(monkeypatch):
    async def first(state: State):
        return {"messages": [AIMessage(content="first model")]}

    async def second(state: State):
        return {"messages": [AIMessage(content="second model")]}

    client = make_client(monkeypatch, first)
    first_graph = client._agent
    second_graph = make_client(monkeypatch, second)._agent

    def ensure(config, *, context):
        client._agent = first_graph if context["user_id"] == "alice" else second_graph

    client._ensure_agent = ensure
    assert await asyncio.gather(
        client.achat("hello", thread_id="model-a", user_id="alice"),
        client.achat("hello", thread_id="model-b", user_id="bob"),
    ) == ["first model", "second model"]


@pytest.mark.asyncio
async def test_closing_live_graph_releases_real_execution_lease(monkeypatch):
    from deerflow.sandbox.lease import ensure_sandbox_lease_owner, get_sandbox_lease_manager
    from deerflow.sandbox.sandbox_provider import reset_sandbox_provider, set_sandbox_provider

    provider = Mock()
    provider.get.return_value = Mock()
    manager = get_sandbox_lease_manager(provider)
    owners = []

    async def answer(state: State, runtime: Runtime[dict]):
        context = runtime.context
        owner = ensure_sandbox_lease_owner(context)
        assert owner is not None
        owners.append(owner)
        context["sandbox_id"] = "shared"
        await manager.retain_async(owner, "shared", thread_id=context["thread_id"], user_id=context["user_id"])
        get_stream_writer()({"type": "lease.acquired"})
        await asyncio.Event().wait()

    set_sandbox_provider(provider)
    events = make_client(monkeypatch, answer).astream("hello", thread_id="real-lease")
    try:
        async for event in events:
            if event.type == "custom":
                break
        assert len(owners) == 1
        assert manager.binding_for(owners[0]) == "shared"
    finally:
        try:
            await events.aclose()
        finally:
            reset_sandbox_provider()
    assert manager.binding_for(owners[0]) is None
    provider.get.return_value.release_command_scope.assert_called_once_with(owners[0])
    provider.release.assert_called_once_with("shared")


@pytest.mark.asyncio
async def test_cancelled_cold_assembly_never_starts_inference(monkeypatch):
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    called = Mock()

    async def answer(state: State):
        called()
        return {"messages": [AIMessage(content="answer")]}

    client = make_client(monkeypatch, answer)

    def ensure(config, *, context):
        started.set()
        try:
            assert release.wait(5)
        finally:
            finished.set()

    client._ensure_agent = ensure
    task = asyncio.create_task(client.achat("hello", thread_id="cancel-assembly"))
    try:
        assert await asyncio.to_thread(started.wait, 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()
        assert await asyncio.to_thread(finished.wait, 5)
    called.assert_not_called()
