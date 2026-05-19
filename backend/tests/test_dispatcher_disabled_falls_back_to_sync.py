"""Tests for the dispatcher-disabled fallback (Sprint B.5.1, design §9.2).

When ``rag.indexing_workers == 0`` the dispatcher is constructed but
disabled (``IndexingDispatcher.enabled == False``). In that mode every
write path on ``KnowledgeBaseService`` must fall back to running
``IndexingService.execute_index_job`` inline so tests / bare-bones dev
setups don't silently leave docs ``pending`` forever.

This test covers:
- The service still routes through ``_run_index_job`` (no scattered
  ``if dispatcher`` checks).
- When the dispatcher is missing or ``enabled == False``, the inline
  branch is taken.
- When the dispatcher *is* enabled, ``submit`` is called and inline
  is not.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from deerflow.knowledge_base.service import KnowledgeBaseService


def _build_service(*, dispatcher=None) -> KnowledgeBaseService:
    return KnowledgeBaseService(
        kb_repo=MagicMock(),
        doc_repo=MagicMock(),
        job_repo=MagicMock(),
        permission_repo=MagicMock(),
        dispatcher=dispatcher,
    )


class TestDispatcherDisabledFallsBackToSync:
    @pytest.mark.asyncio
    async def test_no_dispatcher_falls_back_to_inline(self):
        svc = _build_service(dispatcher=None)
        svc._indexing.execute_index_job = AsyncMock(return_value={"status": "ok"})

        await svc._run_index_job({"id": "d1"}, {"id": "kb-1"})
        svc._indexing.execute_index_job.assert_awaited_once_with(
            {"id": "d1"}, {"id": "kb-1"}
        )

    @pytest.mark.asyncio
    async def test_disabled_dispatcher_falls_back_to_inline(self):
        disabled = MagicMock()
        disabled.enabled = False
        disabled.submit = AsyncMock()

        svc = _build_service(dispatcher=disabled)
        svc._indexing.execute_index_job = AsyncMock(return_value={"status": "ok"})

        await svc._run_index_job({"id": "d2"}, {"id": "kb-1"})

        disabled.submit.assert_not_awaited()
        svc._indexing.execute_index_job.assert_awaited_once_with(
            {"id": "d2"}, {"id": "kb-1"}
        )

    @pytest.mark.asyncio
    async def test_enabled_dispatcher_submits_and_skips_inline(self):
        enabled = MagicMock()
        enabled.enabled = True
        enabled.submit = AsyncMock(return_value=True)

        svc = _build_service(dispatcher=enabled)
        svc._indexing.execute_index_job = AsyncMock()

        await svc._run_index_job(
            {"id": "d3", "knowledge_base_id": "kb-1", "version": 1},
            {"id": "kb-1"},
        )

        enabled.submit.assert_awaited_once()
        svc._indexing.execute_index_job.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_attach_dispatcher_swaps_routing_decision(self):
        # Constructed with no dispatcher; later attached.
        svc = _build_service(dispatcher=None)
        svc._indexing.execute_index_job = AsyncMock()

        await svc._run_index_job({"id": "early"}, {"id": "kb-1"})
        assert svc._indexing.execute_index_job.await_count == 1

        enabled = MagicMock()
        enabled.enabled = True
        enabled.submit = AsyncMock(return_value=True)
        svc.attach_dispatcher(enabled)

        await svc._run_index_job(
            {"id": "late", "knowledge_base_id": "kb-1", "version": 1},
            {"id": "kb-1"},
        )
        # Inline call count unchanged after attach.
        assert svc._indexing.execute_index_job.await_count == 1
        enabled.submit.assert_awaited_once()
