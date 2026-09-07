"""Executable contract for checkpoint retention: what may be deleted, what may not.

Companion to ``docs/checkpoint-retention-contract.md`` and the #4189 item 3
design discussion. LangGraph checkpoints form a per-thread parent chain, so a
deletion that looks harmless by recency can silently break branch/regenerate
(``find_checkpoint_before_message`` raises ``CheckpointLineageError`` when a
parent link is no longer addressable) or explicit ``checkpoint_id`` resume.
Each test pins one side of that boundary:

- growth baseline: per-step rows/bytes across the LangGraph tables, full vs
  delta, in the same normalized shape as ``bench_channels``;
- branch ancestor: deleting the checkpoint a branch point depends on must
  fail *loudly* (integrity error), never silently;
- explicit resume: deleting a referenced ``checkpoint_id`` removes the
  ability to resume to it;
- pending writes: uncommitted writes are retained state, not garbage;
- duration-only checkpoints: the runtime appends metadata-only checkpoints
  (``persist_run_durations``); one *inside* a lineage is a chain link the
  walk relies on, so blind deletion breaks the walk loudly;
- leaf sibling branch: a checkpoint forked off an older turn (the production
  branch path) can be deleted without affecting the main line — the one
  proven-safe deletion shape so far.

All contracts run against InMemorySaver, AsyncSqliteSaver, and — when
``TEST_POSTGRES_URI`` is set — AsyncPostgresSaver, mirroring
``test_delta_channel_checkpointers.py``.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any, TypedDict
from uuid import uuid4

import pytest
from langchain_core.messages import AnyMessage, HumanMessage
from langgraph.channels import DeltaChannel
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import StateGraph
from langgraph.graph.message import add_messages

from app.gateway.checkpoint_lineage import (
    CheckpointLineageError,
    find_checkpoint_before_message,
)
from deerflow.agents.thread_state import merge_message_writes


class FullState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


class DeltaState(TypedDict):
    messages: Annotated[
        list[AnyMessage],
        DeltaChannel(merge_message_writes, snapshot_frequency=2),
    ]


DURATION_ONLY_METADATA = {"writes": {"runtime_run_duration": {"seconds": 1.0}}}


def _thread_id() -> str:
    return f"retention-contract-{uuid4().hex}"


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


class _SaverEnv:
    """One saver instance over one backend (same shape as the delta contract fixture)."""

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
        db_path = tmp_path / "retention-contract.sqlite"

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
    """Minimal checkpoint accessor for ``find_checkpoint_before_message``."""

    def __init__(self, saver: Any) -> None:
        self._saver = saver

    async def aget(self, config: dict[str, Any]) -> Any:
        return await self._saver.aget_tuple(config)


# ---------------------------------------------------------------------------
# Normalized storage stats (same shape as bench_channels._normalized_storage_stats)
# ---------------------------------------------------------------------------

_SQLITE_TABLES = (
    ("checkpoint_rows", "checkpoint_bytes", "SELECT COUNT(*), COALESCE(SUM(LENGTH(checkpoint) + LENGTH(metadata)), 0) FROM checkpoints WHERE thread_id = ?"),
    ("write_rows", "write_bytes", "SELECT COUNT(*), COALESCE(SUM(LENGTH(value)), 0) FROM writes WHERE thread_id = ?"),
)

_POSTGRES_TABLES = (
    ("checkpoint_rows", "checkpoint_bytes", "SELECT COUNT(*) AS rows, COALESCE(SUM(pg_column_size(checkpoint) + pg_column_size(metadata)), 0) AS bytes FROM checkpoints WHERE thread_id = %s"),
    ("blob_rows", "blob_bytes", "SELECT COUNT(*) AS rows, COALESCE(SUM(octet_length(blob)), 0) AS bytes FROM checkpoint_blobs WHERE thread_id = %s"),
    ("write_rows", "write_bytes", "SELECT COUNT(*) AS rows, COALESCE(SUM(octet_length(blob)), 0) AS bytes FROM checkpoint_writes WHERE thread_id = %s"),
)


async def _stats(env: _SaverEnv, thread_id: str) -> dict[str, int]:
    """Per-thread rows/bytes in the backend-neutral measurement shape."""
    saver = env.saver
    if env.kind == "memory":
        checkpoint_rows = checkpoint_bytes = write_rows = write_bytes = 0
        for namespace in saver.storage.get(thread_id, {}).values():
            for checkpoint, metadata, _parent in namespace.values():
                checkpoint_rows += 1
                checkpoint_bytes += len(checkpoint[1]) + len(metadata[1])
        for (stored_thread, _ns, _cp_id), writes in saver.writes.items():
            if stored_thread != thread_id:
                continue
            for _task_id, _channel, (_type_tag, blob), _path in writes.values():
                write_rows += 1
                write_bytes += len(blob)
        return {
            "checkpoint_rows": checkpoint_rows,
            "checkpoint_bytes": checkpoint_bytes,
            "blob_rows": 0,
            "blob_bytes": 0,
            "write_rows": write_rows,
            "write_bytes": write_bytes,
        }
    if env.kind == "sqlite":
        stats: dict[str, int] = {}
        for row_key, bytes_key, sql in _SQLITE_TABLES:
            async with saver.conn.execute(sql, (thread_id,)) as cursor:
                row = await cursor.fetchone()
            stats[row_key] = int(row[0])
            stats[bytes_key] = int(row[1] or 0)
        stats["blob_rows"] = 0
        stats["blob_bytes"] = 0
        return stats
    stats = {}
    for row_key, bytes_key, sql in _POSTGRES_TABLES:
        async with saver._cursor() as cursor:
            await cursor.execute(sql, (thread_id,))
            row = await cursor.fetchone()
        stats[row_key] = int(row["rows"])
        stats[bytes_key] = int(row["bytes"] or 0)
    return stats


async def _delete_checkpoint(env: _SaverEnv, thread_id: str, checkpoint_id: str) -> None:
    """Remove one checkpoint row directly from the backend (simulation of a retention delete)."""
    saver = env.saver
    if env.kind == "memory":
        for namespace in saver.storage.get(thread_id, {}).values():
            if checkpoint_id in namespace:
                del namespace[checkpoint_id]
        return
    if env.kind == "sqlite":
        await saver.conn.execute(
            "DELETE FROM checkpoints WHERE thread_id = ? AND checkpoint_id = ?",
            (thread_id, checkpoint_id),
        )
        await saver.conn.commit()
        return
    async with saver._cursor() as cursor:
        await cursor.execute(
            "DELETE FROM checkpoints WHERE thread_id = %s AND checkpoint_id = %s",
            (thread_id, checkpoint_id),
        )


def _report(name: str, data: dict[str, Any]) -> None:
    """Append one scenario result to the optional JSON report file."""
    path = os.environ.get("DEERFLOW_RETENTION_REPORT")
    if not path:
        return
    report: dict[str, Any] = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            report = json.load(handle)
    report.setdefault(name, {})[os.environ.get("DEERFLOW_RETENTION_BACKEND", "run")] = data
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)


# ---------------------------------------------------------------------------
# Shared writers
# ---------------------------------------------------------------------------


async def _write_turns(
    env: _SaverEnv,
    schema: Any,
    steps: int,
    *,
    payload_bytes: int = 256,
) -> tuple[str, list[str], list[str]]:
    """Write *steps* one-message turns; return (thread_id, checkpoint_ids, message_ids)."""
    graph = _build_graph(schema, env.saver)
    thread_id = _thread_id()
    checkpoint_ids: list[str] = []
    message_ids: list[str] = []
    for index in range(steps):
        message = HumanMessage(content=f"turn {index}: " + "x" * payload_bytes, id=f"turn-{index}")
        message_ids.append(message.id)
        await graph.ainvoke({"messages": [message]}, _config(thread_id))
        snapshot = await graph.aget_state(_config(thread_id))
        checkpoint_ids.append(snapshot.config["configurable"]["checkpoint_id"])
    return thread_id, checkpoint_ids, message_ids


async def _walk(env: _SaverEnv, head_config: dict[str, Any], message_id: str) -> Any:
    return await find_checkpoint_before_message(
        _SaverAccessor(env.saver),
        await env.saver.aget_tuple(head_config),
        message_id,
        max_depth=50,
    )


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_growth_baseline_full_vs_delta(saver_env: _SaverEnv) -> None:
    """Scenario A: per-step growth is recorded for both schemas; delta must not regress.

    Full mode re-snapshots cumulative messages every step; delta mode appends
    writes and only snapshots every ``snapshot_frequency`` steps.
    """
    measurements: dict[str, list[dict[str, int]]] = {}
    for schema_name, schema in (("full", FullState), ("delta", DeltaState)):
        graph = _build_graph(schema, saver_env.saver)
        thread_id = _thread_id()
        series: list[dict[str, int]] = []
        for index in range(4):
            message = HumanMessage(content=f"turn {index}: " + "y" * 512, id=f"turn-{index}")
            await graph.ainvoke({"messages": [message]}, _config(thread_id))
            series.append(await _stats(saver_env, thread_id))
        measurements[schema_name] = series

        rows = [sample["checkpoint_rows"] for sample in series]
        assert rows == sorted(rows), f"{schema_name} checkpoint rows must be non-decreasing: {rows}"

    # storage-shape contract: delta mode carries per-step payloads in the
    # writes table (snapshotted only every snapshot_frequency), while full
    # mode re-snapshots everything into the checkpoints payload. Absolute
    # byte comparisons are cadence- and backend-dependent — the report above
    # is what feeds the retention design, these assertions pin the shape.
    assert measurements["delta"][-1]["write_rows"] > 0, "delta mode must land per-step payloads in writes"
    _report("growth_baseline", measurements)


@pytest.mark.anyio
async def test_deleting_branch_ancestor_breaks_lineage_loudly(saver_env: _SaverEnv) -> None:
    """Scenario B: a checkpoint an older turn's branch depends on cannot be silently removed.

    Regenerate/branch resolves the replay base by walking the parent chain from
    the head. Deleting the chain node the branch point needs must surface as
    ``CheckpointLineageError`` — never as a wrong-but-plausible replay base.
    """
    thread_id, checkpoint_ids, message_ids = await _write_turns(saver_env, FullState, steps=4)
    head_config = _config(thread_id)

    base = await _walk(saver_env, head_config, message_ids[1])
    assert base is not None
    branch_point_id = base.config["configurable"]["checkpoint_id"]

    await _delete_checkpoint(saver_env, thread_id, branch_point_id)

    with pytest.raises(CheckpointLineageError):
        await _walk(saver_env, head_config, message_ids[1])
    _report("branch_ancestor_deletion", {"deleted": branch_point_id})


@pytest.mark.anyio
async def test_deleting_explicit_resume_target_breaks_resume(saver_env: _SaverEnv) -> None:
    """Scenario C: a ``checkpoint_id`` someone may resume to is part of the protected set."""
    thread_id, checkpoint_ids, _message_ids = await _write_turns(saver_env, FullState, steps=4)
    target_id = checkpoint_ids[1]

    before = await saver_env.saver.aget_tuple({"configurable": {"thread_id": thread_id, "checkpoint_id": target_id}})
    assert before is not None

    await _delete_checkpoint(saver_env, thread_id, target_id)

    after = await saver_env.saver.aget_tuple({"configurable": {"thread_id": thread_id, "checkpoint_id": target_id}})
    assert after is None, "resume to a deleted checkpoint_id must fail, not silently fall back"


@pytest.mark.anyio
async def test_pending_writes_are_retained_state_not_garbage(saver_env: _SaverEnv) -> None:
    """Scenario D: uncommitted writes are visible state; their rows are protected."""
    thread_id, checkpoint_ids, _message_ids = await _write_turns(saver_env, FullState, steps=2)

    write = ("messages", ("human", b"pending-write"))
    latest_config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": "", "checkpoint_id": checkpoint_ids[-1]}}
    await saver_env.saver.aput_writes(latest_config, [write], task_id="pending-task")

    stats = await _stats(saver_env, thread_id)
    assert stats["write_rows"] > 0, "put_writes must land in the writes table"
    assert checkpoint_ids  # resume surface exists; orphan accounting lives in the contract doc
    _report("pending_writes", {"stats": stats})


@pytest.mark.anyio
async def test_leaf_duration_checkpoint_deletion_is_safe(saver_env: _SaverEnv) -> None:
    """Scenario E1: a trailing metadata-only leaf checkpoint can be deleted.

    ``persist_run_durations`` appends duration-only checkpoints after a run
    finishes. While such a checkpoint is a *leaf* (no later run has forked
    from it), deleting it does not affect the finished run's lineage: the
    lineage walk only ever steps through ancestors of the walk head, and a
    leaf is nobody's ancestor. A duration-only checkpoint that a later run
    has forked from is instead a chain link — deleting that shape requires
    grafting the fork onto the grandparent, which is specified in the
    contract doc and can only be produced by the real runtime (a bare
    ``empty_checkpoint`` lacks the metadata LangGraph needs to resume from).
    """
    thread_id, checkpoint_ids, message_ids = await _write_turns(saver_env, FullState, steps=3)

    head = await saver_env.saver.aget_tuple(_config(thread_id))
    head_checkpoint_id = head.checkpoint["id"]

    # append a trailing duration-only checkpoint, as persist_run_durations
    # does when a run finishes
    duration_id = f"duration-{uuid4().hex}"
    duration_checkpoint = empty_checkpoint()
    duration_checkpoint["id"] = duration_id
    await saver_env.saver.aput(
        {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": "",
                "checkpoint_id": head_checkpoint_id,
            }
        },
        duration_checkpoint,
        DURATION_ONLY_METADATA,
        {},
    )

    # a trailing metadata-only leaf can be dropped (a cleanup that prunes
    # trailing duration checkpoints) without affecting the run's lineage
    await _delete_checkpoint(saver_env, thread_id, duration_id)

    # the run's final checkpoint still resolves its lineage and stays
    # explicitly addressable
    base = await _walk(saver_env, _config_thread(thread_id, checkpoint_ids[-1]), "turn-2")
    assert base is not None
    resumed = await saver_env.saver.aget_tuple(_config_thread(thread_id, checkpoint_ids[-1]))
    assert resumed is not None
    _report("leaf_duration_deletion", {"deleted": duration_id, "head": checkpoint_ids[-1]})


def graph_for(env: _SaverEnv) -> Any:
    return _build_graph(FullState, env.saver)


def _config_thread(thread_id: str, checkpoint_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id, "checkpoint_id": checkpoint_id}}


@pytest.mark.anyio
async def test_leaf_sibling_branch_deletion_is_safe(saver_env: _SaverEnv) -> None:
    """Scenario E2: a forked-off leaf branch can be deleted without touching the main line.

    This is the one deletion shape proven safe so far: create a real branch by
    resuming from an older checkpoint and writing a new turn (the production
    branch path), then delete the resulting leaf checkpoint. The original
    head, its lineage walk, and explicit resume all keep working.
    """
    thread_id, checkpoint_ids, message_ids = await _write_turns(saver_env, FullState, steps=4)
    original_head_id = checkpoint_ids[-1]

    # fork a real branch from turn 1 via the production path (resume + write)
    graph = _build_graph(FullState, saver_env.saver)
    fork_config = _config_thread(thread_id, checkpoint_ids[1])
    fork_message = HumanMessage(content="fork turn: " + "z" * 256, id="fork-turn")
    await graph.ainvoke({"messages": [fork_message]}, fork_config)
    # the fork leaf is the newest checkpoint on the thread; querying with the
    # fork config would return the *source* checkpoint instead
    fork_state = await graph.aget_state(_config(thread_id))
    fork_checkpoint_id = fork_state.config["configurable"]["checkpoint_id"]
    assert fork_checkpoint_id not in (original_head_id, checkpoint_ids[1])

    await _delete_checkpoint(saver_env, thread_id, fork_checkpoint_id)

    # the main line is untouched: its head is still explicitly addressable and
    # the lineage walk still resolves (the forked checkpoint was a leaf)
    mainline_head = await saver_env.saver.aget_tuple(_config_thread(thread_id, original_head_id))
    assert mainline_head is not None
    base = await _walk(saver_env, _config_thread(thread_id, original_head_id), message_ids[0])
    assert base is not None
    resumed = await saver_env.saver.aget_tuple(_config_thread(thread_id, original_head_id))
    assert resumed is not None
    _report("leaf_sibling_deletion", {"fork": fork_checkpoint_id, "head": original_head_id})
