"""IndexingDispatcher — async background pump for KB index jobs.

The dispatcher decouples the upload request from the indexing pipeline.
Routes ``submit()`` a job and return 202 immediately; a pool of worker
tasks drains the queue and runs ``IndexingService.execute_index_job``
in the same event loop. The full motivation lives in the Sprint B
design — this module is the implementation.

Key invariants
--------------
* ``submit()`` is non-blocking and always sets the document's
  ``index_status="pending"`` + ``index_queued_at=<now>`` in the DB so a
  process crash before worker pickup is recoverable.
* ``recover()`` runs at startup and re-enqueues any document whose
  status is still ``pending`` / ``indexing`` — the previous run died
  mid-flight. ``execute_index_job`` is idempotent (cleans old chunks
  before writing new), so re-running a partially completed job is safe.
* An in-memory ``_inflight`` set keyed by ``(kb_id, doc_id, version)``
  collapses duplicate submits — clicking "Reindex" twice in quick
  succession does not produce two queued jobs.
* ``aclose()`` cancels worker tasks and awaits the inflight queue with
  a bounded timeout so process shutdown can't hang on a stuck embedding
  call. Any job left ``running`` after the timeout is picked up on the
  next start by ``recover()``.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from deerflow.knowledge_base.indexing import IndexingService
from deerflow.persistence.knowledge_base.document_repository import DocumentRepository
from deerflow.persistence.knowledge_base.repository import KnowledgeBaseRepository

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class IndexJobRequest:
    document: dict[str, Any]
    knowledge_base: dict[str, Any]


def _idempotent_key(doc: dict[str, Any]) -> tuple[str, str, int]:
    return (str(doc["knowledge_base_id"]), str(doc["id"]), int(doc.get("version", 1)))


class IndexingDispatcher:
    """Async dispatcher draining ``IndexJobRequest`` items into ``IndexingService``."""

    def __init__(
        self,
        *,
        indexing_service: IndexingService,
        kb_repo: KnowledgeBaseRepository,
        doc_repo: DocumentRepository,
        workers: int = 2,
        queue_max: int = 256,
        shutdown_timeout: float = 30.0,
    ) -> None:
        if workers < 0:
            raise ValueError("workers must be >= 0")
        self._svc = indexing_service
        self._kb_repo = kb_repo
        self._doc_repo = doc_repo
        self._worker_count = workers
        self._shutdown_timeout = shutdown_timeout
        self._queue: asyncio.Queue[IndexJobRequest] = asyncio.Queue(maxsize=queue_max)
        self._workers: list[asyncio.Task[None]] = []
        self._inflight: set[tuple[str, str, int]] = set()
        self._inflight_lock = asyncio.Lock()
        self._closed = False

    @property
    def enabled(self) -> bool:
        return self._worker_count > 0

    async def start(self) -> None:
        """Spin up the worker pool. Idempotent."""
        if self._closed:
            raise RuntimeError("dispatcher is closed; create a new instance")
        if self._workers or self._worker_count == 0:
            return
        for i in range(self._worker_count):
            self._workers.append(asyncio.create_task(self._worker_loop(i), name=f"index-worker-{i}"))
        logger.info("IndexingDispatcher started with %d worker(s)", self._worker_count)

    async def submit(self, request: IndexJobRequest) -> bool:
        """Queue a job for background execution.

        Returns True when the job was queued; False when an identical
        ``(kb_id, doc_id, version)`` is already in flight (caller should
        treat this as success — the existing job will produce the same
        outcome). Raises ``asyncio.QueueFull`` when the back-pressure
        bound is hit, surfacing as a 503 to the API caller.
        """
        if not self.enabled:
            raise RuntimeError("dispatcher disabled (indexing_workers=0); use synchronous fallback")
        if self._closed:
            raise RuntimeError("dispatcher is closed")
        key = _idempotent_key(request.document)
        async with self._inflight_lock:
            if key in self._inflight:
                logger.debug("submit: dedup hit for %s", key)
                return False
            self._inflight.add(key)
        # Mark the document pending *before* the worker picks it up so the
        # API response truthfully shows the new state and recovery can
        # reclaim it after a crash.
        await self._doc_repo.update_index_status(
            request.document["id"],
            index_status="pending",
            index_queued_at=datetime.now(UTC),
        )
        try:
            self._queue.put_nowait(request)
        except asyncio.QueueFull:
            async with self._inflight_lock:
                self._inflight.discard(key)
            raise
        return True

    async def aclose(self) -> None:
        """Cancel workers and drain the inflight queue with a bounded timeout."""
        if self._closed:
            return
        self._closed = True
        for w in self._workers:
            w.cancel()
        if self._workers:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._workers, return_exceptions=True),
                    timeout=self._shutdown_timeout,
                )
            except TimeoutError:
                logger.warning(
                    "IndexingDispatcher shutdown timed out after %.1fs; "
                    "workers will leave running jobs to be recovered on next start",
                    self._shutdown_timeout,
                )
        self._workers.clear()

    async def recover(self) -> int:
        """Re-enqueue any document still in ``pending`` / ``indexing``.

        Returns the number of jobs re-queued. Safe to call multiple times
        — duplicates collapse via the inflight set.
        """
        if not self.enabled:
            return 0
        try:
            docs = await self._doc_repo.list_pending_or_running()
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("recover: failed to list pending docs: %s", exc)
            return 0
        recovered = 0
        for doc in docs:
            kb_id = doc.get("knowledge_base_id")
            if not kb_id:
                continue
            kb = await self._kb_repo.get_by_id_internal(kb_id)
            if kb is None:
                logger.warning("recover: kb %s missing for doc %s, skipping", kb_id, doc["id"])
                continue
            queued = await self.submit(IndexJobRequest(document=doc, knowledge_base=kb))
            if queued:
                recovered += 1
        if recovered:
            logger.info("IndexingDispatcher: recovered %d orphan job(s)", recovered)
        return recovered

    async def _worker_loop(self, worker_id: int) -> None:
        from deerflow.rag.job_context import with_kb_context

        while True:
            try:
                request = await self._queue.get()
            except asyncio.CancelledError:
                return
            key = _idempotent_key(request.document)
            doc = request.document
            # Restore the submitter's tenant + user context. Workers
            # are long-lived asyncio tasks: their copy of the
            # contextvars is whatever was set when start() ran
            # (typically nothing). Without this wrap, every job
            # would resolve tenant_id="default" inside Chroma —
            # mixing tenant data into one collection.
            tenant_id = str(doc.get("tenant_id") or "")
            owner_user_id = str(doc.get("owner_user_id") or "") or None
            try:
                async with with_kb_context(
                    tenant_id=tenant_id, user_id=owner_user_id
                ):
                    await self._svc.execute_index_job(doc, request.knowledge_base)
            except asyncio.CancelledError:
                # Reset doc status so recover() picks it up next start.
                await self._doc_repo.update_index_status(
                    doc["id"],
                    index_status="pending",
                )
                raise
            except Exception as exc:
                logger.exception("index-worker-%d: job %s failed: %s", worker_id, key, exc)
            finally:
                async with self._inflight_lock:
                    self._inflight.discard(key)
                self._queue.task_done()
