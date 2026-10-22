"""Bind safe tracing references after authenticating one run admission."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Mapping
from typing import Any

from fastapi import HTTPException

from app.gateway.deps import get_checkpointer
from deerflow.runtime.tracing_snapshot import TRACING_CHECKPOINT_KEYS, TRACING_PINNED_KEY, TRACING_SERVER_OWNED_KEYS, restore_snapshot, stamp_snapshot_references
from deerflow.tracing.profiles import TracingControlError, TracingUnavailableError, protect_run_snapshot, release_run_snapshot, resolve_run_snapshot
from deerflow.utils.file_io import await_drained

logger = logging.getLogger(__name__)


def tracing_database_identity(config: Any) -> str | None:
    """Identify the unified storage a startup-created saver can cover."""
    database = getattr(config, "database", None)
    if getattr(config, "checkpointer", None) is not None or getattr(database, "backend", None) not in {"sqlite", "postgres"}:
        return None
    identity = [database.backend, database.app_sync_sqlalchemy_url, getattr(database, "postgres_schema", "")]
    return hashlib.sha256(json.dumps(identity).encode()).hexdigest()


def _managed_authority(state: Any, config: Any) -> bool:
    authority = getattr(state, "tracing_gc_authority", None)
    return bool(isinstance(authority, tuple) and len(authority) == 2 and authority[0] is not None and authority[0] is getattr(state, "checkpointer", None) and authority[1] is not None and authority[1] == tracing_database_identity(config))


def capture_run_tracing_snapshot(state: Any, agent_name: str | None, user_id: str, *, app_config: Any | None = None):
    """Capture against the actual startup saver, including scheduler admissions."""
    from deerflow.config.app_config import get_app_config

    try:
        current = app_config if app_config is not None else get_app_config()
    except Exception:
        raise TracingUnavailableError("Tracing authority is unavailable; the run was not admitted") from None
    return resolve_run_snapshot(agent_name, user_id, managed_admission=_managed_authority(state, current), app_config=current)


async def admit_run_tracing(
    request: Any,
    config: dict[str, Any],
    run_metadata: dict[str, Any],
    *,
    thread_id: str,
    agent_name: str | None,
    user_id: str,
    resume: bool = False,
    scheduled_references: Mapping[str, Any] | None = None,
    app_config: Any | None = None,
) -> None:
    """Resolve new profiles; resumed/queued work restores its original snapshot."""
    for carrier in (run_metadata, *(config.get(section) for section in ("context", "configurable", "metadata"))):
        if isinstance(carrier, dict):
            for key in TRACING_SERVER_OWNED_KEYS:
                carrier.pop(key, None)
    try:
        resolver_kwargs = {"app_config": app_config} if app_config is not None else {}
        references = scheduled_references
        if resume:
            checkpoint_config = {"configurable": {**(config.get("configurable") or {}), "thread_id": thread_id}}
            checkpoint = await get_checkpointer(request).aget_tuple(checkpoint_config)
            metadata = getattr(checkpoint, "metadata", None) or {}
            references = {key: metadata[key] for key in TRACING_CHECKPOINT_KEYS if key in metadata}
        if references is not None:
            state = getattr(getattr(request, "app", None), "state", None)

            def restore():
                from deerflow.config.app_config import get_app_config

                current = app_config if app_config is not None else get_app_config()
                frozen = restore_snapshot(references, user_id=user_id, agent_name=agent_name, **resolver_kwargs)
                if frozen is not None and not _managed_authority(state, current):
                    protect_run_snapshot(frozen.snapshot_id, user_id, app_config=current)
                return frozen

            snapshot = await asyncio.to_thread(restore)
        else:
            state = getattr(getattr(request, "app", None), "state", None)
            snapshot = await asyncio.to_thread(capture_run_tracing_snapshot, state, agent_name, user_id, **resolver_kwargs)
    except TracingControlError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)}) from None
    except ValueError:
        raise HTTPException(status_code=409, detail="The run tracing snapshot is unavailable or does not match its Agent") from None
    stamp_snapshot_references(run_metadata, snapshot)
    if snapshot is not None and references is not None:
        run_metadata[TRACING_PINNED_KEY] = True
    stamp_snapshot_references(config.setdefault("metadata", {}), snapshot)
    stamp_snapshot_references(config.setdefault("context", {}), snapshot)


async def release_unused_tracing_capture(metadata: Mapping[str, Any], *, user_id: str, app_config: Any | None = None) -> None:
    """Retire a fresh capture after a known refusal or idempotent reuse."""
    snapshot_id = metadata.get("deerflow_tracing_snapshot_id")
    if not isinstance(snapshot_id, str) or metadata.get(TRACING_PINNED_KEY) is True:
        return
    try:
        await await_drained(asyncio.to_thread(release_run_snapshot, snapshot_id, user_id, app_config=app_config))
    except Exception as exc:
        # Failure leaves the pending row protected, without changing admission's result.
        logger.warning("Unused tracing capture remains protected (%s)", type(exc).__name__)
