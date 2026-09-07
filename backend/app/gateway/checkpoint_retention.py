"""Thread-level checkpoint retention enforcing the #4189 item 3 contract.

Implements exactly the two deletion shapes proven safe by
``docs/checkpoint-retention-contract.md`` and its executable suite
(``tests/test_checkpoint_retention_contract.py``) — nothing else:

- **Trailing duration-only leaves** — ``persist_run_durations`` appends
  metadata-only checkpoints after a run finishes; while no later run has
  forked from one, it is nobody's ancestor and can be dropped (contract
  scenario E1).
- **Leaf sibling branches** *(opt-in)* — a checkpoint forked off an older
  turn that has no children (contract scenario E2). Opt-in because a
  superseded line's checkpoints may still be explicit resume targets a
  client holds (protected set item 1); ``RetentionPolicy.protect_checkpoint_ids``
  is the escape hatch until a TTL semantic is agreed for that item.

Everything on the resume head's ancestor chain — including duration-only
chain links, which would need grafting before deletion — every explicitly
protected id, and any checkpoint that still owns ``writes`` rows (protected
set item 3) is never deleted. Deletion runs at the storage layer, mirroring
the contract's per-backend data model, and removes the writes rows orphaned
by a deleted checkpoint in the same step (contract "deletion mechanics").
Postgres ``checkpoint_blobs`` rows are keyed by ``version`` = the id of the
checkpoint that wrote the blob, so the same join keys clean them.

The service ships **without a production trigger**: where retention is
invoked from (post-run hook vs scheduler vs explicit admin action) is a
maintainer decision that lands with the contract itself. Measurement-first:
reports carry before/after per-thread stats in the same normalized shape as
``scripts/benchmark/checkpoint/bench_channels.py``.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.gateway.checkpoint_lineage import (
    checkpoint_configurable,
    is_duration_only_checkpoint,
)

__all__ = ["RetentionPolicy", "RetentionReport", "enforce_thread_retention"]


@dataclass(frozen=True)
class RetentionPolicy:
    """What this run may delete. Defaults prune only what the contract proves safe unconditionally."""

    prune_trailing_duration_leaves: bool = True
    prune_leaf_sibling_branches: bool = False
    protect_checkpoint_ids: frozenset[str] = frozenset()
    strict_pending_write_guard: bool = True
    max_delete_per_run: int | None = None


@dataclass
class RetentionReport:
    """Outcome of one retention pass over one thread."""

    thread_id: str
    protected_head_id: str | None = None
    deleted_checkpoint_ids: list[str] = field(default_factory=list)
    stats_before: dict[str, int] = field(default_factory=dict)
    stats_after: dict[str, int] = field(default_factory=dict)


@dataclass
class _Node:
    ns: str
    cp_id: str
    parent_ns: str | None
    parent_id: str | None
    step: int
    duration_only: bool
    mid_run: bool


def _node_step(tuple_: Any) -> int:
    """Ordering key for "newest": the metadata step is the runtime's real
    sequence number; ``checkpoint["step"]`` is not reliably populated on every
    backend's raw list path."""
    metadata = getattr(tuple_, "metadata", None) or {}
    step = metadata.get("step")
    if isinstance(step, int):
        return step
    checkpoint = getattr(tuple_, "checkpoint", None) or {}
    step = checkpoint.get("step")
    return step if isinstance(step, int) else -1


def _thread_config(thread_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id}}


async def _thread_storage_stats(saver: Any, thread_id: str) -> dict[str, int]:
    """Per-thread rows/bytes, same normalized shape as ``bench_channels``."""
    if isinstance(saver, InMemorySaver):
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
    if isinstance(saver, AsyncSqliteSaver):
        sqls = (
            ("checkpoint_rows", "checkpoint_bytes", "SELECT COUNT(*), COALESCE(SUM(LENGTH(checkpoint) + LENGTH(metadata)), 0) FROM checkpoints WHERE thread_id = ?"),
            ("write_rows", "write_bytes", "SELECT COUNT(*), COALESCE(SUM(LENGTH(value)), 0) FROM writes WHERE thread_id = ?"),
        )
        stats: dict[str, int] = {}
        for row_key, bytes_key, sql in sqls:
            async with saver.conn.execute(sql, (thread_id,)) as cursor:
                row = await cursor.fetchone()
            stats[row_key] = int(row[0])
            stats[bytes_key] = int(row[1] or 0)
        stats["blob_rows"] = 0
        stats["blob_bytes"] = 0
        return stats
    sqls = (
        ("checkpoint_rows", "checkpoint_bytes", "SELECT COUNT(*) AS rows, COALESCE(SUM(pg_column_size(checkpoint) + pg_column_size(metadata)), 0) AS bytes FROM checkpoints WHERE thread_id = %s"),
        ("blob_rows", "blob_bytes", "SELECT COUNT(*) AS rows, COALESCE(SUM(octet_length(blob)), 0) AS bytes FROM checkpoint_blobs WHERE thread_id = %s"),
        ("write_rows", "write_bytes", "SELECT COUNT(*) AS rows, COALESCE(SUM(octet_length(blob)), 0) AS bytes FROM checkpoint_writes WHERE thread_id = %s"),
    )
    stats = {}
    for row_key, bytes_key, sql in sqls:
        async with saver._cursor() as cursor:
            await cursor.execute(sql, (thread_id,))
            row = await cursor.fetchone()
        stats[row_key] = int(row["rows"])
        stats[bytes_key] = int(row["bytes"] or 0)
    return stats


async def _checkpoint_ids_with_writes(saver: Any, thread_id: str) -> set[tuple[str, str]]:
    """(checkpoint_ns, checkpoint_id) pairs that still own writes rows.

    Protected set item 3: pending/uncommitted writes are retained state, not
    garbage, so v1 refuses to delete any checkpoint that still owns writes
    rows. Production checkpoints normally accumulate their own committed
    writes rows too, so the conservative default makes pruning a no-op on
    hot threads; a policy that distinguishes in-flight from orphaned writes
    belongs to the contract's next revision, not to a fast path here.
    """
    if isinstance(saver, InMemorySaver):
        return {(ns, cp_id) for (stored_thread, ns, cp_id) in saver.writes if stored_thread == thread_id}
    if isinstance(saver, AsyncSqliteSaver):
        async with saver.conn.execute(
            "SELECT DISTINCT checkpoint_ns, checkpoint_id FROM writes WHERE thread_id = ?",
            (thread_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        return {(row[0] or "", row[1]) for row in rows}
    async with saver._cursor() as cursor:
        await cursor.execute(
            "SELECT DISTINCT checkpoint_ns, checkpoint_id FROM checkpoint_writes WHERE thread_id = %s",
            (thread_id,),
        )
        rows = await cursor.fetchall()
    return {(row[0] or "", row[1]) for row in rows}


async def _delete_checkpoint_rows(saver: Any, thread_id: str, key: tuple[str, str]) -> None:
    """Remove one checkpoint and the rows only it reachable, jointly (contract mechanics)."""
    ns, cp_id = key
    if isinstance(saver, InMemorySaver):
        saver.storage.get(thread_id, {}).get(ns, {}).pop(cp_id, None)
        saver.writes.pop((thread_id, ns, cp_id), None)
        return
    if isinstance(saver, AsyncSqliteSaver):
        await saver.conn.execute(
            "DELETE FROM checkpoints WHERE thread_id = ? AND checkpoint_ns = ? AND checkpoint_id = ?",
            (thread_id, ns, cp_id),
        )
        await saver.conn.execute(
            "DELETE FROM writes WHERE thread_id = ? AND checkpoint_ns = ? AND checkpoint_id = ?",
            (thread_id, ns, cp_id),
        )
        await saver.conn.commit()
        return
    async with saver._cursor() as cursor:
        await cursor.execute(
            "DELETE FROM checkpoints WHERE thread_id = %s AND checkpoint_ns = %s AND checkpoint_id = %s",
            (thread_id, ns, cp_id),
        )
        await cursor.execute(
            "DELETE FROM checkpoint_blobs WHERE thread_id = %s AND checkpoint_ns = %s AND version = %s",
            (thread_id, ns, cp_id),
        )
        await cursor.execute(
            "DELETE FROM checkpoint_writes WHERE thread_id = %s AND checkpoint_ns = %s AND checkpoint_id = %s",
            (thread_id, ns, cp_id),
        )


async def enforce_thread_retention(
    saver: BaseCheckpointSaver,
    thread_id: str,
    policy: RetentionPolicy | None = None,
    *,
    collect_stats: bool = True,
) -> RetentionReport:
    """Apply *policy* to one thread's checkpoints and return what happened.

    Classification walks the parent chain the same way
    ``app/gateway/checkpoint_lineage.py`` does; the resume head is the newest
    non-duration-only checkpoint by ``(step, checkpoint_id)`` and its whole
    ancestor chain is protected. Anything off that chain is only deletable
    when it is a leaf, not mid-run, not explicitly protected, free of writes
    rows under the strict guard, and matches one of the two contract-proven
    shapes. A node whose parent is already missing is left alone: partial
    damage must not be silently compounded.
    """
    effective = policy or RetentionPolicy()
    report = RetentionReport(thread_id=thread_id)
    if collect_stats:
        report.stats_before = await _thread_storage_stats(saver, thread_id)

    nodes: dict[tuple[str, str], _Node] = {}
    async for tuple_ in saver.alist(_thread_config(thread_id), limit=None):
        configurable = checkpoint_configurable(tuple_)
        cp_id = configurable.get("checkpoint_id")
        if not cp_id:
            continue
        ns = configurable.get("checkpoint_ns") or ""
        parent_ns: str | None = None
        parent_id: str | None = None
        parent_config = getattr(tuple_, "parent_config", None)
        if isinstance(parent_config, dict):
            parent = parent_config.get("configurable") or {}
            parent_ns = parent.get("checkpoint_ns") or ""
            parent_id = parent.get("checkpoint_id")
        nodes[(ns, cp_id)] = _Node(
            ns=ns,
            cp_id=cp_id,
            parent_ns=parent_ns,
            parent_id=parent_id,
            step=_node_step(tuple_),
            duration_only=is_duration_only_checkpoint(tuple_),
            mid_run=bool(getattr(tuple_, "next", None)),
        )
    if not nodes:
        return report

    children: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    for key, node in nodes.items():
        if node.parent_id is not None:
            children[(node.parent_ns, node.parent_id)].append(key)

    resumable = [key for key, node in nodes.items() if not node.duration_only]
    # Head = newest by checkpoint id. LangGraph ids are time-ordered (uuid7):
    # metadata step restarts from the fork point after a branch-resume, so it
    # is not a thread-global sequence, while max-id matches what an unsaved
    # ``aget_tuple`` resolves as the thread's latest state.
    head_key = max(resumable, key=lambda key: key[1]) if resumable else None
    report.protected_head_id = head_key[1] if head_key else None

    chain: set[tuple[str, str]] = set()
    cursor = head_key
    while cursor is not None:
        chain.add(cursor)
        node = nodes[cursor]
        cursor = (node.parent_ns, node.parent_id) if node.parent_id is not None else None

    guarded: set[tuple[str, str]] = set()
    if effective.strict_pending_write_guard:
        guarded = await _checkpoint_ids_with_writes(saver, thread_id)

    deletable: list[tuple[str, str]] = []
    for key, node in nodes.items():
        if key in chain:
            continue
        if children.get(key):
            continue
        if key[1] in effective.protect_checkpoint_ids:
            continue
        if node.mid_run:
            continue
        if key in guarded:
            continue
        if node.parent_id is not None and (node.parent_ns, node.parent_id) not in nodes:
            continue
        if node.duration_only:
            if not effective.prune_trailing_duration_leaves:
                continue
        elif not effective.prune_leaf_sibling_branches:
            continue
        deletable.append(key)

    if effective.max_delete_per_run is not None:
        deletable = deletable[: effective.max_delete_per_run]

    for key in deletable:
        await _delete_checkpoint_rows(saver, thread_id, key)
        report.deleted_checkpoint_ids.append(key[1])

    if collect_stats:
        report.stats_after = await _thread_storage_stats(saver, thread_id)
    return report
