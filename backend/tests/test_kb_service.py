"""Tests for KnowledgeBaseService core operations.

Covers: constructor validation, KB CRUD delegation, document creation triggers
indexing, delete cascades to vector store, dispatcher fallback, and permission checks.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deerflow.knowledge_base.service import KnowledgeBaseService


def _mock_repos():
    kb_repo = AsyncMock()
    doc_repo = AsyncMock()
    job_repo = AsyncMock()
    perm_repo = AsyncMock()
    return kb_repo, doc_repo, job_repo, perm_repo


def _make_service(kb_repo=None, doc_repo=None, job_repo=None, perm_repo=None, dispatcher=None):
    kb, doc, job, perm = _mock_repos()
    return KnowledgeBaseService(
        kb_repo=kb_repo or kb,
        doc_repo=doc_repo or doc,
        job_repo=job_repo or job,
        permission_repo=perm_repo or perm,
        dispatcher=dispatcher,
    ), (kb_repo or kb, doc_repo or doc, job_repo or job, perm_repo or perm)


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


class TestConstructor:
    def test_requires_permission_repo(self):
        kb_repo, doc_repo, job_repo, _ = _mock_repos()
        with pytest.raises(ValueError, match="requires a KbPermissionRepository"):
            KnowledgeBaseService(
                kb_repo=kb_repo,
                doc_repo=doc_repo,
                job_repo=job_repo,
                permission_repo=None,
            )

    def test_constructs_with_all_repos(self):
        kb_repo, doc_repo, job_repo, perm_repo = _mock_repos()
        svc = KnowledgeBaseService(
            kb_repo=kb_repo,
            doc_repo=doc_repo,
            job_repo=job_repo,
            permission_repo=perm_repo,
        )
        assert svc.access_control is not None
        assert svc.permission_repo is perm_repo


# ---------------------------------------------------------------------------
# KB CRUD
# ---------------------------------------------------------------------------


class TestKnowledgeBaseCRUD:
    @pytest.mark.asyncio
    async def test_create_delegates_to_repo(self):
        svc, (kb_repo, *_rest) = _make_service()
        kb_repo.create = AsyncMock(return_value={"id": "kb-1", "name": "Test"})

        result = await svc.create_knowledge_base(
            tenant_id="t1",
            owner_user_id="u1",
            name="Test",
            description="A test KB",
            visibility="private",
        )

        kb_repo.create.assert_called_once_with(
            tenant_id="t1",
            owner_user_id="u1",
            name="Test",
            description="A test KB",
            visibility="private",
        )
        assert result["id"] == "kb-1"

    @pytest.mark.asyncio
    async def test_get_returns_none_for_missing(self):
        svc, (kb_repo, *_rest) = _make_service()
        kb_repo.get_accessible = AsyncMock(return_value=None)

        result = await svc.get_knowledge_base("kb-999", tenant_id="t1", user_id="u1")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_returns_kb_when_accessible(self):
        svc, (kb_repo, *_rest) = _make_service()
        kb_repo.get_accessible = AsyncMock(return_value={"id": "kb-1", "name": "My KB"})

        result = await svc.get_knowledge_base("kb-1", tenant_id="t1", user_id="u1")
        assert result is not None
        assert result["name"] == "My KB"

    @pytest.mark.asyncio
    async def test_list_filters_by_tenant(self):
        svc, (kb_repo, *_rest) = _make_service()
        kb_repo.list_accessible = AsyncMock(return_value=[
            {"id": "kb-1"},
            {"id": "kb-2"},
        ])

        result = await svc.list_knowledge_bases(tenant_id="t1", user_id="u1")
        assert len(result) == 2
        kb_repo.list_accessible.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_no_fields_returns_existing(self):
        svc, (kb_repo, *_rest) = _make_service()
        kb_repo.get = AsyncMock(return_value={"id": "kb-1", "name": "Original"})

        result = await svc.update_knowledge_base(
            "kb-1", tenant_id="t1", owner_user_id="u1"
        )

        kb_repo.get.assert_called_once()
        kb_repo.update.assert_not_called()
        assert result["name"] == "Original"

    @pytest.mark.asyncio
    async def test_update_with_name_delegates(self):
        svc, (kb_repo, *_rest) = _make_service()
        kb_repo.update = AsyncMock(return_value={"id": "kb-1", "name": "Renamed"})

        result = await svc.update_knowledge_base(
            "kb-1", tenant_id="t1", owner_user_id="u1", name="Renamed"
        )

        kb_repo.update.assert_called_once()
        assert result["name"] == "Renamed"

    @pytest.mark.asyncio
    async def test_delete_returns_false_when_not_found(self):
        svc, (kb_repo, *_rest) = _make_service()
        kb_repo.get_by_id_internal = AsyncMock(return_value=None)

        result = await svc.delete_knowledge_base("kb-999", tenant_id="t1", owner_user_id="u1")
        assert result is False

    @patch("deerflow.rag.vector_store.get_vector_store")
    @pytest.mark.asyncio
    async def test_delete_permanently_cleans_kb_resources(self, mock_vs_fn):
        svc, (kb_repo, doc_repo, job_repo, perm_repo) = _make_service()
        kb_data = {
            "id": "kb-1",
            "collection_name": "t1_kb1",
            "tenant_id": "t1",
            "owner_user_id": "owner-1",
            "visibility": "tenant",
        }
        kb_repo.get_by_id_internal = AsyncMock(return_value=kb_data)
        kb_repo.hard_delete = AsyncMock(return_value=True)
        doc_repo.hard_delete_by_kb = AsyncMock(return_value=2)
        job_repo.delete_by_kb = AsyncMock(return_value=3)
        perm_repo.delete_by_kb = AsyncMock(return_value=1)

        store = MagicMock()
        mock_vs_fn.return_value = store

        result = await svc.delete_knowledge_base("kb-1", tenant_id="t1", owner_user_id="admin-1")

        assert result is True
        doc_repo.hard_delete_by_kb.assert_called_once_with("kb-1")
        job_repo.delete_by_kb.assert_called_once_with("kb-1")
        perm_repo.delete_by_kb.assert_called_once_with("kb-1")
        kb_repo.hard_delete.assert_called_once_with("kb-1", tenant_id="t1")
        store.delete_collection.assert_called_once_with("t1_kb1")

    @pytest.mark.asyncio
    async def test_delete_private_kb_rejects_non_owner(self):
        svc, (kb_repo, doc_repo, job_repo, perm_repo) = _make_service()
        kb_repo.get_by_id_internal = AsyncMock(return_value={
            "id": "kb-1",
            "collection_name": "t1_kb1",
            "tenant_id": "t1",
            "owner_user_id": "owner-1",
            "visibility": "private",
        })

        result = await svc.delete_knowledge_base("kb-1", tenant_id="t1", owner_user_id="other-user")

        assert result is False
        doc_repo.hard_delete_by_kb.assert_not_called()
        job_repo.delete_by_kb.assert_not_called()
        perm_repo.delete_by_kb.assert_not_called()
        kb_repo.hard_delete.assert_not_called()

    @patch("deerflow.rag.vector_store.get_vector_store")
    @pytest.mark.asyncio
    async def test_delete_public_kb_uses_kb_tenant(self, mock_vs_fn):
        svc, (kb_repo, doc_repo, job_repo, perm_repo) = _make_service()
        kb_repo.get_by_id_internal = AsyncMock(return_value={
            "id": "kb-public",
            "collection_name": "public_col",
            "tenant_id": "tenant-owner",
            "owner_user_id": "owner-1",
            "visibility": "public",
        })
        kb_repo.hard_delete = AsyncMock(return_value=True)
        doc_repo.hard_delete_by_kb = AsyncMock(return_value=1)
        job_repo.delete_by_kb = AsyncMock(return_value=1)
        perm_repo.delete_by_kb = AsyncMock(return_value=0)
        store = MagicMock()
        mock_vs_fn.return_value = store

        result = await svc.delete_knowledge_base(
            "kb-public",
            tenant_id="superadmin-tenant",
            owner_user_id="superadmin-user",
        )

        assert result is True
        kb_repo.hard_delete.assert_called_once_with("kb-public", tenant_id="tenant-owner")
        store.delete_collection.assert_called_once_with("public_col")


# ---------------------------------------------------------------------------
# Document operations
# ---------------------------------------------------------------------------


class TestDocumentOperations:
    @pytest.mark.asyncio
    async def test_create_document_triggers_indexing(self):
        svc, (kb_repo, doc_repo, _job, _perm) = _make_service()
        kb_repo.get = AsyncMock(return_value={"id": "kb-1", "collection_name": "col"})
        doc = {"id": "doc-1", "content": "hello", "knowledge_base_id": "kb-1"}
        doc_repo.create = AsyncMock(return_value=doc)
        doc_repo.get = AsyncMock(return_value={**doc, "index_status": "indexed"})

        with patch.object(svc, "_run_index_job", new_callable=AsyncMock) as mock_index:
            result = await svc.create_document(
                "kb-1",
                tenant_id="t1",
                owner_user_id="u1",
                title="Test",
                content="hello",
            )

        mock_index.assert_called_once_with(doc, {"id": "kb-1", "collection_name": "col"})

    @pytest.mark.asyncio
    async def test_create_document_raises_when_kb_missing(self):
        svc, (kb_repo, *_rest) = _make_service()
        kb_repo.get = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match="not found"):
            await svc.create_document(
                "kb-999",
                tenant_id="t1",
                owner_user_id="u1",
                title="T",
                content="c",
            )

    @pytest.mark.asyncio
    async def test_get_document_returns_none_when_missing(self):
        svc, (_kb, doc_repo, *_rest) = _make_service()
        doc_repo.get = AsyncMock(return_value=None)

        result = await svc.get_document("doc-999", tenant_id="t1", owner_user_id="u1")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_document_returns_false_when_missing(self):
        svc, (_kb, doc_repo, *_rest) = _make_service()
        doc_repo.get = AsyncMock(return_value=None)

        result = await svc.delete_document("doc-999", tenant_id="t1", owner_user_id="u1")
        assert result is False


# ---------------------------------------------------------------------------
# Dispatcher routing
# ---------------------------------------------------------------------------


class TestDispatcherRouting:
    @pytest.mark.asyncio
    async def test_dispatcher_enabled_submits_request(self):
        dispatcher = AsyncMock()
        dispatcher.enabled = True
        dispatcher.submit = AsyncMock()

        svc, (_kb, _doc, _job, _perm) = _make_service(dispatcher=dispatcher)

        doc = {"id": "doc-1", "content": "hello"}
        kb = {"id": "kb-1"}
        await svc._run_index_job(doc, kb)

        dispatcher.submit.assert_called_once()

    @pytest.mark.asyncio
    async def test_dispatcher_disabled_runs_inline(self):
        dispatcher = MagicMock()
        dispatcher.enabled = False

        svc, (_kb, _doc, _job, _perm) = _make_service(dispatcher=dispatcher)

        doc = {"id": "doc-1", "content": "hello"}
        kb = {"id": "kb-1"}

        with patch.object(svc._indexing, "execute_index_job", new_callable=AsyncMock) as mock_exec:
            await svc._run_index_job(doc, kb)
            mock_exec.assert_called_once_with(doc, kb)

    @pytest.mark.asyncio
    async def test_no_dispatcher_runs_inline(self):
        svc, (_kb, _doc, _job, _perm) = _make_service(dispatcher=None)

        doc = {"id": "doc-1", "content": "hello"}
        kb = {"id": "kb-1"}

        with patch.object(svc._indexing, "execute_index_job", new_callable=AsyncMock) as mock_exec:
            await svc._run_index_job(doc, kb)
            mock_exec.assert_called_once_with(doc, kb)


# ---------------------------------------------------------------------------
# Permission checks
# ---------------------------------------------------------------------------


class TestPermissionChecks:
    @pytest.mark.asyncio
    async def test_check_write_permission_raises_when_kb_not_found(self):
        svc, (kb_repo, *_rest) = _make_service()
        kb_repo.get_accessible = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match="not found"):
            await svc.check_write_permission(
                "kb-999", user_id="u1", tenant_id="t1", role="user"
            )

    @pytest.mark.asyncio
    async def test_check_write_permission_raises_on_denied(self):
        svc, (kb_repo, *_rest) = _make_service()
        kb = {"id": "kb-1", "visibility": "private", "owner_user_id": "other"}
        kb_repo.get_accessible = AsyncMock(return_value=kb)
        svc._access_control.can_write = AsyncMock(return_value=False)

        with pytest.raises(PermissionError, match="Write access denied"):
            await svc.check_write_permission(
                "kb-1", user_id="u1", tenant_id="t1", role="user"
            )

    @pytest.mark.asyncio
    async def test_check_write_permission_returns_kb_when_allowed(self):
        svc, (kb_repo, *_rest) = _make_service()
        kb = {"id": "kb-1", "visibility": "private", "owner_user_id": "u1"}
        kb_repo.get_accessible = AsyncMock(return_value=kb)
        svc._access_control.can_write = AsyncMock(return_value=True)

        result = await svc.check_write_permission(
            "kb-1", user_id="u1", tenant_id="t1", role="user"
        )
        assert result["id"] == "kb-1"

    @pytest.mark.asyncio
    async def test_check_admin_permission_raises_on_denied(self):
        svc, (kb_repo, *_rest) = _make_service()
        kb = {"id": "kb-1", "visibility": "private", "owner_user_id": "u1"}
        kb_repo.get_accessible = AsyncMock(return_value=kb)
        svc._access_control.can_admin = AsyncMock(return_value=False)

        with pytest.raises(PermissionError, match="Admin access denied"):
            await svc.check_admin_permission(
                "kb-1", user_id="u2", tenant_id="t1", role="user"
            )
