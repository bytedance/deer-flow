"""Bind safe tracing references after authenticating one run admission."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from fastapi import HTTPException

from app.gateway.deps import get_checkpointer
from deerflow.runtime.tracing_snapshot import TRACING_CHECKPOINT_KEYS, TRACING_PINNED_KEY, TRACING_SERVER_OWNED_KEYS, restore_snapshot, stamp_snapshot_references
from deerflow.tracing.profiles import TracingControlError, resolve_run_snapshot


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
            snapshot = await asyncio.to_thread(restore_snapshot, references, user_id=user_id, agent_name=agent_name, **resolver_kwargs)
        else:
            snapshot = await asyncio.to_thread(resolve_run_snapshot, agent_name, user_id, **resolver_kwargs)
    except TracingControlError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)}) from None
    except ValueError:
        raise HTTPException(status_code=409, detail="The run tracing snapshot is unavailable or does not match its Agent") from None
    stamp_snapshot_references(run_metadata, snapshot)
    if snapshot is not None and references is not None:
        run_metadata[TRACING_PINNED_KEY] = True
    stamp_snapshot_references(config.setdefault("metadata", {}), snapshot)
    stamp_snapshot_references(config.setdefault("context", {}), snapshot)
