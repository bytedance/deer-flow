"""Tests for three-level knowledge base visibility access control.

Covers:
- Private: only owner can see
- Tenant: any user in the same tenant can see
- Public: any user can see
- Visibility filter on list
- resolve_accessible_by_ids / resolve_accessible_by_collections
- create with visibility parameter
- update cannot change visibility
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from deerflow.persistence.base import Base
from deerflow.persistence.knowledge_base.repository import KnowledgeBaseRepository

TENANT_A = "tenant-a"
TENANT_B = "tenant-b"
USER_1 = "user-1"
USER_2 = "user-2"
USER_3 = "user-3"


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


@pytest_asyncio.fixture
async def seeded_kbs(repo: KnowledgeBaseRepository):
    """Create a set of KBs with different visibility levels for testing."""
    private_kb = await repo.create(
        tenant_id=TENANT_A, owner_user_id=USER_1, name="Private KB", visibility="private"
    )
    tenant_kb = await repo.create(
        tenant_id=TENANT_A, owner_user_id=USER_1, name="Tenant KB", visibility="tenant"
    )
    public_kb = await repo.create(
        tenant_id=TENANT_A, owner_user_id=USER_1, name="Public KB", visibility="public"
    )
    other_tenant_private = await repo.create(
        tenant_id=TENANT_B, owner_user_id=USER_3, name="Other Tenant Private", visibility="private"
    )
    other_tenant_tenant = await repo.create(
        tenant_id=TENANT_B, owner_user_id=USER_3, name="Other Tenant Shared", visibility="tenant"
    )
    return {
        "private": private_kb,
        "tenant": tenant_kb,
        "public": public_kb,
        "other_private": other_tenant_private,
        "other_tenant": other_tenant_tenant,
    }


class TestListAccessible:
    @pytest.mark.asyncio
    async def test_owner_sees_all_own_and_tenant_and_public(self, repo, seeded_kbs):
        """Owner (user-1, tenant-a) sees: own private + tenant-a tenant + all public."""
        items = await repo.list_accessible(tenant_id=TENANT_A, user_id=USER_1)
        names = {i["name"] for i in items}
        assert "Private KB" in names
        assert "Tenant KB" in names
        assert "Public KB" in names
        assert "Other Tenant Private" not in names
        # Public from other tenant is visible
        # Other tenant's "tenant" visibility is NOT visible to tenant-a user
        assert "Other Tenant Shared" not in names

    @pytest.mark.asyncio
    async def test_same_tenant_user_sees_tenant_and_public_not_private(self, repo, seeded_kbs):
        """User-2 in tenant-a sees tenant + public KBs, but NOT user-1's private KB."""
        items = await repo.list_accessible(tenant_id=TENANT_A, user_id=USER_2)
        names = {i["name"] for i in items}
        assert "Private KB" not in names
        assert "Tenant KB" in names
        assert "Public KB" in names

    @pytest.mark.asyncio
    async def test_different_tenant_user_sees_only_public(self, repo, seeded_kbs):
        """User-3 in tenant-b sees only public KBs from tenant-a."""
        items = await repo.list_accessible(tenant_id=TENANT_B, user_id=USER_3)
        names = {i["name"] for i in items}
        # Can see own private and own tenant
        assert "Other Tenant Private" in names
        assert "Other Tenant Shared" in names
        # Can see public from any tenant
        assert "Public KB" in names
        # Cannot see tenant-a private or tenant-scoped
        assert "Private KB" not in names
        assert "Tenant KB" not in names

    @pytest.mark.asyncio
    async def test_visibility_filter_private(self, repo, seeded_kbs):
        items = await repo.list_accessible(
            tenant_id=TENANT_A, user_id=USER_1, visibility_filter="private"
        )
        assert all(i["visibility"] == "private" for i in items)
        assert len(items) == 1
        assert items[0]["name"] == "Private KB"

    @pytest.mark.asyncio
    async def test_visibility_filter_tenant(self, repo, seeded_kbs):
        items = await repo.list_accessible(
            tenant_id=TENANT_A, user_id=USER_2, visibility_filter="tenant"
        )
        assert all(i["visibility"] == "tenant" for i in items)
        assert len(items) == 1

    @pytest.mark.asyncio
    async def test_visibility_filter_public(self, repo, seeded_kbs):
        items = await repo.list_accessible(
            tenant_id=TENANT_A, user_id=USER_2, visibility_filter="public"
        )
        assert all(i["visibility"] == "public" for i in items)
        assert len(items) == 1

    @pytest.mark.asyncio
    async def test_pagination(self, repo, seeded_kbs):
        items = await repo.list_accessible(tenant_id=TENANT_A, user_id=USER_1, limit=2, offset=0)
        assert len(items) == 2
        items2 = await repo.list_accessible(tenant_id=TENANT_A, user_id=USER_1, limit=2, offset=2)
        assert len(items2) == 1


class TestGetAccessible:
    @pytest.mark.asyncio
    async def test_owner_can_access_own_private(self, repo, seeded_kbs):
        kb = await repo.get_accessible(
            seeded_kbs["private"]["id"], tenant_id=TENANT_A, user_id=USER_1
        )
        assert kb is not None
        assert kb["name"] == "Private KB"

    @pytest.mark.asyncio
    async def test_other_user_cannot_access_private(self, repo, seeded_kbs):
        kb = await repo.get_accessible(
            seeded_kbs["private"]["id"], tenant_id=TENANT_A, user_id=USER_2
        )
        assert kb is None

    @pytest.mark.asyncio
    async def test_same_tenant_user_can_access_tenant_kb(self, repo, seeded_kbs):
        kb = await repo.get_accessible(
            seeded_kbs["tenant"]["id"], tenant_id=TENANT_A, user_id=USER_2
        )
        assert kb is not None
        assert kb["name"] == "Tenant KB"

    @pytest.mark.asyncio
    async def test_different_tenant_cannot_access_tenant_kb(self, repo, seeded_kbs):
        kb = await repo.get_accessible(
            seeded_kbs["tenant"]["id"], tenant_id=TENANT_B, user_id=USER_3
        )
        assert kb is None

    @pytest.mark.asyncio
    async def test_any_user_can_access_public_kb(self, repo, seeded_kbs):
        kb = await repo.get_accessible(
            seeded_kbs["public"]["id"], tenant_id=TENANT_B, user_id=USER_3
        )
        assert kb is not None
        assert kb["name"] == "Public KB"

    @pytest.mark.asyncio
    async def test_deleted_kb_not_accessible(self, repo, seeded_kbs):
        await repo.soft_delete(
            seeded_kbs["public"]["id"], tenant_id=TENANT_A, owner_user_id=USER_1
        )
        kb = await repo.get_accessible(
            seeded_kbs["public"]["id"], tenant_id=TENANT_A, user_id=USER_1
        )
        assert kb is None


class TestResolveAccessibleByIds:
    @pytest.mark.asyncio
    async def test_returns_accessible_kbs_only(self, repo, seeded_kbs):
        all_ids = [seeded_kbs[k]["id"] for k in seeded_kbs]
        results = await repo.resolve_accessible_by_ids(
            all_ids, tenant_id=TENANT_A, user_id=USER_2
        )
        names = {r["name"] for r in results}
        # user-2 in tenant-a: sees tenant + public, not private
        assert "Private KB" not in names
        assert "Tenant KB" in names
        assert "Public KB" in names
        # other tenant's private/tenant not visible
        assert "Other Tenant Private" not in names
        assert "Other Tenant Shared" not in names

    @pytest.mark.asyncio
    async def test_empty_ids_returns_empty(self, repo, seeded_kbs):
        results = await repo.resolve_accessible_by_ids(
            [], tenant_id=TENANT_A, user_id=USER_1
        )
        assert results == []

    @pytest.mark.asyncio
    async def test_owner_sees_own_private_in_batch(self, repo, seeded_kbs):
        results = await repo.resolve_accessible_by_ids(
            [seeded_kbs["private"]["id"]], tenant_id=TENANT_A, user_id=USER_1
        )
        assert len(results) == 1
        assert results[0]["name"] == "Private KB"


class TestResolveAccessibleByCollections:
    @pytest.mark.asyncio
    async def test_returns_accessible_collections_only(self, repo, seeded_kbs):
        all_collections = [seeded_kbs[k]["collection_name"] for k in seeded_kbs]
        results = await repo.resolve_accessible_by_collections(
            all_collections, tenant_id=TENANT_A, user_id=USER_2
        )
        names = {r["name"] for r in results}
        assert "Private KB" not in names
        assert "Tenant KB" in names
        assert "Public KB" in names

    @pytest.mark.asyncio
    async def test_empty_collections_returns_empty(self, repo, seeded_kbs):
        results = await repo.resolve_accessible_by_collections(
            [], tenant_id=TENANT_A, user_id=USER_1
        )
        assert results == []


class TestCreateWithVisibility:
    @pytest.mark.asyncio
    async def test_default_visibility_is_private(self, repo):
        kb = await repo.create(tenant_id=TENANT_A, owner_user_id=USER_1, name="Default")
        assert kb["visibility"] == "private"

    @pytest.mark.asyncio
    async def test_create_with_tenant_visibility(self, repo):
        kb = await repo.create(
            tenant_id=TENANT_A, owner_user_id=USER_1, name="Shared", visibility="tenant"
        )
        assert kb["visibility"] == "tenant"

    @pytest.mark.asyncio
    async def test_create_with_public_visibility(self, repo):
        kb = await repo.create(
            tenant_id=TENANT_A, owner_user_id=USER_1, name="Open", visibility="public"
        )
        assert kb["visibility"] == "public"


class TestUpdateCannotChangeVisibility:
    @pytest.mark.asyncio
    async def test_visibility_not_in_allowed_update_fields(self, repo):
        kb = await repo.create(
            tenant_id=TENANT_A, owner_user_id=USER_1, name="Test", visibility="private"
        )
        updated = await repo.update(
            kb["id"], tenant_id=TENANT_A, owner_user_id=USER_1, visibility="public"
        )
        assert updated is not None
        assert updated["visibility"] == "private"
