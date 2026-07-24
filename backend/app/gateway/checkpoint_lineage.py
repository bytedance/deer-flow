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


def is_duration_only_checkpoint(checkpoint_tuple: Any) -> bool:
    writes = checkpoint_metadata(checkpoint_tuple).get("writes")
    return isinstance(writes, dict) and "runtime_run_duration" in writes


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
    represent an addressable conversation state and are skipped.
    """

    if message_id not in {_message_id(message) for message in checkpoint_messages(head_checkpoint)}:
        raise CheckpointLineageIntegrityError("Target message is not present in the checkpoint head")

    current = head_checkpoint
    visited: set[tuple[str, str, str]] = set()
    current_identity = _checkpoint_identity(current)
    if current_identity is not None:
        visited.add(current_identity)

    # Each step performs one ancestor read, but normal branch/regenerate
    # histories cross the target boundary within 1–3 reads. Keep max_depth as
    # a conservative safety cap for valid histories with many intermediate or
    # duration-only checkpoints.
    for _ in range(max_depth):
        parent_config = getattr(current, "parent_config", None)
        if not isinstance(parent_config, dict):
            raise CheckpointParentMissingError("Checkpoint lineage ended before the target message")

        parent = await accessor.aget(parent_config)
        parent_identity = _checkpoint_identity(parent)
        requested_parent_identity = _config_identity(parent_config)
        if parent_identity is None or not _checkpoint_exists(parent) or (requested_parent_identity is not None and parent_identity != requested_parent_identity):
            raise CheckpointLineageIntegrityError("Checkpoint parent link is not addressable")
        if parent_identity is not None:
            if parent_identity in visited:
                raise CheckpointLineageIntegrityError("Checkpoint lineage contains a cycle")
            visited.add(parent_identity)

        if is_duration_only_checkpoint(parent):
            current = parent
            continue

        parent_message_ids = {_message_id(message) for message in checkpoint_messages(parent)}
        if message_id not in parent_message_ids:
            return parent
        current = parent

    raise CheckpointLineageIntegrityError(f"Checkpoint lineage exceeded the scan limit ({max_depth})")


def find_checkpoint_before_message_chronologically(
    checkpoints: Sequence[Any],
    message_id: str,
) -> tuple[Any | None, bool]:
    """Return ``(replay_base, target_found)`` from newest-first history.

    This is a compatibility fallback for imported or legacy checkpoints that do
    not carry ``parent_config`` links. Callers must prefer the lineage walk when
    links are available because a chronological scan cannot distinguish sibling
    checkpoint branches. Duration-only checkpoints are ignored, and only
    checkpoints with an addressable id can become the replay base.
    """

    previous_checkpoint = None
    for checkpoint_tuple in reversed(checkpoints):
        if is_duration_only_checkpoint(checkpoint_tuple):
            continue
        message_ids = {_message_id(message) for message in checkpoint_messages(checkpoint_tuple)}
        if message_id in message_ids:
            return previous_checkpoint, True
        if checkpoint_configurable(checkpoint_tuple).get("checkpoint_id"):
            previous_checkpoint = checkpoint_tuple
    return None, False
