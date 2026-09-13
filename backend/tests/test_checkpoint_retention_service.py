"""Behavioral tests for ``app/gateway/checkpoint_retention.py``.

Each test drives the retention service over real saver backends (memory,
SQLite, and Postgres when ``TEST_POSTGRES_URI`` is set) using the same chain
constructions as the contract suite, then verifies the contract's four
post-deletion properties: latest resume, explicit ``checkpoint_id`` resume,
branch/regenerate lineage walk, and orphan row accounting. The duration-only
checkpoints are produced by the real runtime writer (``persist_run_durations``),
not hand-rolled ``aput`` calls, so the classification runs against the exact
metadata shape production emits.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any, TypedDict
from uuid import uuid4

import pytest
from langchain_core.messages import AnyMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from app.gateway import checkpoint_retention
from app.gateway.checkpoint_lineage import find_checkpoint_before_message
from app.gateway.checkpoint_retention import (
    RetentionPolicy,
    _row_field,
    enforce_thread_retention,
)
from deerflow.runtime.runs.worker import persist_run_durations


class FullState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


def _thread_id() -> str:
    return f"retention-service-{uuid4().hex}"


def _config(thread_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id}}


def _config_thread(thread_id: str, checkpoint_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id, "checkpoint_id": checkpoint_id}}


def _noop(state: dict[str, Any]) -> dict[str, Any]:
    return {}


def _build_graph(schema: Any, checkpointer: Any) -> Any:
    builder = StateGraph(schema)
    builder.add_node("noop", _noop)
    builder.set_entry_point("noop")
    builder.set_finish_point("noop")
    return builder.compile(checkpointer=checkpointer)


class _SaverEnv:
    def __init__(self, kind: str, open_saver: Any) -> None:
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
        db_path = tmp_path / "retention-service.sqlite"

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


class _SaverAccessor:
    def __init__(self, saver: Any) -> None:
        self._saver = saver

    async def aget(self, config: dict[str, Any]) -> Any:
        return await self._saver.aget_tuple(config)


async def _walk(env: _SaverEnv, head_config: dict[str, Any], message_id: str) -> Any:
    return await find_checkpoint_before_message(
        _SaverAccessor(env.saver),
        await env.saver.aget_tuple(head_config),
        message_id,
        max_depth=50,
    )


async def _write_turns(
    env: _SaverEnv,
    steps: int,
    *,
    payload_bytes: int = 256,
) -> tuple[str, list[str], list[str]]:
    graph = _build_graph(FullState, env.saver)
    thread_id = _thread_id()
    checkpoint_ids: list[str] = []
    for index in range(steps):
        message = HumanMessage(content=f"turn {index}: " + "x" * payload_bytes, id=f"turn-{index}")
        await graph.ainvoke({"messages": [message]}, _config(thread_id))
        snapshot = await graph.aget_state(_config(thread_id))
        checkpoint_ids.append(snapshot.config["configurable"]["checkpoint_id"])
    return thread_id, checkpoint_ids, [f"turn-{index}" for index in range(steps)]


async def _append_duration_checkpoint(env: _SaverEnv, thread_id: str, run_id: str = "run-1") -> str:
    """Append a duration-only checkpoint through the real runtime writer."""
    written = await persist_run_durations(checkpointer=env.saver, thread_id=thread_id, durations={run_id: 7})
    assert written, "persist_run_durations must land a metadata-only checkpoint"
    head = await env.saver.aget_tuple(_config(thread_id))
    assert head is not None
    return head.checkpoint["id"]


async def _listed_checkpoint_ids(env: _SaverEnv, thread_id: str) -> set[str]:
    return {tuple_.checkpoint["id"] async for tuple_ in env.saver.alist(_config(thread_id), limit=None)}


async def _write_count(env: _SaverEnv, thread_id: str, checkpoint_id: str) -> int:
    if env.kind == "memory":
        return len(env.saver.writes.get((thread_id, "", checkpoint_id), {}))
    if env.kind == "sqlite":
        async with env.saver.conn.execute(
            "SELECT COUNT(*) FROM writes WHERE thread_id = ? AND checkpoint_id = ?",
            (thread_id, checkpoint_id),
        ) as cursor:
            row = await cursor.fetchone()
        return int(_row_field(row, "COUNT(*)", 0))
    async with env.saver._cursor() as cursor:
        await cursor.execute(
            "SELECT COUNT(*) AS write_count FROM checkpoint_writes WHERE thread_id = %s AND checkpoint_id = %s",
            (thread_id, checkpoint_id),
        )
        row = await cursor.fetchone()
    return int(_row_field(row, "write_count", 0))


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_linear_thread_prunes_nothing(saver_env: _SaverEnv) -> None:
    """A plain linear thread is one protected ancestor chain: nothing may go."""
    thread_id, checkpoint_ids, _message_ids = await _write_turns(saver_env, steps=4)

    report = await enforce_thread_retention(saver_env.saver, thread_id)

    assert report.deleted_checkpoint_ids == []
    assert report.protected_head_id == checkpoint_ids[-1]
    # one invoke lands several checkpoints (input/task/result); the ids we
    # collected are the resumable results, and all of them must survive
    listed = await _listed_checkpoint_ids(saver_env, thread_id)
    assert set(checkpoint_ids).issubset(listed)


@pytest.mark.anyio
async def test_runtime_duration_leaf_pruned_by_default(saver_env: _SaverEnv) -> None:
    """Contract E1 via the real writer: a trailing duration-only leaf is pruned,
    the finished run's final checkpoint stays resumable and walkable, and the
    row accounting reflects exactly one reclaimed checkpoint."""
    thread_id, checkpoint_ids, message_ids = await _write_turns(saver_env, steps=3)
    duration_id = await _append_duration_checkpoint(saver_env, thread_id)

    # Shipping default (strict_pending_write_guard=True): the duration-only
    # leaf owns no writes rows — on memory its ``writes`` entry is the phantom
    # empty dict that ``_checkpoint_ids_with_writes`` does not count — so the
    # default policy itself prunes it. This is the proof that the headline
    # "enabled by default" E1 shape is reachable on every backend, not only
    # after relaxing the guard.
    report = await enforce_thread_retention(saver_env.saver, thread_id)

    assert report.deleted_checkpoint_ids == [duration_id]
    assert report.protected_head_id == checkpoint_ids[-1]
    assert duration_id not in await _listed_checkpoint_ids(saver_env, thread_id)
    resumed = await saver_env.saver.aget_tuple(_config_thread(thread_id, checkpoint_ids[-1]))
    assert resumed is not None
    base = await _walk(saver_env, _config_thread(thread_id, checkpoint_ids[-1]), message_ids[-1])
    assert base is not None
    assert report.stats_after["checkpoint_rows"] == report.stats_before["checkpoint_rows"] - 1


@pytest.mark.anyio
async def test_duration_link_protected_after_next_run(saver_env: _SaverEnv) -> None:
    """Contract protected set item 4: once a later run has been written on top
    of a duration-only checkpoint, that checkpoint is a chain link on the new
    head's ancestor chain and must not be touched (deleting it would need
    grafting, which v1 does not attempt)."""
    thread_id, checkpoint_ids, _message_ids = await _write_turns(saver_env, steps=3)
    duration_id = await _append_duration_checkpoint(saver_env, thread_id)

    graph = _build_graph(FullState, saver_env.saver)
    follow_up = HumanMessage(content="turn after duration: " + "x" * 64, id="turn-after-duration")
    await graph.ainvoke({"messages": [follow_up]}, _config(thread_id))
    snapshot = await graph.aget_state(_config(thread_id))
    assert snapshot.config["configurable"]["checkpoint_id"] not in (*checkpoint_ids, duration_id)

    report = await enforce_thread_retention(saver_env.saver, thread_id)

    assert report.deleted_checkpoint_ids == []
    assert duration_id in await _listed_checkpoint_ids(saver_env, thread_id)
    assert report.protected_head_id == snapshot.config["configurable"]["checkpoint_id"]


@pytest.mark.anyio
async def test_regenerated_old_head_pruned_opt_in(saver_env: _SaverEnv) -> None:
    """Contract E2 shape in its production direction: after a regenerate, the
    fork is the live resume head and the superseded old head becomes a leaf
    sibling. With the opt-in flag the old head is pruned while the fork line
    keeps working end to end."""
    thread_id, checkpoint_ids, _message_ids = await _write_turns(saver_env, steps=4)
    old_head_id = checkpoint_ids[-1]

    graph = _build_graph(FullState, saver_env.saver)
    fork_message = HumanMessage(content="regenerated turn: " + "z" * 256, id="fork-turn")
    await graph.ainvoke({"messages": [fork_message]}, _config_thread(thread_id, checkpoint_ids[1]))
    snapshot = await graph.aget_state(_config(thread_id))
    fork_head_id = snapshot.config["configurable"]["checkpoint_id"]
    assert fork_head_id not in (*checkpoint_ids,)

    policy = RetentionPolicy(prune_leaf_sibling_branches=True, strict_pending_write_guard=False)
    report = await enforce_thread_retention(saver_env.saver, thread_id, policy)

    assert report.deleted_checkpoint_ids == [old_head_id]
    assert report.protected_head_id == fork_head_id

    fork_tuple = await saver_env.saver.aget_tuple(_config_thread(thread_id, fork_head_id))
    assert fork_tuple is not None
    base = await _walk(saver_env, _config_thread(thread_id, fork_head_id), "fork-turn")
    assert base is not None
    remaining = await _listed_checkpoint_ids(saver_env, thread_id)
    assert old_head_id not in remaining
    assert {checkpoint_ids[0], checkpoint_ids[1], fork_head_id}.issubset(remaining)


@pytest.mark.anyio
async def test_explicit_protect_ids_spare_the_superseded_head(saver_env: _SaverEnv) -> None:
    """Protected set item 1: a client-held checkpoint id wins over pruning.
    The same thread prunes only once the id leaves the protect list."""
    thread_id, checkpoint_ids, _message_ids = await _write_turns(saver_env, steps=4)
    old_head_id = checkpoint_ids[-1]

    graph = _build_graph(FullState, saver_env.saver)
    fork_message = HumanMessage(content="regenerated turn: " + "z" * 256, id="fork-turn")
    await graph.ainvoke({"messages": [fork_message]}, _config_thread(thread_id, checkpoint_ids[1]))

    protected_policy = RetentionPolicy(prune_leaf_sibling_branches=True, protect_checkpoint_ids=frozenset({old_head_id}))
    report = await enforce_thread_retention(saver_env.saver, thread_id, protected_policy)
    assert report.deleted_checkpoint_ids == []
    kept = await saver_env.saver.aget_tuple(_config_thread(thread_id, old_head_id))
    assert kept is not None

    report = await enforce_thread_retention(
        saver_env.saver,
        thread_id,
        RetentionPolicy(prune_leaf_sibling_branches=True, strict_pending_write_guard=False),
    )
    assert report.deleted_checkpoint_ids == [old_head_id]


@pytest.mark.anyio
async def test_strict_pending_write_guard_spares_leaf_and_cleans_orphans_after(saver_env: _SaverEnv) -> None:
    """Protected set item 3 + deletion mechanics: a leaf that still owns writes
    rows is spared under the strict guard; deleting it with the guard relaxed
    removes its writes rows with it, and writes held by retained checkpoints
    survive."""
    thread_id, checkpoint_ids, _message_ids = await _write_turns(saver_env, steps=4)
    old_head_id = checkpoint_ids[-1]

    graph = _build_graph(FullState, saver_env.saver)
    fork_message = HumanMessage(content="regenerated turn: " + "z" * 256, id="fork-turn")
    await graph.ainvoke({"messages": [fork_message]}, _config_thread(thread_id, checkpoint_ids[1]))
    snapshot = await graph.aget_state(_config(thread_id))
    fork_head_id = snapshot.config["configurable"]["checkpoint_id"]

    write = ("messages", ("human", b"pending-write"))
    old_head_config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": "", "checkpoint_id": old_head_id}}
    fork_head_config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": "", "checkpoint_id": fork_head_id}}
    await saver_env.saver.aput_writes(old_head_config, [write], task_id="orphan-task")
    await saver_env.saver.aput_writes(fork_head_config, [write], task_id="pending-task")
    assert await _write_count(saver_env, thread_id, old_head_id) > 0

    guarded_report = await enforce_thread_retention(
        saver_env.saver,
        thread_id,
        RetentionPolicy(prune_leaf_sibling_branches=True, strict_pending_write_guard=True),
    )
    assert guarded_report.deleted_checkpoint_ids == []
    assert await _write_count(saver_env, thread_id, old_head_id) > 0

    relaxed_report = await enforce_thread_retention(
        saver_env.saver,
        thread_id,
        RetentionPolicy(prune_leaf_sibling_branches=True, strict_pending_write_guard=False),
    )
    assert relaxed_report.deleted_checkpoint_ids == [old_head_id]
    assert await _write_count(saver_env, thread_id, old_head_id) == 0, "orphaned writes rows must go with their checkpoint"
    assert await _write_count(saver_env, thread_id, fork_head_id) > 0, "writes of retained checkpoints must survive"

    fork_tuple = await saver_env.saver.aget_tuple(_config_thread(thread_id, fork_head_id))
    assert fork_tuple is not None
    base = await _walk(saver_env, _config_thread(thread_id, fork_head_id), "fork-turn")
    assert base is not None


@pytest.mark.anyio
async def test_max_delete_per_run_caps_the_batch(saver_env: _SaverEnv) -> None:
    """Two prunable leaves (a trailing duration-only leaf and a superseded old
    head) with a cap of one: exactly one row goes, the other survives."""
    thread_id, checkpoint_ids, _message_ids = await _write_turns(saver_env, steps=3)
    old_head_id = checkpoint_ids[-1]

    graph = _build_graph(FullState, saver_env.saver)
    fork_message = HumanMessage(content="regenerated turn: " + "z" * 256, id="fork-turn")
    await graph.ainvoke({"messages": [fork_message]}, _config_thread(thread_id, checkpoint_ids[1]))

    duration_id = await _append_duration_checkpoint(saver_env, thread_id)

    policy = RetentionPolicy(
        prune_leaf_sibling_branches=True,
        strict_pending_write_guard=False,
        max_delete_per_run=1,
    )
    report = await enforce_thread_retention(saver_env.saver, thread_id, policy)

    assert len(report.deleted_checkpoint_ids) == 1
    assert report.deleted_checkpoint_ids[0] in (old_head_id, duration_id)
    remaining = await _listed_checkpoint_ids(saver_env, thread_id)
    assert len(remaining & {old_head_id, duration_id}) == 1


@pytest.mark.anyio
async def test_unsupported_saver_raises_before_any_read() -> None:
    """An untested saver is rejected up front: no row is read or deleted, so
    no partial deletion can happen on a backend the mechanics were not
    validated on."""

    class _FakeSaver:
        async def alist(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any]:
            raise AssertionError("alist must not run on an unsupported saver")
            yield  # pragma: no cover

    with pytest.raises(NotImplementedError):
        await enforce_thread_retention(_FakeSaver(), _thread_id())


@pytest.mark.anyio
async def test_chain_walk_tolerates_missing_ancestor_row() -> None:
    """A head whose ancestor row is missing (partial damage from an earlier
    policy revision or manual cleanup) ends the chain walk instead of
    crashing the whole pass; the surviving protections still hold."""
    saver = InMemorySaver()
    graph = _build_graph(FullState, saver)
    thread_id = _thread_id()
    checkpoint_ids: list[str] = []
    for index in range(3):
        message = HumanMessage(content=f"turn {index}: " + "x" * 256, id=f"turn-{index}")
        await graph.ainvoke({"messages": [message]}, _config(thread_id))
        snapshot = await graph.aget_state(_config(thread_id))
        checkpoint_ids.append(snapshot.config["configurable"]["checkpoint_id"])

    # Simulate a partially pruned thread: the middle resumable row is gone.
    namespace = saver.storage[thread_id][""]
    assert checkpoint_ids[1] in namespace
    namespace.pop(checkpoint_ids[1], None)

    report = await enforce_thread_retention(saver, thread_id)

    assert report.protected_head_id == checkpoint_ids[-1]
    # The head is protected; the remaining off-chain node (the oldest turn) is
    # a leaf sibling, which is not pruned unless opted in.
    assert report.deleted_checkpoint_ids == []


@pytest.mark.anyio
async def test_thread_lock_parameter_accepted(saver_env: _SaverEnv) -> None:
    """An explicit per-thread lock is honored: with an uncontended lock the
    call completes with the same outcome as without one."""
    thread_id, checkpoint_ids, _message_ids = await _write_turns(saver_env, steps=2)

    lock = asyncio.Lock()
    report = await enforce_thread_retention(saver_env.saver, thread_id, thread_lock=lock)

    assert report.deleted_checkpoint_ids == []
    assert report.protected_head_id == checkpoint_ids[-1]


# ---------------------------------------------------------------------------
# Policy validation and report shape
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_negative_max_delete_per_run_fails_closed_before_any_read(saver_env: _SaverEnv, monkeypatch: pytest.MonkeyPatch) -> None:
    """A negative cap is an invalid configuration, not a small one. It must
    raise before the store is touched — the slice that applies the cap would
    otherwise turn -1 into "everything except the last candidate", i.e. widen a
    destructive pass to almost its maximum — and it must delete nothing."""
    thread_id, checkpoint_ids, _message_ids = await _write_turns(saver_env, steps=3)
    old_head_id = checkpoint_ids[-1]

    graph = _build_graph(FullState, saver_env.saver)
    fork_message = HumanMessage(content="regenerated turn: " + "z" * 256, id="fork-turn")
    await graph.ainvoke({"messages": [fork_message]}, _config_thread(thread_id, checkpoint_ids[1]))
    duration_id = await _append_duration_checkpoint(saver_env, thread_id)
    before = await _listed_checkpoint_ids(saver_env, thread_id)
    # Both leaves are prunable under this policy, so a widened batch would show
    # up as deletions rather than as an empty report.
    assert {old_head_id, duration_id}.issubset(before)

    async def _no_store_access(*args: Any, **kwargs: Any) -> dict[str, int]:
        raise AssertionError("validation must reject the policy before reading the store")

    monkeypatch.setattr(checkpoint_retention, "_thread_storage_stats", _no_store_access)

    with pytest.raises(ValueError, match="max_delete_per_run must be >= 0, got -1"):
        await enforce_thread_retention(
            saver_env.saver,
            thread_id,
            RetentionPolicy(
                prune_leaf_sibling_branches=True,
                strict_pending_write_guard=False,
                max_delete_per_run=-1,
            ),
        )

    monkeypatch.undo()
    assert await _listed_checkpoint_ids(saver_env, thread_id) == before


@pytest.mark.anyio
async def test_zero_max_delete_per_run_deletes_nothing(saver_env: _SaverEnv) -> None:
    """Zero is the disabled-but-valid boundary: it bounds the batch to nothing
    and still reports the same before/after measurement shape."""
    thread_id, checkpoint_ids, _message_ids = await _write_turns(saver_env, steps=3)
    duration_id = await _append_duration_checkpoint(saver_env, thread_id)

    report = await enforce_thread_retention(
        saver_env.saver,
        thread_id,
        RetentionPolicy(max_delete_per_run=0),
    )

    assert report.deleted_checkpoint_ids == []
    assert duration_id in await _listed_checkpoint_ids(saver_env, thread_id)
    assert report.stats_after == report.stats_before


@pytest.mark.anyio
async def test_empty_thread_reports_the_same_before_and_after_stats(saver_env: _SaverEnv) -> None:
    """An empty (or unknown) thread is a no-op, but the report contract still
    holds: both measurement halves are present and identical, so a caller
    aggregating stats does not have to special-case "nothing to classify"."""
    thread_id = _thread_id()

    report = await enforce_thread_retention(saver_env.saver, thread_id)

    assert report.deleted_checkpoint_ids == []
    assert report.protected_head_id is None
    assert report.stats_before == report.stats_after
    assert set(report.stats_before) == {
        "logical_checkpoint_bytes",
        "logical_write_bytes",
        "checkpoint_rows",
        "checkpoint_bytes",
        "blob_rows",
        "blob_bytes",
        "write_rows",
        "write_bytes",
    }

    without_stats = await enforce_thread_retention(saver_env.saver, thread_id, collect_stats=False)
    assert without_stats.stats_before == {}
    assert without_stats.stats_after == {}


# ---------------------------------------------------------------------------
# Namespaced (persistent subgraph) histories
# ---------------------------------------------------------------------------


class _ChildState(TypedDict):
    value: int


def _increment(state: _ChildState) -> dict[str, int]:
    return {"value": state.get("value", 0) + 1}


def _build_nested_graph(checkpointer: Any) -> Any:
    """A parent graph whose node is a subgraph that owns its own checkpoints."""
    child_builder = StateGraph(_ChildState)
    child_builder.add_node("increment", _increment)
    child_builder.add_edge(START, "increment")
    child_builder.add_edge("increment", END)
    child = child_builder.compile(checkpointer=True)

    parent_builder = StateGraph(_ChildState)
    parent_builder.add_node("child", child)
    parent_builder.add_edge(START, "child")
    parent_builder.add_edge("child", END)
    return parent_builder.compile(checkpointer=checkpointer)


@pytest.mark.anyio
async def test_persistent_subgraph_resume_head_survives_a_prune(saver_env: _SaverEnv) -> None:
    """A persistent subgraph checkpoints under its own namespace, and ``alist``
    returns those rows alongside the parent's. Protecting only one global head
    makes the child's latest checkpoint look like an off-chain sibling leaf, so
    the opt-in E2 shape deletes it and the child's saved state rolls back to the
    preceding checkpoint. Each namespace's resume head must be protected."""
    graph = _build_nested_graph(saver_env.saver)
    thread_id = _thread_id()
    await graph.ainvoke({"value": 10}, _config(thread_id))

    namespaces = {(tuple_.config["configurable"].get("checkpoint_ns") or "") async for tuple_ in saver_env.saver.alist(_config(thread_id), limit=None)}
    child_namespaces = sorted(ns for ns in namespaces if ns)
    assert child_namespaces, "the persistent subgraph must write its own namespace"
    child_ns = child_namespaces[0]

    child_config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": child_ns}}
    child_head = await saver_env.saver.aget_tuple(child_config)
    assert child_head is not None
    child_head_id = child_head.checkpoint["id"]
    assert child_head.checkpoint["channel_values"]["value"] == 11

    report = await enforce_thread_retention(
        saver_env.saver,
        thread_id,
        RetentionPolicy(prune_leaf_sibling_branches=True),
    )

    assert child_head_id not in report.deleted_checkpoint_ids
    resumed = await saver_env.saver.aget_tuple(child_config)
    assert resumed is not None
    assert resumed.checkpoint["id"] == child_head_id
    assert resumed.checkpoint["channel_values"]["value"] == 11
    listed = {tuple_.checkpoint["id"] async for tuple_ in saver_env.saver.alist(_config(thread_id), limit=None)}
    assert child_head_id in listed
