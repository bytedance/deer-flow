"""Dual-mode checkpoint channel safety: mode freeze, metadata markers, and the fail-closed gate.

Checkpointer storage runs in ``full`` mode (whole-snapshot channel values) or
``delta`` mode (LangGraph ``DeltaChannel``: sentinel blobs + per-step writes).
The mode is process-frozen at agent-build time, stamped into each checkpoint's
metadata on write, and enforced before every state access: a full-mode process
opening a delta thread raises :class:`CheckpointModeMismatchError` instead of
silently materializing empty state. Delta-mode processes read legacy full
checkpoints transparently, so full -> delta is the supported migration path.
"""

from __future__ import annotations

from typing import Any

from deerflow.config.database_config import CheckpointChannelMode

INTERNAL_CHECKPOINT_MODE_KEY = "__deerflow_checkpoint_channel_mode"
CHECKPOINT_MODE_METADATA_KEY = "deerflow_checkpoint_channel_mode"


class CheckpointModeMismatchError(RuntimeError):
    """Raised before a full-mode graph reads a Delta checkpoint."""


class CheckpointModeReconfigurationError(RuntimeError):
    """Raised when a process attempts to hot-switch its persistence mode."""


_frozen_checkpoint_channel_mode: CheckpointChannelMode | None = None


def frozen_checkpoint_channel_mode() -> CheckpointChannelMode | None:
    """Return the process-frozen checkpoint channel mode, if already frozen."""
    return _frozen_checkpoint_channel_mode


def freeze_checkpoint_channel_mode(mode: CheckpointChannelMode) -> CheckpointChannelMode:
    global _frozen_checkpoint_channel_mode
    if _frozen_checkpoint_channel_mode is None:
        _frozen_checkpoint_channel_mode = mode
    elif _frozen_checkpoint_channel_mode != mode:
        raise CheckpointModeReconfigurationError("checkpoint_channel_mode is restart-required and cannot change in a running process")
    return _frozen_checkpoint_channel_mode


def inject_checkpoint_mode(config: dict[str, Any], mode: CheckpointChannelMode) -> None:
    configurable = config.setdefault("configurable", {})
    configurable[INTERNAL_CHECKPOINT_MODE_KEY] = mode
    metadata = config.setdefault("metadata", {})
    if mode == "delta":
        metadata[CHECKPOINT_MODE_METADATA_KEY] = "delta"
    else:
        metadata.pop(CHECKPOINT_MODE_METADATA_KEY, None)


def checkpoint_metadata_uses_delta(metadata: Any) -> bool:
    """Whether checkpoint metadata carries the delta-mode marker."""
    if not metadata:
        return False
    if metadata.get(CHECKPOINT_MODE_METADATA_KEY) == "delta":
        return True
    counters = metadata.get("counters_since_delta_snapshot")
    return isinstance(counters, dict) and "messages" in counters


def checkpoint_tuple_uses_delta(checkpoint_tuple: Any) -> bool:
    if checkpoint_tuple is None:
        return False
    return checkpoint_metadata_uses_delta(getattr(checkpoint_tuple, "metadata", {}) or {})


def state_snapshot_uses_delta(snapshot: Any) -> bool:
    """Whether a materialized ``StateSnapshot`` originates from a delta checkpoint."""
    if snapshot is None:
        return False
    return checkpoint_metadata_uses_delta(getattr(snapshot, "metadata", {}) or {})


def raise_if_snapshot_incompatible(snapshot: Any, mode: CheckpointChannelMode) -> None:
    """Fail closed when a full-mode process materialized a delta checkpoint.

    Runs on the ``StateSnapshot`` returned by ``get_state``/``get_state_history``,
    so reads cost a single checkpoint fetch: the marker lives in
    ``snapshot.metadata``. Reading the blob is harmless; silently *using* the
    empty/partial state is the danger, and the caller never receives it.
    """
    if mode == "full" and state_snapshot_uses_delta(snapshot):
        raise CheckpointModeMismatchError("Thread requires delta mode; materialize and convert its checkpoints before using full mode.")


def ensure_checkpoint_mode_compatible(checkpointer: Any, config: dict[str, Any], mode: CheckpointChannelMode) -> None:
    """Pre-write gate: a write cannot be un-applied, so it checks ahead of time.

    Reads use :func:`raise_if_snapshot_incompatible` on the returned snapshot
    instead, avoiding the extra fetch.
    """
    if mode == "delta":
        return
    if checkpoint_tuple_uses_delta(checkpointer.get_tuple(config)):
        raise CheckpointModeMismatchError("Thread requires delta mode; materialize and convert its checkpoints before using full mode.")


async def aensure_checkpoint_mode_compatible(checkpointer: Any, config: dict[str, Any], mode: CheckpointChannelMode) -> None:
    if mode == "delta":
        return
    if checkpoint_tuple_uses_delta(await checkpointer.aget_tuple(config)):
        raise CheckpointModeMismatchError("Thread requires delta mode; materialize and convert its checkpoints before using full mode.")
