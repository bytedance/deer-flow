"""Tests for ``IndexingDispatcher`` (Sprint B.1).

Covers the contract the upload routes rely on:

* ``submit()`` flips the doc to ``pending`` *before* the worker picks
  up — a crash between submit and worker pickup is recoverable.
* The worker calls ``IndexingService.execute_index_job`` with the
  request's document + KB.
* Duplicate ``(kb_id, doc_id, version)`` submits collapse to one job.
* ``recover()`` re-enqueues anything stuck in pending/indexing.
* ``aclose()`` cancels workers and releases inflight slots.
* ``indexing_workers=0`` disables submit entirely so callers fall back
  to inline ``await execute_index_job``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from deerflow.knowledge_base.dispatcher import IndexingDispatcher, IndexJobRequest


def _make_doc(*, doc_id="d1", kb_id="kb1", version=1) -> dict:
    return {
        "id": doc_id,
        "knowledge_base_id": kb_id,
        "tenant_id": "tenant-x",
        "owner_user_id": "user-1",
        "version": version,
        "title": "T",
        "content": "C",
        "chunk_ids": [],
    }


def _make_kb(kb_id="kb1") -> dict:
    return {"id": kb_id, "collection_name": f"col_{kb_id}", "tenant_id": "tenant-x", "name": "K"}


@pytest_asyncio.fixture
async def dispatcher_with_svc():
    svc = MagicMock()
    svc.execute_index_job = AsyncMock(return_value={"status": "completed"})
    kb_repo = MagicMock()
    kb_repo.get_by_id_internal = AsyncMock(return_value=_make_kb())
    doc_repo = MagicMock()
    doc_repo.update_index_status = AsyncMock()
    doc_repo.list_pending_or_running = AsyncMock(return_value=[])
    d = IndexingDispatcher(
        indexing_service=svc,
        kb_repo=kb_repo,
        doc_repo=doc_repo,
        workers=2,
        queue_max=10,
        shutdown_timeout=2.0,
    )
    await d.start()
    try:
        yield d, svc, kb_repo, doc_repo
    finally:
        await d.aclose()


class TestSubmitAndExecute:
    @pytest.mark.asyncio
    async def test_submit_marks_pending_and_runs_job(self, dispatcher_with_svc) -> None:
        d, svc, _, doc_repo = dispatcher_with_svc
        doc = _make_doc()
        ok = await d.submit(IndexJobRequest(document=doc, knowledge_base=_make_kb()))
        assert ok is True
        # Wait for the worker to drain.
        await d._queue.join()
        # Pending was written before worker pickup.
        first_call = doc_repo.update_index_status.call_args_list[0]
        assert first_call.kwargs["index_status"] == "pending"
        assert first_call.kwargs["index_queued_at"] is not None
        # Worker invoked execute_index_job exactly once with our request.
        svc.execute_index_job.assert_awaited_once()
        args = svc.execute_index_job.await_args
        assert args.args[0] is doc

    @pytest.mark.asyncio
    async def test_duplicate_submit_collapses(self, dispatcher_with_svc) -> None:
        d, svc, _, _ = dispatcher_with_svc
        # Block the worker so the second submit hits the inflight set.
        gate = __import__("asyncio").Event()

        async def slow(*_a, **_kw):
            await gate.wait()
            return {"status": "completed"}

        svc.execute_index_job.side_effect = slow

        doc = _make_doc()
        ok1 = await d.submit(IndexJobRequest(document=doc, knowledge_base=_make_kb()))
        ok2 = await d.submit(IndexJobRequest(document=doc, knowledge_base=_make_kb()))
        assert ok1 is True
        assert ok2 is False
        gate.set()
        await d._queue.join()
        assert svc.execute_index_job.await_count == 1


class TestRecover:
    @pytest.mark.asyncio
    async def test_recover_reenqueues_orphans(self) -> None:
        svc = MagicMock()
        svc.execute_index_job = AsyncMock(return_value={"status": "completed"})
        kb_repo = MagicMock()
        kb_repo.get_by_id_internal = AsyncMock(return_value=_make_kb())
        doc_repo = MagicMock()
        doc_repo.update_index_status = AsyncMock()
        doc_repo.list_pending_or_running = AsyncMock(
            return_value=[_make_doc(doc_id="orphan-1"), _make_doc(doc_id="orphan-2")]
        )

        d = IndexingDispatcher(
            indexing_service=svc, kb_repo=kb_repo, doc_repo=doc_repo, workers=2, shutdown_timeout=2.0
        )
        await d.start()
        try:
            recovered = await d.recover()
            assert recovered == 2
            await d._queue.join()
            assert svc.execute_index_job.await_count == 2
        finally:
            await d.aclose()

    @pytest.mark.asyncio
    async def test_recover_skips_kb_missing(self) -> None:
        svc = MagicMock()
        svc.execute_index_job = AsyncMock()
        kb_repo = MagicMock()
        kb_repo.get_by_id_internal = AsyncMock(return_value=None)
        doc_repo = MagicMock()
        doc_repo.update_index_status = AsyncMock()
        doc_repo.list_pending_or_running = AsyncMock(return_value=[_make_doc()])

        d = IndexingDispatcher(
            indexing_service=svc, kb_repo=kb_repo, doc_repo=doc_repo, workers=1, shutdown_timeout=2.0
        )
        await d.start()
        try:
            assert await d.recover() == 0
            svc.execute_index_job.assert_not_awaited()
        finally:
            await d.aclose()


class TestDisabledMode:
    @pytest.mark.asyncio
    async def test_disabled_dispatcher_rejects_submit(self) -> None:
        # workers=0 → caller is expected to fall back to inline indexing.
        d = IndexingDispatcher(
            indexing_service=MagicMock(),
            kb_repo=MagicMock(),
            doc_repo=MagicMock(),
            workers=0,
        )
        await d.start()
        with pytest.raises(RuntimeError, match="disabled"):
            await d.submit(IndexJobRequest(document=_make_doc(), knowledge_base=_make_kb()))
        assert d.enabled is False
        await d.aclose()

    @pytest.mark.asyncio
    async def test_disabled_recover_is_noop(self) -> None:
        d = IndexingDispatcher(
            indexing_service=MagicMock(),
            kb_repo=MagicMock(),
            doc_repo=MagicMock(),
            workers=0,
        )
        await d.start()
        assert await d.recover() == 0
        await d.aclose()


class TestBackpressure:
    @pytest.mark.asyncio
    async def test_queue_full_releases_inflight(self) -> None:
        # Stuck worker + small queue → eventually submit raises QueueFull,
        # and the rejected job's inflight slot is released so a retry would
        # not be blocked by dedup.
        import asyncio as _asyncio

        gate = _asyncio.Event()
        svc = MagicMock()

        async def slow(*_a, **_kw):
            await gate.wait()
            return {"status": "completed"}

        svc.execute_index_job = AsyncMock(side_effect=slow)
        kb_repo = MagicMock()
        kb_repo.get_by_id_internal = AsyncMock(return_value=_make_kb())
        doc_repo = MagicMock()
        doc_repo.update_index_status = AsyncMock()

        d = IndexingDispatcher(
            indexing_service=svc, kb_repo=kb_repo, doc_repo=doc_repo, workers=1, queue_max=2
        )
        await d.start()
        try:
            await d.submit(IndexJobRequest(document=_make_doc(doc_id="a"), knowledge_base=_make_kb()))
            # Yield so the worker has a chance to pull "a" before we fill
            # the queue with the next two jobs.
            await _asyncio.sleep(0.05)
            await d.submit(IndexJobRequest(document=_make_doc(doc_id="b"), knowledge_base=_make_kb()))
            await d.submit(IndexJobRequest(document=_make_doc(doc_id="c"), knowledge_base=_make_kb()))
            with pytest.raises(_asyncio.QueueFull):
                await d.submit(
                    IndexJobRequest(document=_make_doc(doc_id="d"), knowledge_base=_make_kb())
                )
            # Inflight for "d" was released so a retry would succeed.
            assert ("kb1", "d", 1) not in d._inflight
        finally:
            gate.set()
            await d.aclose()
