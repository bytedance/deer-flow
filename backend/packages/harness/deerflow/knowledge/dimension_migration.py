"""Move the vector library to another width (spec 2026-09-26 D1 乙 / D5-2, D5-6).

The width is part of the identity of a vector space, so changing it is a rebuild, not an
edit: every stored vector belongs to the old space. This module runs the *ordered* half of
that rebuild — build the new generation, re-embed every library into it, re-embed whatever
the switch window added, and report. It deliberately stops there: **the switch itself
(writing the new width) and dropping the old generation belong to the caller**, which is
the only layer that knows the configuration file (D5-7).

Three properties are the point, and each is a test:

- **Build before you switch.** The new generation is created empty, the old one keeps
  answering every read until the caller flips, so a failure here leaves the running
  deployment untouched — the failure mode is "nothing happened", not "half a library".
- **A leftover is not resumed, it is dropped.** An interrupted run leaves a half-filled
  new generation; the next run drops it and starts over (D5-2). Resuming would have to
  reason about which points are stale, which is exactly the state nobody can audit.
- **The switch window is covered** (D5-6): anything that arrived or changed during the run
  is re-embedded before the caller flips — measured by the library's own content
  signature, and including documents still moving through the worker, whose writes land
  in the old generation until the flip.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

from deerflow.knowledge.reindex import DEFAULT_PAGE_SIZE, reindex_kb
from deerflow.knowledge.store import KnowledgeStore

logger = logging.getLogger(__name__)


class _Embedder(Protocol):
    """Structural type for the embedder dependency (real or stub).

    ``identity`` mirrors ``reindex._Embedder``: the delta pass stamps the library with
    the space it just rebuilt into (spec 2026-10-04 D2).
    """

    batch_size: int
    identity: str

    async def embed(self, texts, *, text_type: str = "document"): ...


class _GenerationStore(Protocol):
    """The vector store double the migration drives (real one or a recorder)."""

    async def drop_collections(self) -> list[str]: ...

    async def create_collections(self) -> None: ...

    async def delete_by_doc(self, doc_id: str) -> None: ...


@dataclass(slots=True)
class MigrationReport:
    """Outcome of one width migration."""

    kbs_total: int
    kbs_done: int
    documents_reindexed: int
    documents_failed: int
    chunks_indexed: int
    delta_documents: int
    delta_chunks_indexed: int


_IN_FLIGHT = False
_PROGRESS: dict[str, int] | None = None
_LAST_RUN: str | None = None
_DETAIL: str | None = None


def migration_in_progress() -> bool:
    return _IN_FLIGHT


def migration_progress() -> dict[str, int] | None:
    """Live counters while a migration runs; ``None`` when idle."""
    return None if _PROGRESS is None else dict(_PROGRESS)


def migration_last_run() -> tuple[str | None, str | None]:
    """``("succeeded" | "failed" | None, detail)`` of the last finished run.

    The detail carries the exception for a failure: the status endpoint has to say *why*
    the switch did not happen, and the log alone is not where an admin looks.
    """
    return _LAST_RUN, _DETAIL


def _bump(**deltas: int) -> None:
    if _PROGRESS is None:
        return
    for key, delta in deltas.items():
        _PROGRESS[key] = _PROGRESS.get(key, 0) + delta


async def migrate_collections(
    store: KnowledgeStore,
    *,
    vector_store: Any,
    embedder: _Embedder,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> MigrationReport:
    """Rebuild every library into ``vector_store``'s (new) generation.

    ``vector_store`` is built by the caller at the *target* width — this function only
    decides the order and the coverage. Raises whatever the rebuild raises, after
    recording the failure: the caller must not flip the configuration on a raise.
    """
    global _IN_FLIGHT, _LAST_RUN, _DETAIL, _PROGRESS

    report = MigrationReport(
        kbs_total=0,
        kbs_done=0,
        documents_reindexed=0,
        documents_failed=0,
        chunks_indexed=0,
        delta_documents=0,
        delta_chunks_indexed=0,
    )
    _IN_FLIGHT = True
    _DETAIL = None
    try:
        # 1. The new generation, built fresh: a leftover from an interrupted run is dropped
        #    rather than resumed (D5-2).
        dropped = await vector_store.drop_collections()
        if dropped:
            logger.info("dimension migration dropped a leftover generation: %s", ", ".join(dropped))
        await vector_store.create_collections()

        # 2. The switch window's baseline, taken before anything is re-embedded (D5-6).
        kbs = await store.list_all_kbs()
        report.kbs_total = len(kbs)
        baseline = {kb["id"]: await _content_mark(store, kb["id"]) for kb in kbs}
        _PROGRESS = {"kbs_total": len(kbs), "kbs_done": 0, "documents_reindexed": 0, "chunks_indexed": 0}

        for kb in kbs:
            kb_id = kb["id"]
            kb_report = await reindex_kb(store, vector_store, embedder, kb_id=kb_id, page_size=page_size)
            report.documents_reindexed += kb_report.documents_reindexed
            report.documents_failed += kb_report.documents_failed
            report.chunks_indexed += kb_report.chunks_indexed
            report.kbs_done += 1
            _bump(kbs_done=1, documents_reindexed=kb_report.documents_reindexed, chunks_indexed=kb_report.chunks_indexed)

        # 3. Whatever moved during the run, before the caller may switch (D5-6). The
        #    signature is per library, so a library nothing touched costs one aggregate
        #    query and no embedding at all — the common case stays free.
        for kb in kbs:
            kb_id = kb["id"]
            after = await _content_mark(store, kb_id)
            if after == baseline[kb_id]:
                continue
            logger.info("dimension migration re-embedding library %s: it changed during the switch window", kb_id)
            delta = await reindex_kb(store, vector_store, embedder, kb_id=kb_id, page_size=page_size, include_non_terminal=True)
            report.delta_documents += delta.documents_reindexed
            report.delta_chunks_indexed += delta.chunks_indexed
            report.documents_failed += delta.documents_failed
            await _drop_documents_that_left(store, vector_store, kb_id, marked=baseline[kb_id])
        _LAST_RUN = "succeeded"
    except Exception as exc:
        _LAST_RUN = "failed"
        _DETAIL = f"{type(exc).__name__}: {exc}"
        logger.exception("dimension migration failed; the running generation is untouched")
        raise
    finally:
        _IN_FLIGHT = False
        _PROGRESS = None
    return report


async def _content_mark(store: KnowledgeStore, kb_id: str) -> tuple[Any, frozenset[str]]:
    """What "this library changed" means for the switch window (D5-6).

    Two cheap reads: the store's own invalidation signature (counts plus the newest edit
    timestamp per collection — the projection cache's fingerprint, reused rather than
    re-derived) and the document id set. Together they catch an arriving document, an
    edited chunk and a deleted document; a document still in flight shows up as its
    chunks land.
    """
    documents = await store.list_documents(kb_id)
    return await store.get_kb_content_stats(kb_id), frozenset(document["id"] for document in documents)


async def _drop_documents_that_left(store: KnowledgeStore, vector_store: Any, kb_id: str, *, marked: tuple[Any, frozenset[str]]) -> None:
    """Remove the new generation's points for documents that no longer exist.

    The delete path cleaned them out of the generation that was live *then*; without this
    the new generation would serve vectors pointing at chunks that are gone.
    """
    _, before = marked
    after = frozenset(document["id"] for document in await store.list_documents(kb_id))
    for doc_id in before - after:
        await vector_store.delete_by_doc(doc_id)
        logger.info("dimension migration dropped the new generation's points for deleted document %s", doc_id)
