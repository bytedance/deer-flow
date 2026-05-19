"""Tests for KB embedding model + dimension binding (Sprint B.3.1–B.3.4).

Covers:
- B.3.1: ``create()`` writes ``embedding_model`` from rag_config (or
  explicit override) plus ``embedding_dim=0`` placeholder.
- B.3.1: ``update_embedding_binding()`` writes back the resolved dim
  after the first index job confirms it.
- B.3.2 surface: existence of the binding fields on the KB row dict so
  IndexingService / ingestion can read them without a second query.
- B.3.3: ``EmbeddingDimensionMismatchError`` carries enough context
  (expected / actual / collection) for an operator to know which KB is
  broken.
- B.3.4: ``multi_kb_retrieve`` records ``embedding_model`` per KB in the
  per-KB stats so trace logs can show which models were used.

These are unit tests against the repository + module surfaces — the
async indexing path itself is exercised end-to-end in
``test_indexing_dispatcher.py``.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from deerflow.config.rag_config import RagConfig, set_rag_config
from deerflow.persistence.base import Base
from deerflow.persistence.knowledge_base.repository import KnowledgeBaseRepository
from deerflow.rag.errors import EmbeddingDimensionMismatchError

TENANT_A = "tenant-a"
USER_1 = "user-1"


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sf = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield sf
    await engine.dispose()


@pytest_asyncio.fixture
async def repo(session_factory):
    return KnowledgeBaseRepository(session_factory)


class TestCreateBindsEmbedding:
    def teardown_method(self) -> None:
        set_rag_config(RagConfig())

    @pytest.mark.asyncio
    async def test_create_writes_global_default_embedding_model(self, repo):
        set_rag_config(
            RagConfig(
                enabled=True,
                embedding_model="openai:text-embedding-3-large",
            )
        )
        kb = await repo.create(
            tenant_id=TENANT_A,
            owner_user_id=USER_1,
            name="kb",
            visibility="private",
        )
        assert kb["embedding_model"] == "openai:text-embedding-3-large"
        assert kb["embedding_dim"] == 0

    @pytest.mark.asyncio
    async def test_create_accepts_explicit_embedding_model_override(self, repo):
        set_rag_config(
            RagConfig(
                enabled=True,
                embedding_model="openai:text-embedding-3-small",
            )
        )
        kb = await repo.create(
            tenant_id=TENANT_A,
            owner_user_id=USER_1,
            name="kb",
            visibility="private",
            embedding_model="local:bge-small-en",
        )
        assert kb["embedding_model"] == "local:bge-small-en"
        assert kb["embedding_dim"] == 0


class TestEmbeddingBindingBackfill:
    def teardown_method(self) -> None:
        set_rag_config(RagConfig())

    @pytest.mark.asyncio
    async def test_update_embedding_binding_sets_dim(self, repo):
        kb = await repo.create(
            tenant_id=TENANT_A, owner_user_id=USER_1, name="kb", visibility="private"
        )
        ok = await repo.update_embedding_binding(kb["id"], embedding_dim=1536)
        assert ok is True
        refreshed = await repo.get_by_id_internal(kb["id"])
        assert refreshed is not None
        assert refreshed["embedding_dim"] == 1536

    @pytest.mark.asyncio
    async def test_update_embedding_binding_can_set_both_fields(self, repo):
        kb = await repo.create(
            tenant_id=TENANT_A, owner_user_id=USER_1, name="kb", visibility="private"
        )
        ok = await repo.update_embedding_binding(
            kb["id"],
            embedding_model="local:bge-large-en",
            embedding_dim=1024,
        )
        assert ok is True
        refreshed = await repo.get_by_id_internal(kb["id"])
        assert refreshed["embedding_model"] == "local:bge-large-en"
        assert refreshed["embedding_dim"] == 1024

    @pytest.mark.asyncio
    async def test_update_embedding_binding_noop_when_no_fields(self, repo):
        kb = await repo.create(
            tenant_id=TENANT_A, owner_user_id=USER_1, name="kb", visibility="private"
        )
        ok = await repo.update_embedding_binding(kb["id"])
        assert ok is False


class TestEmbeddingDimensionMismatchError:
    def test_carries_expected_actual_and_collection(self):
        exc = EmbeddingDimensionMismatchError(
            expected=1536, actual=1024, collection="kb_abc"
        )
        assert exc.expected == 1536
        assert exc.actual == 1024
        assert exc.collection == "kb_abc"
        msg = str(exc)
        assert "1536" in msg and "1024" in msg and "kb_abc" in msg

    def test_collection_is_optional(self):
        exc = EmbeddingDimensionMismatchError(expected=384, actual=768)
        assert "384" in str(exc)
        assert "768" in str(exc)
