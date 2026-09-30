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

History fast-path interaction: the trailing duration-only leaf is also the
carrier of the run-history metadata cache (``run_durations`` /
``run_message_ids``) that ``get_thread_history`` reads from the latest
checkpoint, and the parent it clones does not carry that map. Deleting the
leaf makes the next history read fall back to store scans and re-persist a
fresh leaf, so the wiring PR must sequence retention away from history reads
or adopt a policy that spares cache-carrying leaves — see the contract doc,
"History fast-path interaction (wiring requirement)".
"""

from __future__ import annotations

from collections import defaultdict
from contextlib import AbstractAsyncContextManager, nullcontext
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
    # Resume heads that survived this pass, per namespace (checkpoint_ns -> id).
    # The root namespace (the "" key) is what an unsaved ``aget_tuple`` resolves
    # as the thread's latest state; a persistent subgraph contributes its own
    # child namespace whose head is protected too and would be invisible in a
    # singular field. Consumers that only care about the thread's latest state
    # read the root key.
    protected_head_ids: dict[str, str] = field(default_factory=dict)
    deleted_checkpoint_ids: list[str] = field(default_factory=list)
    stats_before: dict[str, int] = field(default_factory=dict)
    stats_after: dict[str, int] = field(default_factory=dict)


@dataclass
class _Node:
    ns: str
    cp_id: str
    parent_ns: str | None
    parent_id: str | None
    duration_only: bool
    metadata_source: str | None = None
    carries_run_durations: bool = False
    versions: frozenset = frozenset()


def _thread_config(thread_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id}}


def _row_field(row: Any, name: str, index: int) -> Any:
    """Read one column from a DB-API row whatever row factory produced it.

    Postgres cursors are opened with ``row_factory=dict_row`` — both by this
    codebase (``deerflow/runtime/checkpointer/async_provider.py``) and inside
    ``langgraph-checkpoint-postgres`` itself (``aio.py`` opens every cursor as
    ``conn.cursor(binary=True, row_factory=dict_row)``) — so their rows are
    name-addressable and positional access raises ``KeyError: 0``. aiosqlite
    rows are plain tuples. Reading through this helper keeps the per-backend
    helpers independent of which saver opened the cursor: the Postgres leg of
    ``tests/test_checkpoint_retention_service.py`` failed on exactly that
    assumption, on six scenarios, the first time CI ran it.
    """
    try:
        return row[name]
    except (TypeError, KeyError, IndexError):
        return row[index]


def _mark_duration_leaves_without_the_marker(nodes: dict[tuple[str, str], _Node]) -> None:
    """Classify metadata-only duration leaves on backends that drop the marker.

    ``persist_run_history_metadata`` is the only writer of these checkpoints and
    stamps ``metadata["writes"]["runtime_run_duration"]``, which is what
    :func:`is_duration_only_checkpoint` reads. The Postgres saver funnels
    metadata through langgraph's ``get_serializable_checkpoint_metadata``, which
    pops ``writes`` before the row is written (``checkpoint/base/__init__.py``;
    only the Postgres savers call it), so on Postgres that marker never comes
    back — every duration leaf would look resumable and the default E1 shape
    would silently never fire on the production backend.

    The writer's other stamps survive a Postgres round trip and together are
    exact: ``source == "update"``, a non-empty accumulated ``run_durations``
    map, and the leaf being a verbatim copy of its parent (``channel_versions``
    copied unchanged — the writer only replaces ``id``/``ts``). A client
    ``update_state`` writes a newly versioned channel, so it fails the last
    condition and is never swept into this class.
    """
    for node in nodes.values():
        if node.duration_only or node.parent_id is None:
            continue
        parent = nodes.get((node.parent_ns, node.parent_id))
        if parent is None or node.metadata_source != "update" or not node.carries_run_durations:
            continue
        if node.versions and node.versions == parent.versions:
            node.duration_only = True


def _ensure_supported_saver(saver: BaseCheckpointSaver) -> None:
    """Fail fast before any row is read or written on an untested saver.

    The per-backend helpers below model exactly three storage layouts
    (memory, SQLite, Postgres) and would otherwise fall through to "assume
    Postgres" SQL for any other ``BaseCheckpointSaver``. A shallow Postgres
    saver (no ``checkpoint_blobs``/``checkpoint_writes`` tables) or a
    third-party saver would then issue DELETEs and die partway — with
    autocommit on the Postgres connection, after the ``checkpoints`` row is
    already gone. For a destructive tool, an explicit allowlist that raises
    ``NotImplementedError`` beats a partial deletion and a confusing
    traceback.
    """
    if isinstance(saver, (InMemorySaver, AsyncSqliteSaver)):
        return
    async_postgres_saver: type | None = None
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        async_postgres_saver = AsyncPostgresSaver
    except Exception:
        pass
    if async_postgres_saver is not None and isinstance(saver, async_postgres_saver):
        return
    raise NotImplementedError(f"checkpoint retention supports InMemorySaver, AsyncSqliteSaver and AsyncPostgresSaver, got {type(saver).__module__}.{type(saver).__name__}")


async def _thread_storage_stats(saver: Any, thread_id: str) -> dict[str, int]:
    """Per-thread rows/bytes, same normalized shape as ``bench_channels``."""
    if isinstance(saver, InMemorySaver):
        checkpoint_rows = checkpoint_bytes = blob_rows = blob_bytes = write_rows = write_bytes = 0
        for namespace in saver.storage.get(thread_id, {}).values():
            for checkpoint, metadata, _parent in namespace.values():
                checkpoint_rows += 1
                checkpoint_bytes += len(checkpoint[1]) + len(metadata[1])
        for (stored_thread, _ns, _channel, _version), (_type_tag, blob) in saver.blobs.items():
            if stored_thread != thread_id:
                continue
            blob_rows += 1
            blob_bytes += len(blob)
        for (stored_thread, _ns, _cp_id), writes in saver.writes.items():
            if stored_thread != thread_id:
                continue
            for _task_id, _channel, (_type_tag, blob), _path in writes.values():
                write_rows += 1
                write_bytes += len(blob)
        return {
            "logical_checkpoint_bytes": checkpoint_bytes + blob_bytes,
            "logical_write_bytes": write_bytes,
            "checkpoint_rows": checkpoint_rows,
            "checkpoint_bytes": checkpoint_bytes,
            "blob_rows": blob_rows,
            "blob_bytes": blob_bytes,
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
        stats["logical_checkpoint_bytes"] = stats["checkpoint_bytes"]
        stats["logical_write_bytes"] = stats["write_bytes"]
        return stats
    # Reachable only for the allowlisted Postgres saver (see
    # ``_ensure_supported_saver``): its checkpoint rows are split into
    # ``checkpoints`` + ``checkpoint_blobs``.
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
        stats[row_key] = int(_row_field(row, "rows", 0))
        stats[bytes_key] = int(_row_field(row, "bytes", 1) or 0)
    stats["logical_checkpoint_bytes"] = stats["checkpoint_bytes"] + stats["blob_bytes"]
    stats["logical_write_bytes"] = stats["write_bytes"]
    return stats


async def _checkpoint_ids_with_writes(saver: Any, thread_id: str) -> set[tuple[str, str]]:
    """(checkpoint_ns, checkpoint_id) pairs that still own writes rows.

    Protected set item 3: pending/uncommitted writes are retained state, not
    garbage, so v1 refuses to delete any checkpoint that still owns writes
    rows. On the memory backend ``InMemorySaver.writes`` also holds an *empty*
    dict for checkpoints whose task produced no writes — counting key presence
    would spare those phantom entries and silently disable pruning on the
    memory saver, so a pair qualifies only when its writes dict is non-empty,
    matching how :func:`_thread_storage_stats` counts rows rather than keys.
    Production checkpoints normally accumulate their own committed writes rows
    too, so the conservative default still makes pruning a no-op on hot
    threads; a policy that distinguishes in-flight from orphaned writes belongs
    to the contract's next revision, not to a fast path here.
    """
    if isinstance(saver, InMemorySaver):
        return {(ns, cp_id) for (stored_thread, ns, cp_id), writes in saver.writes.items() if stored_thread == thread_id and writes}
    if isinstance(saver, AsyncSqliteSaver):
        async with saver.conn.execute(
            "SELECT DISTINCT checkpoint_ns, checkpoint_id FROM writes WHERE thread_id = ?",
            (thread_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        # aiosqlite rows are plain tuples; the Postgres rows below are not.
        return {(row[0] or "", row[1]) for row in rows}
    async with saver._cursor() as cursor:
        await cursor.execute(
            "SELECT DISTINCT checkpoint_ns, checkpoint_id FROM checkpoint_writes WHERE thread_id = %s",
            (thread_id,),
        )
        rows = await cursor.fetchall()
    return {(_row_field(row, "checkpoint_ns", 0) or "", _row_field(row, "checkpoint_id", 1)) for row in rows}


async def _delete_checkpoint_rows(saver: Any, thread_id: str, key: tuple[str, str]) -> None:
    """Remove one checkpoint row and the writes rows it owns, jointly.

    Blob rows are handled by the survivor-reachability pass
    (:func:`_delete_unreachable_blobs`), never per-checkpoint: versions are
    shared between a checkpoint and its clones (see the contract doc).
    """
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
    # Reachable only for the allowlisted Postgres saver (see
    # ``_ensure_supported_saver``).
    async with saver._cursor() as cursor:
        await cursor.execute(
            "DELETE FROM checkpoints WHERE thread_id = %s AND checkpoint_ns = %s AND checkpoint_id = %s",
            (thread_id, ns, cp_id),
        )
        await cursor.execute(
            "DELETE FROM checkpoint_writes WHERE thread_id = %s AND checkpoint_ns = %s AND checkpoint_id = %s",
            (thread_id, ns, cp_id),
        )


async def _delete_unreachable_blobs(saver: Any, thread_id: str, survivor_versions: set) -> None:
    """Whole-thread blob GC: drop exactly the versions no surviving checkpoint
    references (memory ``saver.blobs`` / Postgres ``checkpoint_blobs``)."""
    if isinstance(saver, InMemorySaver):
        for key in [key for key in saver.blobs if key[0] == thread_id and key[3] not in survivor_versions]:
            del saver.blobs[key]
        return
    if isinstance(saver, AsyncSqliteSaver):
        return
    async with saver._cursor() as cursor:
        await cursor.execute("SELECT DISTINCT version FROM checkpoint_blobs WHERE thread_id = %s", (thread_id,))
        rows = await cursor.fetchall()
    orphans = [version for version in (_row_field(row, "version", 0) for row in rows) if version not in survivor_versions]
    if orphans:
        async with saver._cursor() as cursor:
            await cursor.execute(
                "DELETE FROM checkpoint_blobs WHERE thread_id = %s AND version = ANY(%s)",
                (thread_id, orphans),
            )


async def enforce_thread_retention(
    saver: BaseCheckpointSaver,
    thread_id: str,
    policy: RetentionPolicy | None = None,
    *,
    thread_lock: AbstractAsyncContextManager[None] | None = None,
    collect_stats: bool = True,
) -> RetentionReport:
    """Apply *policy* to one thread's checkpoints and return what happened.

    Classification walks the parent chain the same way
    ``app/gateway/checkpoint_lineage.py`` does; each namespace's resume head is
    that namespace's newest non-duration-only checkpoint by checkpoint id
    (LangGraph ids are time-ordered), and every head's whole ancestor chain is
    protected. Anything off those chains is only deletable when it is a leaf,
    not explicitly protected, free of writes rows under the strict guard, and
    matches one of the two contract-proven shapes. A node whose parent is
    already missing is left alone: partial damage must not be silently
    compounded. Only savers the deletion mechanics have been validated on are
    accepted (see :func:`_ensure_supported_saver`).

    ``max_delete_per_run`` is validated before any row is read: a negative cap
    raises ``ValueError`` rather than reaching the slice that applies it, where
    Python's negative indexing would widen the batch instead of disabling it.
    An empty thread returns a no-op report whose ``stats_after`` mirrors
    ``stats_before``, so the measurement shape does not depend on whether the
    thread had anything to classify.

    Concurrency requirement: classification and deletion are two separate
    passes over the store, so a run that forks from a node classified as a
    leaf in between leaves a dangling ``parent_config`` — the contract's own
    "converts a cleanup into a thread-level outage" failure class. Callers
    must therefore serialize per-thread mutation against the runtime writer
    by passing the thread's checkpoint lock
    (``deerflow.runtime.runs.worker._checkpoint_thread_lock(thread_id)``) as
    *thread_lock*; without one, retention must only run while the thread is
    guaranteed quiescent.

    The lock returned by ``_checkpoint_thread_lock`` is a plain, *non-reentrant*
    ``asyncio.Lock`` (``AsyncKeyedLockTable.hold``). A caller that already
    holds it and then passes it here self-deadlocks — which matters because
    the runtime's own ``persist_run_history_metadata`` enters that same lock
    before writing, so a post-run-hook call site must invoke retention *after*
    releasing it, not from inside the held section.
    """
    _ensure_supported_saver(saver)
    effective = policy or RetentionPolicy()
    if effective.max_delete_per_run is not None and effective.max_delete_per_run < 0:
        # Fail closed *before* any store read. ``deletable[:cap]`` with a
        # negative cap selects every candidate except the last few, so an
        # invalid value meant to disable the run would instead maximize it —
        # a batch bound must never widen a destructive pass.
        raise ValueError(f"max_delete_per_run must be >= 0, got {effective.max_delete_per_run}")
    report = RetentionReport(thread_id=thread_id)
    lock: AbstractAsyncContextManager[None] = thread_lock if thread_lock is not None else nullcontext()
    async with lock:
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
            checkpoint = getattr(tuple_, "checkpoint", None) or {}
            channel_versions = checkpoint.get("channel_versions")
            metadata = getattr(tuple_, "metadata", None) or {}
            metadata = metadata if isinstance(metadata, dict) else {}
            run_durations = metadata.get("run_durations")
            nodes[(ns, cp_id)] = _Node(
                ns=ns,
                cp_id=cp_id,
                parent_ns=parent_ns,
                parent_id=parent_id,
                duration_only=is_duration_only_checkpoint(tuple_),
                metadata_source=metadata.get("source"),
                carries_run_durations=isinstance(run_durations, dict) and bool(run_durations),
                versions=frozenset(channel_versions.values()) if isinstance(channel_versions, dict) else frozenset(),
            )
        if not nodes:
            # Nothing to classify: an empty (or unknown) thread is a no-op, but
            # the before/after pair is part of the report contract, so it is
            # mirrored rather than truncated — a caller aggregating measurements
            # must not have to special-case "thread had no checkpoints".
            if collect_stats:
                report.stats_after = dict(report.stats_before)
            return report
        _mark_duration_leaves_without_the_marker(nodes)

        children: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
        for key, node in nodes.items():
            if node.parent_id is not None:
                children[(node.parent_ns, node.parent_id)].append(key)

        resumable = [key for key, node in nodes.items() if not node.duration_only]
        # Head = newest by checkpoint id. LangGraph ids are time-ordered (uuid7):
        # metadata step restarts from the fork point after a branch-resume, so it
        # is not a thread-global sequence, while max-id matches what an unsaved
        # ``aget_tuple`` resolves as the thread's latest state.
        #
        # Heads are selected *per namespace*. ``alist`` is called with the thread
        # id alone, so ``nodes`` holds every namespace in the thread — a
        # persistent subgraph (compiled with ``checkpointer=True``) keeps its own
        # checkpoints under e.g. ``tools:<task>``. Protecting only one global
        # head leaves the child namespace's latest checkpoint looking like an
        # off-chain sibling leaf, which the opt-in E2 shape would then delete,
        # rolling that graph's saved state back one step.
        heads: dict[str, tuple[str, str]] = {}
        for key in resumable:
            current = heads.get(key[0])
            if current is None or key[1] > current[1]:
                heads[key[0]] = key
        report.protected_head_ids = {ns: key[1] for ns, key in heads.items()}

        chain: set[tuple[str, str]] = set()
        for head in heads.values():
            cursor: tuple[str, str] | None = head
            while cursor is not None:
                if cursor not in nodes:
                    # A head whose ancestor row is missing (partial damage from
                    # an earlier policy revision or manual cleanup) ends this
                    # walk instead of crashing the whole pass; the deletable loop
                    # below already leaves nodes with missing parents alone.
                    break
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

        # Blob GC, contract deletion mechanics: a blob row is an orphan only if no
        # SURVIVING checkpoint references its version. A real duration-only leaf
        # copies its parent's channel_versions verbatim, so its blobs are the
        # parent's rows — deleting "blobs keyed by the removed checkpoint's own
        # versions" would corrupt the surviving state.
        deleted_keys = set(deletable)
        survivor_versions: set[Any] = set()
        for key, node in nodes.items():
            if key not in deleted_keys:
                survivor_versions.update(node.versions)

        for key in deletable:
            await _delete_checkpoint_rows(saver, thread_id, key)
            report.deleted_checkpoint_ids.append(key[1])

        if deletable:
            await _delete_unreachable_blobs(saver, thread_id, survivor_versions)

        if collect_stats:
            report.stats_after = await _thread_storage_stats(saver, thread_id)
        return report
