"""Safe references to encrypted, immutable run tracing snapshots."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from deerflow.tracing.profiles import RunTracingSnapshot

TRACING_SNAPSHOT_ID_KEY = "deerflow_tracing_snapshot_id"
TRACING_AGENT_NAME_KEY = "deerflow_tracing_agent_name"
TRACING_PINNED_KEY = "deerflow_tracing_pinned"
TRACING_MANAGED_KEY = "deerflow_tracing_managed"
TRACING_PARENT_CONTEXT_KEY = "tracing_parent_contexts"
TRACING_REFERENCE_KEYS = frozenset({TRACING_SNAPSHOT_ID_KEY, TRACING_AGENT_NAME_KEY})
TRACING_CHECKPOINT_KEYS = TRACING_REFERENCE_KEYS | {TRACING_MANAGED_KEY}
TRACING_SERVER_OWNED_KEYS = TRACING_CHECKPOINT_KEYS | {TRACING_PINNED_KEY, TRACING_PARENT_CONTEXT_KEY}
ROOT_TRACING_BOUND_KEY = "__deerflow_root_tracing_bound"


def snapshot_references(snapshot: RunTracingSnapshot | None) -> dict[str, str]:
    """Project only the non-secret identity allowed in persisted run data."""
    if snapshot is None:
        return {}
    return {TRACING_SNAPSHOT_ID_KEY: snapshot.snapshot_id, TRACING_AGENT_NAME_KEY: snapshot.agent_name}


def restore_snapshot(references: Mapping[str, Any], *, user_id: str, agent_name: str | None = None, app_config: Any | None = None) -> RunTracingSnapshot | None:
    """Restore an existing snapshot, never resolve today's profile on recovery."""
    from deerflow.tracing.profiles import canonical_agent_name, resolve_run_snapshot

    snapshot_id = references.get(TRACING_SNAPSHOT_ID_KEY)
    parent_agent_name = references.get(TRACING_AGENT_NAME_KEY)
    if snapshot_id is None and parent_agent_name is None:
        if references.get(TRACING_MANAGED_KEY):
            raise ValueError("Managed run tracing snapshot references are missing")
        return None
    if not isinstance(snapshot_id, str) or not snapshot_id or not isinstance(parent_agent_name, str) or not parent_agent_name:
        raise ValueError("Invalid tracing snapshot references")
    if agent_name is not None and canonical_agent_name(agent_name) != canonical_agent_name(parent_agent_name):
        raise ValueError("Run agent does not match the tracing snapshot")
    resolver_kwargs = {"app_config": app_config} if app_config is not None else {}
    snapshot = resolve_run_snapshot(parent_agent_name, user_id, snapshot_id=snapshot_id, **resolver_kwargs)
    if snapshot is None:
        raise ValueError("Run tracing snapshot is unavailable")
    return snapshot


def stamp_snapshot_references(target: dict[str, Any], snapshot: RunTracingSnapshot | None) -> None:
    for key in TRACING_SERVER_OWNED_KEYS:
        target.pop(key, None)
    target.update(snapshot_references(snapshot))
    if snapshot is not None:
        target[TRACING_MANAGED_KEY] = True
