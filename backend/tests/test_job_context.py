"""Tests for ``with_kb_context`` + Chroma default-tenant guard (Sprint B.4).

Covers:
- B.4.1: ``with_kb_context`` sets tenant_id (and optionally user_id)
  on entry and restores them on exit. Refuses empty / "default" tenant
  values so a misconfigured caller doesn't silently fall back.
- B.4.1: tokens are correctly nested — re-entering with a different
  tenant restores the outer tenant on exit, not the global default.
- B.4.2: dispatcher worker wraps ``execute_index_job`` in
  ``with_kb_context`` so the KB row's tenant is in scope when the job
  resolves a Chroma collection name.
- B.4.3: ``ChromaVectorStore._collection_name`` raises when the
  current tenant is "default" while ``allow_no_auth_kb=False``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from deerflow.config.rag_config import RagConfig, set_rag_config
from deerflow.config.tenant import (
    _DEFAULT_TENANT_ID,
    get_current_tenant_id,
)
from deerflow.rag.backends.chroma import ChromaVectorStore
from deerflow.rag.job_context import with_kb_context


class TestWithKbContextScoping:
    @pytest.mark.asyncio
    async def test_sets_tenant_inside_block_and_restores_on_exit(self):
        before = get_current_tenant_id()
        async with with_kb_context(tenant_id="acme-corp"):
            assert get_current_tenant_id() == "acme-corp"
        assert get_current_tenant_id() == before

    @pytest.mark.asyncio
    async def test_nested_blocks_restore_outer_tenant(self):
        async with with_kb_context(tenant_id="outer"):
            assert get_current_tenant_id() == "outer"
            async with with_kb_context(tenant_id="inner"):
                assert get_current_tenant_id() == "inner"
            assert get_current_tenant_id() == "outer"
        assert get_current_tenant_id() == _DEFAULT_TENANT_ID

    @pytest.mark.asyncio
    async def test_rejects_default_tenant_id(self):
        with pytest.raises(ValueError, match="real tenant_id"):
            async with with_kb_context(tenant_id="default"):
                pass

    @pytest.mark.asyncio
    async def test_rejects_empty_tenant_id(self):
        with pytest.raises(ValueError, match="real tenant_id"):
            async with with_kb_context(tenant_id=""):
                pass

    @pytest.mark.asyncio
    async def test_user_id_is_optional_and_scoped(self):
        from deerflow.runtime.user_context import get_current_user

        # The conftest autouse fixture seeds a "test-user-autouse"
        # contextvar before each test. We just need to verify the
        # override scopes correctly: inside the block we see u-1,
        # outside we see whatever was there before.
        before = get_current_user()
        async with with_kb_context(tenant_id="acme", user_id="u-1"):
            user = get_current_user()
            assert user is not None
            assert user.id == "u-1"
        assert get_current_user() is before


class TestDispatcherWrapsExecuteWithContext:
    @pytest.mark.asyncio
    async def test_worker_loop_restores_tenant_for_each_job(self):
        from deerflow.knowledge_base.dispatcher import (
            IndexingDispatcher,
            IndexJobRequest,
        )

        observed: list[str] = []

        async def fake_execute(doc, kb):
            observed.append(get_current_tenant_id())

        svc = MagicMock()
        svc.execute_index_job = AsyncMock(side_effect=fake_execute)

        kb_repo = MagicMock()
        doc_repo = MagicMock()
        doc_repo.update_index_status = AsyncMock()

        disp = IndexingDispatcher(
            indexing_service=svc,
            kb_repo=kb_repo,
            doc_repo=doc_repo,
            workers=1,
            queue_max=4,
        )
        await disp.start()
        try:
            await disp.submit(
                IndexJobRequest(
                    document={
                        "id": "d1",
                        "knowledge_base_id": "kb-1",
                        "version": 1,
                        "tenant_id": "acme-corp",
                        "owner_user_id": "u-1",
                    },
                    knowledge_base={"id": "kb-1", "collection_name": "kb_x"},
                )
            )
            # Drain queue
            await disp._queue.join()
        finally:
            await disp.aclose()

        assert observed == ["acme-corp"]

    @pytest.mark.asyncio
    async def test_worker_restores_outer_context_after_job(self):
        from deerflow.knowledge_base.dispatcher import (
            IndexingDispatcher,
            IndexJobRequest,
        )

        async def noop(doc, kb):
            return None

        svc = MagicMock()
        svc.execute_index_job = AsyncMock(side_effect=noop)
        kb_repo = MagicMock()
        doc_repo = MagicMock()
        doc_repo.update_index_status = AsyncMock()

        disp = IndexingDispatcher(
            indexing_service=svc,
            kb_repo=kb_repo,
            doc_repo=doc_repo,
            workers=1,
            queue_max=4,
        )
        await disp.start()
        try:
            await disp.submit(
                IndexJobRequest(
                    document={
                        "id": "d1",
                        "knowledge_base_id": "kb-1",
                        "version": 1,
                        "tenant_id": "acme-corp",
                        "owner_user_id": "u-1",
                    },
                    knowledge_base={"id": "kb-1", "collection_name": "kb_x"},
                )
            )
            await disp._queue.join()
        finally:
            await disp.aclose()

        # Worker task is gone; foreground context never saw the
        # acme-corp tenant.
        assert get_current_tenant_id() == _DEFAULT_TENANT_ID


class TestChromaDefaultTenantGuard:
    def teardown_method(self) -> None:
        set_rag_config(RagConfig())

    def test_collection_name_raises_in_default_tenant_when_no_auth_disabled(
        self,
    ):
        set_rag_config(RagConfig(allow_no_auth_kb=False))
        store = ChromaVectorStore()
        with pytest.raises(RuntimeError, match="tenant_id='default'"):
            store._collection_name("kb_x")

    def test_collection_name_allows_default_when_no_auth_enabled(self):
        set_rag_config(RagConfig(allow_no_auth_kb=True))
        store = ChromaVectorStore()
        # No raise — dev/demo posture lets the global tenant collection
        # be used.
        name = store._collection_name("kb_x")
        assert name.endswith("_kb_x")

    @pytest.mark.asyncio
    async def test_collection_name_passes_under_with_kb_context(self):
        set_rag_config(RagConfig(allow_no_auth_kb=False))
        store = ChromaVectorStore()
        async with with_kb_context(tenant_id="acme-corp"):
            name = store._collection_name("kb_x")
        assert name == "acme-corp_kb_x"
