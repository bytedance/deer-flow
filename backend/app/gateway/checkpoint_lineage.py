"""Shared helpers for resolving replay checkpoints on one checkpoint lineage."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any


class CheckpointLineageError(RuntimeError):
    """Raised when a requested checkpoint ancestor cannot be resolved safely."""


class CheckpointParentMissingError(CheckpointLineageError):
    """Raised when a legacy checkpoint does not record its parent link."""


class CheckpointLineageIntegrityError(CheckpointLineageError):
    """Raised when recorded checkpoint lineage is present but unsafe to use."""


def checkpoint_messages(checkpoint_tuple: Any) -> list[Any]:
    values = getattr(checkpoint_tuple, "values", None)
    if isinstance(values, dict):
        messages = values.get("messages", [])
        return list(messages) if isinstance(messages, list) else []
    checkpoint = getattr(checkpoint_tuple, "checkpoint", None) or {}
    channel_values = checkpoint.get("channel_values", {}) if isinstance(checkpoint, dict) else {}
    messages = channel_values.get("messages", []) if isinstance(channel_values, dict) else []
    return list(messages) if isinstance(messages, list) else []


def checkpoint_configurable(checkpoint_tuple: Any) -> dict[str, Any]:
    config = getattr(checkpoint_tuple, "config", None) or {}
    configurable = config.get("configurable", {}) if isinstance(config, dict) else {}
    return dict(configurable) if isinstance(configurable, dict) else {}


def checkpoint_metadata(checkpoint_tuple: Any) -> dict[str, Any]:
    metadata = getattr(checkpoint_tuple, "metadata", None) or {}
    return dict(metadata) if isinstance(metadata, dict) else {}


def _has_postgres_stamps(metadata: dict[str, Any]) -> bool:
    """The stamp-fallback gate shared by the classifier and the walk probe.

    One gate, two consumers: if the classifier's fallback tier is ever
    widened, this predicate widens with it and the lineage walk keeps
    fetching the grandparent that the fallback will require. Re-encoding the
    gate in the probe would silently break that pairing — the walk would stop
    prefetching, every Postgres duration leaf would fall back to
    ``parent=None``, and the refusal tier would return the original bug.
    """

    if metadata.get("source") != "update":
        return False
    return "run_durations" in metadata or "run_message_ids" in metadata


def is_duration_only_checkpoint(checkpoint_tuple: Any, *, parent: Any | None = None, stamp_fallback: bool = True, versions: dict[str, Any] | None = None, parent_versions: dict[str, Any] | None = None) -> bool:
    """Return whether the tuple is a metadata-only run-duration checkpoint.

    ``persist_run_history_metadata`` (``deerflow.runtime.runs.worker``) is the
    only writer of these checkpoints. It stamps
    ``metadata["writes"]["runtime_run_duration"]``, and the memory and SQLite
    savers round-trip that marker unchanged — so whenever ``writes`` is
    present it is authoritative: its per-writer key classifies the leaf
    exactly (a title or goal leaf carries ``runtime_interrupt_title`` /
    ``goal``, a graph step carries its channel writes, and none of them is a
    duration checkpoint).

    The Postgres savers instead funnel metadata through langgraph's
    ``get_serializable_checkpoint_metadata``, which pops ``writes`` before
    the row lands (``langgraph/checkpoint/postgres/aio.py``; no other saver
    calls it) — so on Postgres the marker never comes back and every duration
    checkpoint would look like an addressable state to the replay and history
    paths. The writer's index keys (``run_durations`` and
    ``run_message_ids``) and ``source == "update"`` do survive that round
    trip, but they are not proof on their own: ``_ensure_interrupted_title``
    and ``write_thread_goal`` copy the head's metadata and thereby inherit
    the stamps while changing a real channel. The fallback therefore also
    requires the duration writer's shape — it clones the parent's
    ``channel_versions`` verbatim (``id``/``ts`` only), while a state-changing
    leaf bumps at least one version — which is what passing ``parent``
    enables. Without a resolvable parent the stamps are refused: the cost of
    scanning one metadata-only copy is a state-equivalent base, the cost of
    skipping a goal leaf is the goal itself.

    Langgraph's ``update_state`` paths (rollback restore, compaction, manual
    updates) cannot inherit the stamps at all: they persist metadata built
    from scratch (``{"source": "update", "step", "parents", ...}``), and
    ``get_checkpoint_metadata`` merges only scalar values from config
    metadata, so dict-valued stamps never leak in either.

    Destructive callers must not rely on the fallback — pass
    ``stamp_fallback=False`` and confirm by shape instead, as
    ``checkpoint_retention._mark_duration_leaves_without_the_marker`` does.
    """

    metadata = checkpoint_metadata(checkpoint_tuple)
    writes = metadata.get("writes")
    if isinstance(writes, dict):
        return "runtime_run_duration" in writes
    if not stamp_fallback or parent is None:
        return False
    if not _has_postgres_stamps(metadata):
        return False
    return _copies_parent_verbatim(checkpoint_tuple, parent, versions=versions, parent_versions=parent_versions)


def has_duration_stamps_without_marker(checkpoint_tuple: Any) -> bool:
    """Whether the tuple reaches the Postgres stamp-fallback tier.

    Reaching the tier makes the tuple a duration-copy *candidate*, not a
    verdict: title and goal leaves inherit the same stamps. Callers that can
    resolve the parent tuple pass it to :func:`is_duration_only_checkpoint`
    for the shape check; this predicate exists so the lineage walk only pays
    the extra grandparent read when the marker tier could not decide.
    """

    metadata = checkpoint_metadata(checkpoint_tuple)
    if isinstance(metadata.get("writes"), dict):
        return False
    return _has_postgres_stamps(metadata)


def _sync_versions(checkpointer: Any | None, snapshot: Any) -> dict[str, Any] | None:
    """Versions for *snapshot*, re-reading the raw tuple when it lacks them."""

    if snapshot is None:
        return None
    versions = _snapshot_versions(snapshot)
    if versions is not None:
        return versions
    getter = getattr(checkpointer, "get_tuple", None)
    config = getattr(snapshot, "config", None)
    if callable(getter) and isinstance(config, dict):
        try:
            return _snapshot_versions(getter(config))
        except Exception:
            return None
    return None


def _snapshot_versions(obj: Any) -> dict[str, Any] | None:
    """Channel versions persisted on a tuple or snapshot, when exposed.

    Raw checkpoint tuples carry ``checkpoint.channel_versions``; the degraded
    ``_RawCheckpointSnapshot`` exposes the same map as ``channel_versions``;
    langgraph's materialized ``StateSnapshot`` exposes neither, so the walk
    falls back to the persisted raw tuple.
    """

    checkpoint = getattr(obj, "checkpoint", None)
    if isinstance(checkpoint, dict):
        versions = checkpoint.get("channel_versions")
        if isinstance(versions, dict):
            return versions
    versions = getattr(obj, "channel_versions", None)
    if isinstance(versions, dict):
        return versions
    return None


def _history_identity(checkpoint_tuple: Any) -> tuple[str, str, str] | None:
    return _config_identity(getattr(checkpoint_tuple, "config", {}) or {})


async def resolve_history_versions(accessor: Any, checkpoints: Sequence[Any]) -> dict[tuple[str, str, str], Any]:
    """Persisted channel versions for a history window, keyed by config identity."""

    versions: dict[tuple[str, str, str], Any] = {}
    for checkpoint_tuple in checkpoints:
        identity = _history_identity(checkpoint_tuple)
        if identity is not None and identity not in versions:
            versions[identity] = await resolve_channel_versions(accessor, checkpoint_tuple)
    return versions


async def resolve_channel_versions(accessor: Any, snapshot: Any) -> dict[str, Any] | None:
    """Persisted ``channel_versions`` for *snapshot*, fetching raw when absent.

    Materialized accessor snapshots (``StateSnapshot``) do not carry the
    checkpoint payload, so the version maps the Postgres stamp fallback needs
    are re-read from the raw checkpoint tuple. The degraded raw read path
    already exposes the same map, so it never needs the extra read.
    """

    versions = _snapshot_versions(snapshot)
    if versions is not None:
        return versions
    getter = getattr(accessor, "aget_tuple", None)
    config = getattr(snapshot, "config", None)
    if callable(getter) and isinstance(config, dict):
        try:
            tup = await getter(config)
        except Exception:
            return None
        return _snapshot_versions(tup)
    return None


def _copies_parent_verbatim(checkpoint_tuple: Any, parent: Any, *, versions: dict[str, Any] | None = None, parent_versions: dict[str, Any] | None = None) -> bool:
    """Whether the leaf cloned its parent's ``channel_versions`` unchanged.

    Same rule as ``checkpoint_retention``'s shape check: the duration writer
    replaces only ``id``/``ts``, while any state-changing writer bumps at
    least one channel version.
    """

    versions = versions if isinstance(versions, dict) else _snapshot_versions(checkpoint_tuple)
    parent_versions = parent_versions if isinstance(parent_versions, dict) else _snapshot_versions(parent)
    if not isinstance(versions, dict) or not isinstance(parent_versions, dict) or not versions:
        return False
    return frozenset(versions.values()) == frozenset(parent_versions.values())


def history_parent_index(checkpoints: Sequence[Any]) -> dict[tuple[str, str], Any]:
    """Index a checkpoint window by ``(namespace, id)`` for parent lookups."""

    index: dict[tuple[str, str], Any] = {}
    for checkpoint_tuple in checkpoints:
        configurable = checkpoint_configurable(checkpoint_tuple)
        checkpoint_id = configurable.get("checkpoint_id")
        if isinstance(checkpoint_id, str) and checkpoint_id:
            index[(str(configurable.get("checkpoint_ns") or ""), checkpoint_id)] = checkpoint_tuple
    return index


def parent_from_history_index(checkpoint_tuple: Any, index: dict[tuple[str, str], Any]) -> Any | None:
    """Resolve the tuple's parent inside an indexed window, or ``None``.

    ``None`` means the parent is outside the window (or the tuple predates
    parent links); the stamp fallback then refuses to classify, which keeps a
    goal leaf at the window boundary addressable.
    """

    parent_config = getattr(checkpoint_tuple, "parent_config", None)
    if not isinstance(parent_config, dict):
        return None
    configurable = parent_config.get("configurable") or {}
    checkpoint_id = configurable.get("checkpoint_id")
    if not isinstance(checkpoint_id, str) or not checkpoint_id:
        return None
    return index.get((str(configurable.get("checkpoint_ns") or ""), checkpoint_id))


def has_pending_tasks(checkpoint_tuple: Any) -> bool:
    """Return whether *checkpoint_tuple* still has graph work scheduled.

    A replay base must be a state the thread was at rest in. A mid-run
    checkpoint owns the writes of the node that was about to run, and resuming
    from it replays them — re-adding the very turn the replay is meant to
    replace. Message ids alone cannot detect this, because middleware may
    rewrite a message's id in the same run that produced it.

    ``next`` is not derivable on the degraded raw-checkpoint read path, which
    reports no tasks at all. Absence of evidence therefore stays permissive:
    those reads keep selecting the same base they always did.
    """

    return bool(getattr(checkpoint_tuple, "next", None))


def _message_id(message: Any) -> str | None:
    value = getattr(message, "id", None)
    if value is None and isinstance(message, dict):
        value = message.get("id")
    return str(value) if value else None


def _config_identity(config: dict[str, Any]) -> tuple[str, str, str] | None:
    configurable = config.get("configurable", {})
    thread_id = configurable.get("thread_id")
    checkpoint_ns = configurable.get("checkpoint_ns", "")
    checkpoint_id = configurable.get("checkpoint_id")
    if not isinstance(thread_id, str) or not thread_id or not isinstance(checkpoint_id, str) or not checkpoint_id:
        return None
    return thread_id, str(checkpoint_ns or ""), checkpoint_id


def _checkpoint_identity(checkpoint_tuple: Any) -> tuple[str, str, str] | None:
    return _config_identity(getattr(checkpoint_tuple, "config", {}) or {})


def _checkpoint_exists(checkpoint_tuple: Any) -> bool:
    """Distinguish a persisted empty checkpoint from an accessor miss.

    LangGraph represents a missing explicit ``checkpoint_id`` as an empty
    snapshot that echoes the requested config. Persisted snapshots always
    carry metadata, a creation timestamp, or a raw checkpoint payload.
    """

    explicit = getattr(checkpoint_tuple, "checkpoint_exists", None)
    if isinstance(explicit, bool):
        return explicit
    if getattr(checkpoint_tuple, "metadata", None) is not None:
        return True
    if getattr(checkpoint_tuple, "created_at", None) is not None:
        return True
    return isinstance(getattr(checkpoint_tuple, "checkpoint", None), dict)


async def find_checkpoint_before_message(
    accessor: Any,
    head_checkpoint: Any,
    message_id: str,
    *,
    max_depth: int,
) -> Any:
    """Walk one parent lineage and return the first checkpoint before ``message_id``.

    Following ``parent_config`` is important after a regenerate: a thread can contain
    sibling checkpoint branches, and a global time-ordered scan can otherwise select
    a checkpoint from the wrong branch. Duration-only metadata checkpoints do not
    represent an addressable conversation state and are skipped, and so are
    checkpoints that still have pending tasks (see :func:`has_pending_tasks`).
    """

    if message_id not in {_message_id(message) for message in checkpoint_messages(head_checkpoint)}:
        raise CheckpointLineageIntegrityError("Target message is not present in the checkpoint head")

    current = head_checkpoint
    visited: set[tuple[str, str, str]] = set()
    current_identity = _checkpoint_identity(current)
    if current_identity is not None:
        visited.add(current_identity)

    # Each distinct ancestor is read once; a Postgres stamp candidate also
    # needs its grandparent for the shape check, and that grandparent is the
    # next iteration's parent, so it is carried over instead of re-read.
    # Normal branch/regenerate histories cross the target boundary within
    # 1–3 reads. Keep max_depth as a conservative safety cap for valid
    # histories with many intermediate or duration-only checkpoints.
    prefetched_parent = None
    for _ in range(max_depth):
        parent_config = getattr(current, "parent_config", None)
        if not isinstance(parent_config, dict):
            raise CheckpointParentMissingError("Checkpoint lineage ended before the target message")

        parent = prefetched_parent if prefetched_parent is not None else await accessor.aget(parent_config)
        prefetched_parent = None
        parent_identity = _checkpoint_identity(parent)
        requested_parent_identity = _config_identity(parent_config)
        if parent_identity is None or not _checkpoint_exists(parent) or (requested_parent_identity is not None and parent_identity != requested_parent_identity):
            raise CheckpointLineageIntegrityError("Checkpoint parent link is not addressable")
        if parent_identity is not None:
            if parent_identity in visited:
                raise CheckpointLineageIntegrityError("Checkpoint lineage contains a cycle")
            visited.add(parent_identity)

        grandparent = None
        if has_duration_stamps_without_marker(parent):
            # Postgres popped the marker; the stamps also sit on title and
            # goal leaves, so confirm the verbatim-copy shape against the
            # grandparent before skipping. An unresolvable grandparent leaves
            # the parent addressable, which only ever costs one extra scanned
            # state-equivalent copy.
            gp_config = getattr(parent, "parent_config", None)
            if isinstance(gp_config, dict):
                candidate = await accessor.aget(gp_config)
                if _checkpoint_exists(candidate):
                    grandparent = candidate
        if is_duration_only_checkpoint(parent, parent=grandparent, versions=await resolve_channel_versions(accessor, parent), parent_versions=await resolve_channel_versions(accessor, grandparent) if grandparent is not None else None):
            prefetched_parent = grandparent
            current = parent
            continue

        parent_message_ids = {_message_id(message) for message in checkpoint_messages(parent)}
        if message_id not in parent_message_ids and not has_pending_tasks(parent):
            return parent
        current = parent

    raise CheckpointLineageIntegrityError(f"Checkpoint lineage exceeded the scan limit ({max_depth})")


def find_checkpoint_before_message_chronologically(
    checkpoints: Sequence[Any],
    message_id: str,
    *,
    history_versions: dict[tuple[str, str, str], Any] | None = None,
    checkpointer: Any | None = None,
) -> tuple[Any | None, bool]:
    """Return ``(replay_base, target_found)`` from newest-first history.

    This is a compatibility fallback for imported or legacy checkpoints that do
    not carry ``parent_config`` links. Callers must prefer the lineage walk when
    links are available because a chronological scan cannot distinguish sibling
    checkpoint branches. Duration-only checkpoints are ignored, and only settled
    checkpoints (see :func:`has_pending_tasks`) with an addressable id can become
    the replay base.
    """

    previous_checkpoint = None
    history_index = history_parent_index(checkpoints)
    for checkpoint_tuple in reversed(checkpoints):
        parent = parent_from_history_index(checkpoint_tuple, history_index)
        versions = history_versions.get(_history_identity(checkpoint_tuple)) if history_versions is not None else _sync_versions(checkpointer, checkpoint_tuple)
        parent_versions = history_versions.get(_history_identity(parent)) if (history_versions is not None and parent is not None) else _sync_versions(checkpointer, parent)
        if is_duration_only_checkpoint(checkpoint_tuple, parent=parent, versions=versions, parent_versions=parent_versions):
            continue
        message_ids = {_message_id(message) for message in checkpoint_messages(checkpoint_tuple)}
        if message_id in message_ids:
            return previous_checkpoint, True
        if checkpoint_configurable(checkpoint_tuple).get("checkpoint_id") and not has_pending_tasks(checkpoint_tuple):
            previous_checkpoint = checkpoint_tuple
    return None, False
