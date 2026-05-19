"""Tests for ``KnowledgeBaseService.reindex_all_for_kb`` (Sprint B.3.5).

Covers:
- Admin-only gate (superadmin / tenant_admin); other roles raise PermissionError.
- KB stale flag is set up-front (before delete_collection) so retrieval
  can't briefly serve from an empty collection mid-reindex.
- ``delete_collection`` is called with the KB's ``collection_name``;
  failure is logged but doesn't abort the reindex.
- Each non-deleted doc gets its version bumped and is dispatched
  through the same ``_run_index_job`` path as new uploads.
- Cross-tenant attempt by tenant_admin is rejected.
- The returned report carries kb_id, collection_name, doc_total,
  doc_queued, doc_failed.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deerflow.knowledge_base.service import KnowledgeBaseService


def _build_service(
    *,
    docs: list[dict[str, Any]] | None = None,
    kb: dict[str, Any] | None = None,
) -> tuple[KnowledgeBaseService, dict[str, MagicMock]]:
    kb_repo = MagicMock()
    kb_repo.get_by_id_internal = AsyncMock(
        return_value=kb
        or {
            "id": "kb-1",
            "tenant_id": "tenant-a",
            "collection_name": "kb_xyz",
            "embedding_model": "openai:text-embedding-3-small",
            "embedding_dim": 1536,
            "vector_metric_stale": True,
        }
    )
    kb_repo.set_vector_metric_stale = AsyncMock(return_value=True)
    kb_repo.update_embedding_binding = AsyncMock(return_value=True)

    doc_repo = MagicMock()
    doc_repo.list_by_kb_accessible = AsyncMock(
        return_value=docs
        if docs is not None
        else [
            {
                "id": "d1",
                "tenant_id": "tenant-a",
                "owner_user_id": "u1",
                "version": 1,
                "chunk_ids": ["c-old-1"],
            },
            {
                "id": "d2",
                "tenant_id": "tenant-a",
                "owner_user_id": "u1",
                "version": 3,
                "chunk_ids": ["c-old-2"],
            },
        ]
    )
    doc_repo.update = AsyncMock(side_effect=lambda doc_id, **kw: {"id": doc_id, **kw})

    job_repo = MagicMock()
    perm_repo = MagicMock()

    svc = KnowledgeBaseService(
        kb_repo=kb_repo,
        doc_repo=doc_repo,
        job_repo=job_repo,
        permission_repo=perm_repo,
    )

    return svc, {
        "kb_repo": kb_repo,
        "doc_repo": doc_repo,
        "perm_repo": perm_repo,
    }


class TestReindexAllAdminGate:
    @pytest.mark.asyncio
    async def test_non_admin_role_is_rejected(self):
        svc, _ = _build_service()
        with pytest.raises(PermissionError):
            await svc.reindex_all_for_kb("kb-1", tenant_id="tenant-a", role="user")

    @pytest.mark.asyncio
    async def test_unknown_kb_raises_value_error(self):
        svc, mocks = _build_service()
        mocks["kb_repo"].get_by_id_internal = AsyncMock(return_value=None)
        with pytest.raises(ValueError):
            await svc.reindex_all_for_kb(
                "missing", tenant_id="tenant-a", role="superadmin"
            )

    @pytest.mark.asyncio
    async def test_tenant_admin_cross_tenant_blocked(self):
        svc, mocks = _build_service(
            kb={
                "id": "kb-1",
                "tenant_id": "tenant-OTHER",
                "collection_name": "kb_xyz",
            }
        )
        with pytest.raises(PermissionError):
            await svc.reindex_all_for_kb(
                "kb-1", tenant_id="tenant-a", role="tenant_admin"
            )


class TestReindexAllExecution:
    @pytest.mark.asyncio
    async def test_marks_stale_then_drops_collection_then_dispatches(self):
        svc, mocks = _build_service()
        kb_repo = mocks["kb_repo"]

        run_calls: list[tuple[str, int]] = []

        async def fake_run_job(doc, kb):
            run_calls.append((doc["id"], doc["version"]))

        with patch(
            "deerflow.rag.vector_store.get_vector_store"
        ) as mock_store_factory, patch.object(
            svc, "_run_index_job", side_effect=fake_run_job
        ):
            mock_store = MagicMock()
            mock_store_factory.return_value = mock_store

            report = await svc.reindex_all_for_kb(
                "kb-1", tenant_id="tenant-a", role="superadmin"
            )

        # Stale-flag gate runs *before* delete so retrieval skips
        # this KB the moment we begin tearing it down.
        kb_repo.set_vector_metric_stale.assert_awaited_once_with(
            "kb-1", stale=True
        )
        # Collection torn down with the right name.
        mock_store.delete_collection.assert_called_once_with("kb_xyz")
        # Dim binding cleared so the lazy backfill can re-bind on
        # first successful job (operator may be migrating models).
        kb_repo.update_embedding_binding.assert_awaited_once_with(
            "kb-1", embedding_dim=0
        )

        # Each non-deleted doc was dispatched with a bumped version.
        assert run_calls == [("d1", 2), ("d2", 4)]
        # Doc rows updated with new versions.
        assert mocks["doc_repo"].update.await_count == 2

        assert report["kb_id"] == "kb-1"
        assert report["collection_name"] == "kb_xyz"
        assert report["doc_total"] == 2
        assert report["doc_queued"] == 2
        assert report["doc_failed"] == []

    @pytest.mark.asyncio
    async def test_delete_collection_failure_does_not_abort_reindex(self):
        svc, _ = _build_service()

        async def fake_run_job(doc, kb):
            return None

        with patch(
            "deerflow.rag.vector_store.get_vector_store"
        ) as mock_store_factory, patch.object(
            svc, "_run_index_job", side_effect=fake_run_job
        ):
            mock_store = MagicMock()
            mock_store.delete_collection.side_effect = RuntimeError(
                "collection missing"
            )
            mock_store_factory.return_value = mock_store

            report = await svc.reindex_all_for_kb(
                "kb-1", tenant_id="tenant-a", role="superadmin"
            )

        # Reindex still queues both docs even when delete failed.
        assert report["doc_queued"] == 2

    @pytest.mark.asyncio
    async def test_per_doc_failure_recorded_but_others_continue(self):
        svc, _ = _build_service()

        async def fake_run_job(doc, kb):
            if doc["id"] == "d1":
                raise RuntimeError("one bad doc")

        with patch(
            "deerflow.rag.vector_store.get_vector_store"
        ) as mock_store_factory, patch.object(
            svc, "_run_index_job", side_effect=fake_run_job
        ):
            mock_store_factory.return_value = MagicMock()
            report = await svc.reindex_all_for_kb(
                "kb-1", tenant_id="tenant-a", role="superadmin"
            )

        assert report["doc_total"] == 2
        assert report["doc_queued"] == 1
        assert report["doc_failed"] == ["d1"]
