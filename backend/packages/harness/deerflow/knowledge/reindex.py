"""Re-embed every live chunk in a knowledge base (spec 2026-09-14 §5 / P4).

Switching the embedding provider or dimension invalidates every stored vector, and
``POST /documents/{id}/retry`` cannot repair that: a retry re-runs the *whole* pipeline
including parsing, which is unnecessary (the chunk text is already the source of truth)
and impossible once the original upload is gone. This module is the missing exit — walk
the library's chunks, page them per document, and hand each page to ``index_chunks``, the
part the worker itself uses, so batching, failure marking, and the deterministic point ids
stay identical.

Run shape: a module-level in-flight counter plus a last-run verdict and a progress
snapshot, all per KB, all process-local. Per-document failures are counted and logged,
never fatal: one unreadable document must not strand the rest of the library behind an
old vector space.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from deerflow.knowledge.embed_identity import write_kb_identity
from deerflow.knowledge.embedder import EmbeddingResult
from deerflow.knowledge.indexer import index_chunks
from deerflow.knowledge.store import KnowledgeStore
from deerflow.knowledge.vector_store import KnowledgeVectorStore

logger = logging.getLogger(__name__)

#: Only terminal documents are rebuilt. Anything else is still moving through the worker,
#: whose own legs read the current config anyway — re-embedding underneath it would race.
_TERMINAL_STATUSES = frozenset({"ready", "failed"})

DEFAULT_PAGE_SIZE = 500

_IN_FLIGHT: dict[str, int] = {}
_LAST_RUN: dict[str, str] = {}
_PROGRESS: dict[str, dict[str, int]] = {}


class _Embedder(Protocol):
    """Structural type for the embedder dependency (real or stub).

    ``identity`` is required on purpose (D2): the stamp must name the space this very
    embedder writes into, so a caller that cannot say which space that is must not run
    a rebuild that claims one.
    """

    batch_size: int
    identity: str

    async def embed(self, texts: Sequence[str], *, text_type: str = "document") -> list[EmbeddingResult]: ...


@dataclass(slots=True)
class ReindexReport:
    """Outcome of one library-level rebuild."""

    documents_total: int
    documents_reindexed: int
    documents_skipped: int
    documents_failed: int
    chunks_indexed: int
    #: Whether the walk left nothing behind — the D2 stamp's precondition. A caller
    #: that withholds the stamp (``stamp=False``) still gets the verdict for later.
    complete: bool = False


def reindex_in_progress(kb_id: str) -> bool:
    return _IN_FLIGHT.get(kb_id, 0) > 0


def reindex_last_run_status(kb_id: str) -> str | None:
    """``"succeeded"`` / ``"failed"`` of the last finished run, else ``None``.

    A per-document failure still counts as a succeeded *run*: the library-wide verdict
    answers "is the rebuild still owed?", not "did every document work".
    """
    return _LAST_RUN.get(kb_id)


def reindex_progress(kb_id: str) -> dict[str, int] | None:
    """Live counters while a rebuild runs; ``None`` when idle."""
    snapshot = _PROGRESS.get(kb_id)
    return None if snapshot is None else dict(snapshot)


def _bump(kb_id: str, **deltas: int) -> None:
    snapshot = _PROGRESS.get(kb_id)
    if snapshot is None:
        return
    for key, delta in deltas.items():
        snapshot[key] = snapshot.get(key, 0) + delta


async def reindex_kb(
    store: KnowledgeStore,
    vector_store: KnowledgeVectorStore | None,
    embedder: _Embedder,
    *,
    kb_id: str,
    page_size: int = DEFAULT_PAGE_SIZE,
    include_non_terminal: bool = False,
    stamp: bool = True,
) -> ReindexReport:
    """Re-embed every live chunk of every terminal document in ``kb_id``.

    ``include_non_terminal`` serves the delta passes — the width migration's (spec
    2026-09-26 D5-6) and, since spec 2026-10-05, the same-width rebuild window's.
    Skipping a document that is still moving is right when the library stays where it
    is — its later legs read the current configuration anyway — and wrong during a
    switch, because until the switch "the current configuration" is still the old
    generation, so that document is exactly the one that would be left behind.

    A run that leaves nothing behind stamps the library's embedding identity
    (spec 2026-10-04 D2): a skipped non-terminal document, a failed document or a
    partial batch anywhere means the library is *not* one space, and no claim is made.
    ``stamp=False`` withholds even that claim: the rebuild window's main walk is only
    half of the switch, so the stamp belongs to its delta pass (spec 2026-10-05 D2=乙).
    """
    documents = await store.list_documents(kb_id)
    report = ReindexReport(
        documents_total=len(documents),
        documents_reindexed=0,
        documents_skipped=0,
        documents_failed=0,
        chunks_indexed=0,
    )
    _IN_FLIGHT[kb_id] = _IN_FLIGHT.get(kb_id, 0) + 1
    _PROGRESS[kb_id] = {"documents_total": len(documents), "documents_done": 0, "chunks_indexed": 0}
    complete = True
    try:
        for document in documents:
            doc_id = document["id"]
            try:
                if not include_non_terminal and document["status"] not in _TERMINAL_STATUSES:
                    report.documents_skipped += 1
                    # Left in whatever space it was ingested in ⇒ the library is mixed.
                    complete = False
                else:
                    result = await _reindex_document(store, vector_store, embedder, kb_id=kb_id, doc_id=doc_id, page_size=page_size)
                    if result is None:
                        report.documents_skipped += 1
                    else:
                        indexed, chunks_total = result
                        report.documents_reindexed += 1
                        report.chunks_indexed += indexed
                        _bump(kb_id, chunks_indexed=indexed)
                        if indexed != chunks_total:
                            complete = False
            except Exception:
                logger.exception("reindex failed for document %s (kb %s); continuing with the rest", doc_id, kb_id)
                report.documents_failed += 1
                complete = False
            finally:
                _bump(kb_id, documents_done=1)
        if vector_store is not None and complete and stamp:
            # Every live vector now sits in this embedder's space — record which
            # one (D2). Never a partial claim: nothing to write means nothing written.
            await write_kb_identity(store._sf, kb_id, embedder.identity)
        report.complete = complete
        _LAST_RUN[kb_id] = "succeeded"
    except Exception:
        _LAST_RUN[kb_id] = "failed"
        raise
    finally:
        remaining = _IN_FLIGHT.get(kb_id, 0) - 1
        if remaining > 0:
            _IN_FLIGHT[kb_id] = remaining
        else:
            _IN_FLIGHT.pop(kb_id, None)
            _PROGRESS.pop(kb_id, None)
    return report


async def _reindex_document(
    store: KnowledgeStore,
    vector_store: KnowledgeVectorStore | None,
    embedder: _Embedder,
    *,
    kb_id: str,
    doc_id: str,
    page_size: int,
) -> tuple[int, int] | None:
    """Page one document's chunks through ``index_chunks``.

    Returns ``(indexed, total chunks)``, or ``None`` when the document has no chunks to
    re-embed. ``index_chunks`` reports ``chunk_count`` as *this call's* indexed count, so
    a paged walk writes the document's real total itself once the pages are done.
    """
    total = await store.count_chunks(doc_id)
    if total == 0:
        return None
    indexed = 0
    offset = 0
    while offset < total:
        page = await store.list_chunks(doc_id, offset=offset, limit=page_size)
        if not page:
            break
        stats = await index_chunks(store, vector_store, embedder, kb_id=kb_id, doc_id=doc_id, chunks=page)
        indexed += stats.indexed
        offset += len(page)
    document = await store.get_document(doc_id)
    if document is not None:
        await store.update_document_status(doc_id, document["status"], chunk_count=indexed)
    return indexed, total


def reindex_status(kb_id: str) -> dict[str, Any]:
    """Poll payload for the settings entry."""
    return {"in_progress": reindex_in_progress(kb_id), "last_run": reindex_last_run_status(kb_id), "progress": reindex_progress(kb_id)}
