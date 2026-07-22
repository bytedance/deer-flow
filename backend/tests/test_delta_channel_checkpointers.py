"""DeltaChannel migration, replay, and storage-shape contracts on real saver backends.

These tests pin the LangGraph 1.2 DeltaChannel upgrade path that production
relies on:

- full -> delta migration on the same thread (old plain-value blobs seed the
  delta channel transparently),
- deterministic materialization with stable message ids (ids are stamped into
  the persisted writes by ``put_writes``/``ensure_message_ids``),
- the on-disk storage shape (non-snapshot checkpoints omit ``messages`` from
  ``channel_values``; snapshot checkpoints store a ``_DeltaSnapshot`` blob),
- non-Delta raw writers (goal / run-duration metadata / interrupted-title
  helper) preserving Delta ancestry and the downgrade markers.

Every contract runs against InMemorySaver, AsyncSqliteSaver, and - when
``TEST_POSTGRES_URI`` is set - AsyncPostgresSaver, because each backend
implements blob/version handling slightly differently.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Annotated, Any, TypedDict
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, RemoveMessage
from langgraph.channels import DeltaChannel
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.types import _DeltaSnapshot
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import Overwrite

from deerflow.agents.goal_state import GoalState
from deerflow.agents.thread_state import DeltaThreadState, merge_message_writes
from deerflow.runtime.checkpoint_mode import CHECKPOINT_MODE_METADATA_KEY, checkpoint_tuple_uses_delta
from deerflow.runtime.checkpoint_state import CheckpointStateAccessor
from deerflow.runtime.goal import write_thread_goal
from deerflow.runtime.runs.worker import _ensure_interrupted_title, persist_run_durations


class FullState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


class DeltaState(TypedDict):
    messages: Annotated[
        list[AnyMessage],
        DeltaChannel(merge_message_writes, snapshot_frequency=2),
    ]


def _thread_id() -> str:
    return f"delta-contract-{uuid4().hex}"


def _config(thread_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id}}


def _noop(state: dict[str, Any]) -> dict[str, Any]:
    return {}


def _build_graph(schema: Any, checkpointer: Any) -> Any:
    builder = StateGraph(schema)
    builder.add_node("noop", _noop)
    builder.set_entry_point("noop")
    builder.set_finish_point("noop")
    return builder.compile(checkpointer=checkpointer)


def _goal(objective: str) -> GoalState:
    return {
        "objective": objective,
        "status": "active",
        "created_at": "2026-07-18T00:00:00+00:00",
        "updated_at": "2026-07-18T00:00:00+00:00",
        "continuation_count": 0,
        "max_continuations": 3,
        "no_progress_count": 0,
        "max_no_progress_continuations": 2,
    }


class _SaverEnv:
    """One saver instance with a reopen() that simulates a process restart.

    Reopening swaps in a brand-new saver over the same bytes (SQLite file or
    Postgres schema) so replay-after-reopen contracts prove persistence, not
    in-process caching. InMemorySaver keeps no external bytes, so reopen is a
    no-op stand-in there.
    """

    def __init__(self, kind: str, open_saver: Callable[[], Any]) -> None:
        self.kind = kind
        self._open_saver = open_saver
        self._cm: Any | None = None
        self.saver: Any | None = None

    async def __aenter__(self) -> _SaverEnv:
        self._cm = self._open_saver()
        self.saver = await self._cm.__aenter__()
        setup = getattr(self.saver, "setup", None)
        if setup is not None:
            await setup()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._cm is not None:
            await self._cm.__aexit__(*exc)
            self._cm = None
            self.saver = None

    async def reopen(self) -> None:
        if self.kind == "memory":
            return
        await self._cm.__aexit__(None, None, None)
        self._cm = self._open_saver()
        self.saver = await self._cm.__aenter__()


@asynccontextmanager
async def _open_sqlite(db_path: Any) -> AsyncIterator[Any]:
    async with AsyncSqliteSaver.from_conn_string(str(db_path)) as saver:
        await saver.setup()
        yield saver


@asynccontextmanager
async def _open_postgres(uri: str) -> AsyncIterator[Any]:
    aio = pytest.importorskip("langgraph.checkpoint.postgres.aio", reason="postgres extra not installed")
    async with aio.AsyncPostgresSaver.from_conn_string(uri) as saver:
        await saver.setup()
        yield saver


@pytest.fixture(params=["memory", "sqlite", "postgres"])
async def saver_env(request: pytest.FixtureRequest, tmp_path: Any) -> AsyncIterator[_SaverEnv]:
    kind = request.param
    if kind == "memory":
        saver = InMemorySaver()

        @asynccontextmanager
        async def open_memory() -> AsyncIterator[Any]:
            yield saver

        open_saver = open_memory
    elif kind == "sqlite":
        db_path = tmp_path / "delta-contract.sqlite"

        def open_sqlite() -> Any:
            return _open_sqlite(db_path)

        open_saver = open_sqlite
    else:
        uri = os.environ.get("TEST_POSTGRES_URI")
        if not uri:
            pytest.skip("TEST_POSTGRES_URI is not set")

        def open_postgres() -> Any:
            return _open_postgres(uri)

        open_saver = open_postgres

    async with _SaverEnv(kind, open_saver) as env:
        yield env


@pytest.mark.anyio
async def test_full_to_delta_migration_replays_on_same_thread(saver_env: _SaverEnv) -> None:
    """A thread written by a full (pre-delta) graph must keep replaying after
    the process swaps to a delta graph: the old plain-value ``messages`` blob
    seeds the delta channel, and later delta writes append on top."""
    thread_id = _thread_id()
    config = _config(thread_id)

    full_graph = _build_graph(FullState, saver_env.saver)
    await full_graph.ainvoke({"messages": [HumanMessage(id="h1", content="seed from full mode")]}, config)

    delta_graph = _build_graph(DeltaState, saver_env.saver)
    delta_accessor = CheckpointStateAccessor.bind(delta_graph, saver_env.saver, mode="delta")

    migrated = await delta_accessor.aget(config)
    assert [m.id for m in migrated.values["messages"]] == ["h1"]
    assert migrated.values["messages"][0].content == "seed from full mode"

    await delta_graph.ainvoke({"messages": [AIMessage(id="a1", content="delta reply")]}, config)

    await saver_env.reopen()
    delta_graph = _build_graph(DeltaState, saver_env.saver)
    delta_accessor = CheckpointStateAccessor.bind(delta_graph, saver_env.saver, mode="delta")

    replayed = await delta_accessor.aget(config)
    assert [m.id for m in replayed.values["messages"]] == ["h1", "a1"]
    assert [m.content for m in replayed.values["messages"]] == ["seed from full mode", "delta reply"]


@pytest.mark.anyio
async def test_materialization_is_deterministic_and_message_ids_are_stable(saver_env: _SaverEnv) -> None:
    """Materializing the same thread twice - and once more after a saver
    reopen - must produce identical values, and the id LangGraph stamps onto
    an id-less message must survive persistence so it can drive RemoveMessage."""
    thread_id = _thread_id()
    config = _config(thread_id)
    graph = _build_graph(DeltaState, saver_env.saver)
    accessor = CheckpointStateAccessor.bind(graph, saver_env.saver, mode="delta")

    await graph.ainvoke({"messages": [HumanMessage(content="no id on purpose")]}, config)

    first = await accessor.aget(config)
    second = await accessor.aget(config)
    assert first.values == second.values

    persisted_id = first.values["messages"][0].id
    assert persisted_id

    await saver_env.reopen()
    graph = _build_graph(DeltaState, saver_env.saver)
    accessor = CheckpointStateAccessor.bind(graph, saver_env.saver, mode="delta")

    reopened = await accessor.aget(config)
    assert reopened.values == first.values
    assert reopened.values["messages"][0].id == persisted_id

    await graph.ainvoke({"messages": [RemoveMessage(id=persisted_id)]}, config)
    after_remove = await accessor.aget(config)
    assert after_remove.values["messages"] == []


@pytest.mark.anyio
async def test_delta_storage_shape_and_snapshot_cadence(saver_env: _SaverEnv) -> None:
    """Non-snapshot checkpoints must not carry ``messages`` in channel_values
    (that is the whole storage win); every ``snapshot_frequency`` updates the
    checkpoint carries a ``_DeltaSnapshot`` blob instead, and materialization
    stays correct across both shapes."""
    thread_id = _thread_id()
    config = _config(thread_id)
    graph = _build_graph(DeltaState, saver_env.saver)
    accessor = CheckpointStateAccessor.bind(graph, saver_env.saver, mode="delta")

    await graph.ainvoke({"messages": [HumanMessage(id="m1", content="one")]}, config)
    first_tuple = await saver_env.saver.aget_tuple(config)
    assert first_tuple is not None
    assert "messages" not in first_tuple.checkpoint["channel_values"]
    # The node's output persists as pending writes attached to the checkpoint
    # saved *before* its superstep (an ancestor of the latest checkpoint).
    chain_has_messages_write = False
    async for chain_tuple in saver_env.saver.alist(config):
        if any(channel == "messages" for _, channel, _ in chain_tuple.pending_writes or []):
            chain_has_messages_write = True
            break
    assert chain_has_messages_write

    # Second update crosses snapshot_frequency=2 -> one checkpoint on the
    # chain carries a _DeltaSnapshot blob for messages. (Which checkpoint
    # reassembles it into channel_values differs per saver: InMemorySaver
    # resolves the versioned blob on the latest checkpoint, AsyncSqliteSaver
    # on its parent. The cadence contract is that the snapshot exists.)
    await graph.ainvoke({"messages": [AIMessage(id="m2", content="two")]}, config)
    snapshot_found = False
    async for chain_tuple in saver_env.saver.alist(config):
        if isinstance(chain_tuple.checkpoint["channel_values"].get("messages"), _DeltaSnapshot):
            snapshot_found = True
            break
    assert snapshot_found

    snapshot = await accessor.aget(config)
    assert [m.id for m in snapshot.values["messages"]] == ["m1", "m2"]
    assert [m.content for m in snapshot.values["messages"]] == ["one", "two"]


@pytest.mark.anyio
async def test_non_delta_writers_preserve_delta_messages_and_markers(saver_env: _SaverEnv) -> None:
    """Raw checkpoint writers that never touch the messages channel (thread
    goal, run-duration metadata, interrupted-title helper) must not sever the
    Delta parent lineage or drop the downgrade markers. Regression: a raw
    ``aput`` whose write_config omits ``checkpoint_id`` stores a parentless
    checkpoint; replay from it then walks an empty ancestor chain and the
    whole message history silently disappears."""
    thread_id = _thread_id()
    config = _config(thread_id)
    write_config = {**config, "metadata": {CHECKPOINT_MODE_METADATA_KEY: "delta"}}
    graph = _build_graph(DeltaThreadState, saver_env.saver)
    accessor = CheckpointStateAccessor.bind(graph, saver_env.saver, mode="delta")

    await graph.ainvoke({"messages": Overwrite([HumanMessage(id="u1", content="hello goal writer")])}, write_config)
    await graph.ainvoke({"messages": [AIMessage(id="a1", content="reply")]}, write_config)

    await write_thread_goal(saver_env.saver, thread_id, _goal("keep messages alive"))
    durations_written = await persist_run_durations(
        checkpointer=saver_env.saver,
        thread_id=thread_id,
        durations={"run-1": 7},
    )
    assert durations_written
    # Delta checkpoints carry no messages in channel_values, so the title
    # helper has nothing to derive from and must stay inert (no write).
    title = await _ensure_interrupted_title(checkpointer=saver_env.saver, thread_id=thread_id, app_config=None)
    assert title is None

    await saver_env.reopen()
    graph = _build_graph(DeltaThreadState, saver_env.saver)
    accessor = CheckpointStateAccessor.bind(graph, saver_env.saver, mode="delta")

    latest_tuple = await saver_env.saver.aget_tuple(config)
    assert latest_tuple is not None

    # Production materialized read path (same one the Gateway uses).
    snapshot = await accessor.aget(config)
    assert [m.id for m in snapshot.values["messages"]] == ["u1", "a1"]
    assert [m.content for m in snapshot.values["messages"]] == ["hello goal writer", "reply"]

    assert checkpoint_tuple_uses_delta(latest_tuple)
    assert latest_tuple.metadata.get(CHECKPOINT_MODE_METADATA_KEY) == "delta"
    assert latest_tuple.metadata.get("run_durations", {}).get("run-1") == 7


# ---------------------------------------------------------------------------
# InMemorySaver delta-history patch guards (deerflow.checkpoint_patches)
# ---------------------------------------------------------------------------


def test_inmemory_delta_history_patch_is_active() -> None:
    """The compatibility patch must be applied in every test/app process."""
    from langgraph.checkpoint.memory import InMemorySaver

    from deerflow import checkpoint_patches

    assert getattr(InMemorySaver, checkpoint_patches._PATCH_FLAG, False) is True
    assert InMemorySaver.get_delta_channel_history is checkpoint_patches._get_delta_channel_history_via_base
    assert InMemorySaver.aget_delta_channel_history is checkpoint_patches._aget_delta_channel_history_via_base


def test_inmemory_delta_history_patch_stands_down_without_upstream_override(monkeypatch) -> None:
    """If upstream removes its (buggy) override, the patch must not reinstall."""
    from langgraph.checkpoint.memory import InMemorySaver

    from deerflow import checkpoint_patches

    monkeypatch.setattr(checkpoint_patches, "_upstream_override_present", lambda: False)
    monkeypatch.delattr(InMemorySaver, checkpoint_patches._PATCH_FLAG, raising=False)
    sentinel = object()
    monkeypatch.setattr(InMemorySaver, "get_delta_channel_history", sentinel)

    checkpoint_patches.ensure_inmemory_delta_history_patch()

    assert getattr(InMemorySaver, checkpoint_patches._PATCH_FLAG, False) is False
    assert InMemorySaver.get_delta_channel_history is sentinel


def test_inmemory_delta_history_patch_warns_on_unvalidated_langgraph(monkeypatch, caplog) -> None:
    """A langgraph newer than the validated version must log a re-inspection warning."""
    import logging

    from langgraph.checkpoint.memory import InMemorySaver

    from deerflow import checkpoint_patches

    monkeypatch.setattr(checkpoint_patches.importlib.metadata, "version", lambda _name: "99.0.0")
    monkeypatch.setattr(checkpoint_patches, "_upstream_override_present", lambda: False)
    monkeypatch.delattr(InMemorySaver, checkpoint_patches._PATCH_FLAG, raising=False)

    with caplog.at_level(logging.WARNING, logger=checkpoint_patches.__name__):
        checkpoint_patches.ensure_inmemory_delta_history_patch()

    assert any("newer than the version" in record.message for record in caplog.records)
