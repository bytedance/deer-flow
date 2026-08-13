"""Standalone LangGraph Server lifecycle integration.

The embedded Gateway does not load this module. ``langgraph.json`` attaches its
empty FastAPI application to the standalone server so the lifespan can repair
assistant provenance before the server accepts Studio requests.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Collection
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

logger = logging.getLogger(__name__)


async def reconcile_assistant_provenance(
    *,
    connect: Callable[..., Any] | None = None,
    assistants_ops: Any = None,
    system_assistant_ids: Collection[str] | None = None,
    page_size: int = 100,
) -> int:
    """Demote persisted client-forged system assistant markers.

    LangGraph registers graph definitions before running this custom lifespan
    and records their deterministic IDs in ``SYSTEM_ASSISTANT_IDS``. That
    registry, rather than mutable assistant metadata, is the authority used to
    distinguish genuine server assistants from rows created by older versions
    that accepted a caller-supplied ``created_by=system`` marker.

    Returns the number of repaired rows.
    """
    if page_size < 1:
        raise ValueError("page_size must be positive")

    if connect is None:
        from langgraph_runtime.database import connect as runtime_connect

        connect = runtime_connect
    if assistants_ops is None:
        from langgraph_runtime.ops import Assistants

        assistants_ops = Assistants
    if system_assistant_ids is None:
        from langgraph_api.graph import SYSTEM_ASSISTANT_IDS

        system_assistant_ids = SYSTEM_ASSISTANT_IDS

    registered_ids = {str(assistant_id) for assistant_id in system_assistant_ids}
    if not registered_ids:
        logger.warning("Skipping assistant provenance reconciliation because no registered system assistants are available")
        return 0

    marked_ids: list[str] = []

    async with connect() as conn:
        offset = 0
        while True:
            rows, next_offset = await assistants_ops.search(
                conn,
                graph_id=None,
                name=None,
                metadata={"created_by": "system"},
                limit=page_size,
                offset=offset,
                sort_by="assistant_id",
                sort_order="ASC",
                select=None,
                ctx=None,
            )
            async for assistant in rows:
                marked_ids.append(str(assistant["assistant_id"]))

            if next_offset is None:
                break
            if next_offset <= offset:
                raise RuntimeError("assistant search returned a non-advancing cursor")
            offset = next_offset

        forged_ids = [assistant_id for assistant_id in marked_ids if assistant_id not in registered_ids]
        repaired = 0
        failures: list[tuple[str, Exception]] = []
        for assistant_id in forged_ids:
            try:
                updated = await assistants_ops.patch(
                    conn,
                    assistant_id,
                    metadata={"created_by": "user"},
                    ctx=None,
                )
                async for _ in updated:
                    pass
            except Exception as exc:
                failures.append((assistant_id, exc))
                logger.exception(
                    "Failed to reconcile assistant provenance for %s",
                    assistant_id,
                )
                continue
            repaired += 1

    if failures:
        failed_ids = ", ".join(assistant_id for assistant_id, _ in failures)
        raise RuntimeError(f"Failed to reconcile {len(failures)} assistant provenance row(s): {failed_ids}") from failures[0][1]

    return repaired


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    repaired = await reconcile_assistant_provenance()
    if repaired:
        logger.warning(
            "Demoted %d persisted assistant system marker(s) that were not registered by this server",
            repaired,
        )
    yield


langgraph_app = FastAPI(
    lifespan=_lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
