"""Tests for KB indexing queue mode (multi-worker dispatcher)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deerflow.knowledge_base.dispatcher import IndexingDispatcher


def _make_job(
    job_id: str = "job1",
    doc_id: str = "doc1",
    kb_id: str = "kb1",
    status: str = "pending",
    retry_count: int = 0,
    worker_id: str | None = None,
    version: int = 1,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "id": job_id,
        "document_id": doc_id,
        "knowledge_base_id": kb_id,
        "tenant_id": "default",
        "owner_user_id": "user1",
        "version": version,
        "status": status,
        "worker_id": worker_id,
        "retry_count": retry_count,
        "started_at": now.isoformat() if status == "running" else None,
        "finished_at": None,
        "error": None,
        "old_chunk_ids": [],
        "new_chunk_ids": [],
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }


def _make_doc(doc_id: str = "doc1", kb_id: str = "kb1") -> dict[str, Any]:
    return {
        "id": doc_id,
        "knowledge_base_id": kb_id,
        "tenant_id": "default",
        "owner_user_id": "user1",
        "title": "Test Doc",
        "content": "test content",
        "version": 1,
    }


def _make_kb(kb_id: str = "kb1") -> dict[str, Any]:
    return {
        "id": kb_id,
        "tenant_id": "default",
        "name": "Test KB",
        "collection_name": "test_kb",
    }


class TestQueueModeInit:
    def test_queue_mode_requires_job_repo(self) -> None:
        svc = MagicMock()
        kb_repo = MagicMock()
        doc_repo = MagicMock()
        with pytest.raises(ValueError, match="queue mode requires"):
            IndexingDispatcher(
                indexing_service=svc,
                kb_repo=kb_repo,
                doc_repo=doc_repo,
                job_repo=None,
                workers=1,
                mode="queue",
            )

    def test_local_mode_no_job_repo_ok(self) -> None:
        svc = MagicMock()
        kb_repo = MagicMock()
        doc_repo = MagicMock()
        d = IndexingDispatcher(
            indexing_service=svc,
            kb_repo=kb_repo,
            doc_repo=doc_repo,
            workers=1,
            mode="local",
        )
        assert d._mode == "local"

    def test_worker_id_generated(self) -> None:
        svc = MagicMock()
        kb_repo = MagicMock()
        doc_repo = MagicMock()
        d = IndexingDispatcher(
            indexing_service=svc,
            kb_repo=kb_repo,
            doc_repo=doc_repo,
            workers=1,
            mode="local",
        )
        assert len(d._worker_id) == 12
        assert d._worker_id.isalnum()


class TestClaimJob:
    @pytest.mark.asyncio
    async def test_claim_and_execute(self) -> None:
        job_repo = AsyncMock()
        job_repo.claim_job.side_effect = [
            _make_job(job_id="j1", status="running", worker_id="w1"),
            asyncio.CancelledError(),
        ]
        job_repo.update_status = AsyncMock()

        doc_repo = AsyncMock()
        doc_repo.get_by_id_internal.return_value = _make_doc()

        kb_repo = AsyncMock()
        kb_repo.get_by_id_internal.return_value = _make_kb()

        svc = AsyncMock()

        d = IndexingDispatcher(
            indexing_service=svc,
            kb_repo=kb_repo,
            doc_repo=doc_repo,
            job_repo=job_repo,
            workers=1,
            mode="queue",
        )
        d._worker_id = "w1"

        await d.start()
        try:
            await asyncio.sleep(0.2)
        finally:
            await d.aclose()

        svc.execute_index_job.assert_called_once()
        job_repo.update_status.assert_called()

    @pytest.mark.asyncio
    async def test_no_pending_job_polls_again(self) -> None:
        job_repo = AsyncMock()
        job_repo.claim_job.side_effect = [None, asyncio.CancelledError()]

        svc = AsyncMock()
        d = IndexingDispatcher(
            indexing_service=svc,
            kb_repo=MagicMock(),
            doc_repo=MagicMock(),
            job_repo=job_repo,
            workers=1,
            mode="queue",
        )

        await d.start()
        try:
            await asyncio.sleep(1.5)
        finally:
            await d.aclose()

        assert job_repo.claim_job.call_count >= 2
        svc.execute_index_job.assert_not_called()


class TestReclaimStaleJobs:
    @pytest.mark.asyncio
    async def test_reclaim_marks_failed_after_max_retries(self) -> None:
        job_repo = AsyncMock()
        job_repo.reclaim_stale_jobs.return_value = 2

        svc = AsyncMock()
        d = IndexingDispatcher(
            indexing_service=svc,
            kb_repo=MagicMock(),
            doc_repo=MagicMock(),
            job_repo=job_repo,
            workers=0,
            mode="queue",
        )
        d._job_timeout = 30
        d._max_retries = 3

        task = asyncio.create_task(d._reclaim_stale_loop())
        await asyncio.sleep(11)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        job_repo.reclaim_stale_jobs.assert_called()


class TestMaxRetries:
    @pytest.mark.asyncio
    async def test_failed_job_retries_then_fails(self) -> None:
        job_repo = AsyncMock()
        job_repo.claim_job.side_effect = [
            _make_job(job_id="j1", status="running", worker_id="w1", retry_count=2),
            asyncio.CancelledError(),
        ]
        job_repo.update_status = AsyncMock()

        doc_repo = AsyncMock()
        doc_repo.get_by_id_internal.return_value = _make_doc()
        doc_repo.update_index_status = AsyncMock()

        kb_repo = AsyncMock()
        kb_repo.get_by_id_internal.return_value = _make_kb()

        async def _fail(*a, **kw):
            raise RuntimeError("embedding failed")

        svc = MagicMock()
        svc.execute_index_job = AsyncMock(side_effect=_fail)

        d = IndexingDispatcher(
            indexing_service=svc,
            kb_repo=kb_repo,
            doc_repo=doc_repo,
            job_repo=job_repo,
            workers=1,
            mode="queue",
        )
        d._worker_id = "w1"
        d._max_retries = 3

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _noop_ctx(**kw):
            yield

        with patch("deerflow.rag.job_context.with_kb_context", _noop_ctx):
            await d.start()
            try:
                await asyncio.sleep(0.5)
            finally:
                await d.aclose()

        call_args = job_repo.update_status.call_args_list
        last_call = call_args[-1]
        assert last_call.kwargs.get("status") == "failed"
