"""The app half of the width migration: start it, switch when it is done, say how it went.

``deerflow.knowledge.dimension_migration`` rebuilds the library into the new generation and
stops there; this module owns the three moves that need the *application*: scheduling the
run off the request (spec 2026-09-26 D5-7), flipping ``rag_config.json`` once the rebuild
reports success, and dropping the old generation afterwards (best-effort).

The order is the whole point of the feature. Until the flip, ``rag_config.json`` still says
the old width, so the running deployment keeps reading and writing the old generation —
which is why a failure here is "nothing happened" rather than "half a library": the file is
only ever replaced after a complete rebuild, and the old collections stay until then.

The verdict is process-local state, like the reindex entries it is modelled on: it answers
"what happened to the migration I started", not "what is in the database".
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from deerflow.config.rag_config_file import write_rag_config
from deerflow.knowledge import dimension_migration
from deerflow.knowledge.vector_store import KnowledgeVectorStore

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _Run:
    """One migration's live verdict: what it targets, where it is, how it ended."""

    target_dimension: int
    state: str = "running"
    detail: str | None = None


_STATE: _Run | None = None
_TASKS: set[asyncio.Task[None]] = set()


def migration_running() -> bool:
    return _STATE is not None and _STATE.state == "running"


def migration_status() -> dict[str, Any] | None:
    """The status payload the settings page polls; ``None`` when nothing ever ran."""
    if _STATE is None:
        return None
    return {
        "state": _STATE.state,
        "target_dimension": _STATE.target_dimension,
        "detail": _STATE.detail,
        "progress": dimension_migration.migration_progress() if _STATE.state == "running" else None,
    }


def start_migration(
    *,
    store: Any,
    graph_store: Any,
    wiki_store: Any,
    url: str,
    old_width: int,
    target_width: int,
    target_payload: dict[str, Any],
    embedder: Any,
) -> None:
    """Kick the rebuild off the request path; the switch happens inside the task.

    ``target_payload`` is the configuration this save will have put in force once the
    rebuild is complete: the caller already wrote everything *but* the width, so this is
    the whole object, not a patch.
    """
    global _STATE
    if migration_running():
        raise RuntimeError("a dimension migration is already running")
    _STATE = _Run(target_dimension=target_width)
    spec = (store, graph_store, wiki_store, url, old_width, target_width, target_payload, embedder)
    task = asyncio.create_task(_run(*spec), name=f"dimension-migration-{target_width}")
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)


def reset_state() -> None:
    """Forget the last verdict (deployments and tests both need a clean slate)."""
    global _STATE
    _STATE = None


async def _run(
    store: Any,
    graph_store: Any,
    wiki_store: Any,
    url: str,
    old_width: int,
    target_width: int,
    target_payload: dict[str, Any],
    embedder: Any,
) -> None:
    assert _STATE is not None  # set by start_migration before the task was scheduled
    state = _STATE
    vector_store = KnowledgeVectorStore(url, dense_size=target_width)
    try:
        await dimension_migration.migrate_collections(store, vector_store=vector_store, embedder=embedder, graph_store=graph_store, wiki_store=wiki_store)
    except Exception as exc:
        state.state = "failed"
        state.detail = f"{type(exc).__name__}: {exc}"
        logger.exception("dimension migration to %d failed; the running generation and the recorded width are untouched", target_width)
        return

    # The switch: one atomic replace, and it happens only here — after a complete rebuild.
    await asyncio.to_thread(write_rag_config, dict(target_payload))
    state.state = "succeeded"
    logger.info("dimension migration to %d complete; rag_config.json now declares it", target_width)

    try:
        dropped = await KnowledgeVectorStore(url, dense_size=old_width).drop_collections()
        logger.info("dimension migration dropped the previous generation: %s", ", ".join(dropped) or "nothing to drop")
    except Exception:
        # Best-effort (D5-2): the old vectors are no longer served, and a leftover collection
        # is a cleanup chore, not a reason to call a finished migration failed.
        logger.warning("dimension migration could not drop the previous generation (width %d)", old_width, exc_info=True)
