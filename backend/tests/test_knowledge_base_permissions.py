"""Integration tests for knowledge base permission system (Sprint 2)."""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from deerflow.knowledge_base.access_control import KbAccessControl, UserContext
from deerflow.persistence.base import Base
from deerflow.persistence.knowledge_base.permission_repository import KbPermissionRepository
from deerflow.persistence.knowledge_base.repository import KnowledgeBaseRepository


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sf = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield sf
    await engine.dispose()


@pytest_asyncio.fixture
async def perm_repo(session_factory):
    return KbPermissionRepository(session_factory)


@pytest_asyncio.fixture
async def kb_repo(session_factory):
    return KnowledgeBaseRepository(session_factory)


@pytest_asyncio.fixture
async def access_control(perm_repo):
    return KbAccessControl(perm_repo)


TENANT = "tenant-1"
OWNER = "user-owner"
OTHER_USER = "user-other"
ADMIN_USER = "user-admin"


# ---------------------------------------------------------------------------
# Permission Repository Tests
# ---------------------------------------------------------------------------


class TestKbPermissionRepository:
    @pytest.mark.asyncio
    async def test_grant_and_get_role(self, perm_repo: KbPermissionRepository):
        await perm_repo.grant(
            knowledge_base_id="kb-1", tenant_id=TENANT, user_id=OTHER_USER, role="editor", granted_by=OWNER
        )
        role = await perm_repo.get_user_role(knowledge_base_id="kb-1", user_id=OTHER_USER)
        assert role == "editor"

    @pytest.mark.asyncio
    async def test_grant_upserts_role(self, perm_repo: KbPermissionRepository):
        await perm_repo.grant(
            knowledge_base_id="kb-1", tenant_id=TENANT, user_id=OTHER_USER, role="viewer", granted_by=OWNER
        )
        await perm_repo.grant(
            knowledge_base_id="kb-1", tenant_id=TENANT, user_id=OTHER_USER, role="admin", granted_by=OWNER
        )
        role = await perm_repo.get_user_role(knowledge_base_id="kb-1", user_id=OTHER_USER)
        assert role == "admin"

    @pytest.mark.asyncio
    async def test_revoke(self, perm_repo: KbPermissionRepository):
        await perm_repo.grant(
            knowledge_base_id="kb-1", tenant_id=TENANT, user_id=OTHER_USER, role="editor", granted_by=OWNER
        )
        revoked = await perm_repo.revoke(knowledge_base_id="kb-1", user_id=OTHER_USER)
        assert revoked is True
        role = await perm_repo.get_user_role(knowledge_base_id="kb-1", user_id=OTHER_USER)
        assert role is None

    @pytest.mark.asyncio
    async def test_revoke_nonexistent(self, perm_repo: KbPermissionRepository):
        revoked = await perm_repo.revoke(knowledge_base_id="kb-1", user_id="nobody")
        assert revoked is False

    @pytest.mark.asyncio
    async def test_list_by_kb(self, perm_repo: KbPermissionRepository):
        await perm_repo.grant(
            knowledge_base_id="kb-1", tenant_id=TENANT, user_id="u1", role="editor", granted_by=OWNER
        )
        await perm_repo.grant(
            knowledge_base_id="kb-1", tenant_id=TENANT, user_id="u2", role="admin", granted_by=OWNER
        )
        await perm_repo.grant(
            knowledge_base_id="kb-2", tenant_id=TENANT, user_id="u3", role="viewer", granted_by=OWNER
        )
        perms = await perm_repo.list_by_kb("kb-1")
        assert len(perms) == 2

    @pytest.mark.asyncio
    async def test_has_write_access(self, perm_repo: KbPermissionRepository):
        await perm_repo.grant(
            knowledge_base_id="kb-1", tenant_id=TENANT, user_id="u1", role="editor", granted_by=OWNER
        )
        await perm_repo.grant(
            knowledge_base_id="kb-1", tenant_id=TENANT, user_id="u2", role="viewer", granted_by=OWNER
        )
        assert await perm_repo.has_write_access(knowledge_base_id="kb-1", user_id="u1") is True
        assert await perm_repo.has_write_access(knowledge_base_id="kb-1", user_id="u2") is False
        assert await perm_repo.has_write_access(knowledge_base_id="kb-1", user_id="u3") is False


# ---------------------------------------------------------------------------
# Access Control Tests
# ---------------------------------------------------------------------------


def _make_kb(
    kb_id: str = "kb-1",
    owner: str = OWNER,
    tenant: str = TENANT,
    visibility: str = "private",
    deleted_at=None,
) -> dict:
    return {
        "id": kb_id,
        "owner_user_id": owner,
        "tenant_id": tenant,
        "visibility": visibility,
        "deleted_at": deleted_at,
    }


class TestKbAccessControlCanRead:
    def test_private_owner_can_read(self, access_control: KbAccessControl):
        user = UserContext(user_id=OWNER, tenant_id=TENANT, role="user")
        kb = _make_kb(visibility="private")
        assert access_control.can_read(user, kb) is True

    def test_private_other_cannot_read(self, access_control: KbAccessControl):
        user = UserContext(user_id=OTHER_USER, tenant_id=TENANT, role="user")
        kb = _make_kb(visibility="private")
        assert access_control.can_read(user, kb) is False

    def test_tenant_same_tenant_can_read(self, access_control: KbAccessControl):
        user = UserContext(user_id=OTHER_USER, tenant_id=TENANT, role="user")
        kb = _make_kb(visibility="tenant")
        assert access_control.can_read(user, kb) is True

    def test_tenant_different_tenant_cannot_read(self, access_control: KbAccessControl):
        user = UserContext(user_id=OTHER_USER, tenant_id="other-tenant", role="user")
        kb = _make_kb(visibility="tenant")
        assert access_control.can_read(user, kb) is False

    def test_public_anyone_can_read(self, access_control: KbAccessControl):
        user = UserContext(user_id="random", tenant_id="any-tenant", role="user")
        kb = _make_kb(visibility="public")
        assert access_control.can_read(user, kb) is True

    def test_deleted_kb_cannot_read(self, access_control: KbAccessControl):
        user = UserContext(user_id=OWNER, tenant_id=TENANT, role="user")
        kb = _make_kb(visibility="private", deleted_at="2026-01-01")
        assert access_control.can_read(user, kb) is False


class TestKbAccessControlCanWrite:
    @pytest.mark.asyncio
    async def test_private_owner_can_write(self, access_control: KbAccessControl):
        user = UserContext(user_id=OWNER, tenant_id=TENANT, role="user")
        kb = _make_kb(visibility="private")
        assert await access_control.can_write(user, kb) is True

    @pytest.mark.asyncio
    async def test_private_other_cannot_write(self, access_control: KbAccessControl):
        user = UserContext(user_id=OTHER_USER, tenant_id=TENANT, role="user")
        kb = _make_kb(visibility="private")
        assert await access_control.can_write(user, kb) is False

    @pytest.mark.asyncio
    async def test_tenant_admin_can_write(self, access_control: KbAccessControl):
        user = UserContext(user_id=ADMIN_USER, tenant_id=TENANT, role="tenant_admin")
        kb = _make_kb(visibility="tenant")
        assert await access_control.can_write(user, kb) is True

    @pytest.mark.asyncio
    async def test_tenant_superadmin_can_write(self, access_control: KbAccessControl):
        user = UserContext(user_id=ADMIN_USER, tenant_id=TENANT, role="superadmin")
        kb = _make_kb(visibility="tenant")
        assert await access_control.can_write(user, kb) is True

    @pytest.mark.asyncio
    async def test_tenant_user_without_grant_cannot_write(self, access_control: KbAccessControl):
        user = UserContext(user_id=OTHER_USER, tenant_id=TENANT, role="user")
        kb = _make_kb(visibility="tenant")
        assert await access_control.can_write(user, kb) is False

    @pytest.mark.asyncio
    async def test_tenant_user_with_editor_grant_can_write(self, access_control: KbAccessControl, perm_repo):
        await perm_repo.grant(
            knowledge_base_id="kb-1", tenant_id=TENANT, user_id=OTHER_USER, role="editor", granted_by=OWNER
        )
        user = UserContext(user_id=OTHER_USER, tenant_id=TENANT, role="user")
        kb = _make_kb(visibility="tenant")
        assert await access_control.can_write(user, kb) is True

    @pytest.mark.asyncio
    async def test_public_superadmin_can_write(self, access_control: KbAccessControl):
        user = UserContext(user_id=ADMIN_USER, tenant_id=TENANT, role="superadmin")
        kb = _make_kb(visibility="public")
        assert await access_control.can_write(user, kb) is True

    @pytest.mark.asyncio
    async def test_public_regular_user_cannot_write(self, access_control: KbAccessControl):
        user = UserContext(user_id=OTHER_USER, tenant_id=TENANT, role="user")
        kb = _make_kb(visibility="public")
        assert await access_control.can_write(user, kb) is False


class TestKbAccessControlCanAdmin:
    @pytest.mark.asyncio
    async def test_private_owner_can_admin(self, access_control: KbAccessControl):
        user = UserContext(user_id=OWNER, tenant_id=TENANT, role="user")
        kb = _make_kb(visibility="private")
        assert await access_control.can_admin(user, kb) is True

    @pytest.mark.asyncio
    async def test_private_other_cannot_admin(self, access_control: KbAccessControl):
        user = UserContext(user_id=OTHER_USER, tenant_id=TENANT, role="user")
        kb = _make_kb(visibility="private")
        assert await access_control.can_admin(user, kb) is False

    @pytest.mark.asyncio
    async def test_tenant_admin_role_can_admin(self, access_control: KbAccessControl):
        user = UserContext(user_id=ADMIN_USER, tenant_id=TENANT, role="tenant_admin")
        kb = _make_kb(visibility="tenant")
        assert await access_control.can_admin(user, kb) is True

    @pytest.mark.asyncio
    async def test_tenant_owner_can_admin(self, access_control: KbAccessControl):
        user = UserContext(user_id=OWNER, tenant_id=TENANT, role="user")
        kb = _make_kb(visibility="tenant")
        assert await access_control.can_admin(user, kb) is True

    @pytest.mark.asyncio
    async def test_tenant_user_with_admin_grant(self, access_control: KbAccessControl, perm_repo):
        await perm_repo.grant(
            knowledge_base_id="kb-1", tenant_id=TENANT, user_id=OTHER_USER, role="admin", granted_by=OWNER
        )
        user = UserContext(user_id=OTHER_USER, tenant_id=TENANT, role="user")
        kb = _make_kb(visibility="tenant")
        assert await access_control.can_admin(user, kb) is True

    @pytest.mark.asyncio
    async def test_tenant_user_with_editor_grant_cannot_admin(self, access_control: KbAccessControl, perm_repo):
        await perm_repo.grant(
            knowledge_base_id="kb-1", tenant_id=TENANT, user_id=OTHER_USER, role="editor", granted_by=OWNER
        )
        user = UserContext(user_id=OTHER_USER, tenant_id=TENANT, role="user")
        kb = _make_kb(visibility="tenant")
        assert await access_control.can_admin(user, kb) is False

    @pytest.mark.asyncio
    async def test_tenant_different_tenant_cannot_admin(self, access_control: KbAccessControl):
        user = UserContext(user_id=ADMIN_USER, tenant_id="other-tenant", role="tenant_admin")
        kb = _make_kb(visibility="tenant")
        assert await access_control.can_admin(user, kb) is False


class TestKbAccessControlCanCreate:
    def test_any_user_can_create_private(self, access_control: KbAccessControl):
        user = UserContext(user_id=OTHER_USER, tenant_id=TENANT, role="user")
        assert access_control.can_create(user, "private") is True

    def test_regular_user_cannot_create_tenant(self, access_control: KbAccessControl):
        user = UserContext(user_id=OTHER_USER, tenant_id=TENANT, role="user")
        assert access_control.can_create(user, "tenant") is False

    def test_tenant_admin_can_create_tenant(self, access_control: KbAccessControl):
        user = UserContext(user_id=ADMIN_USER, tenant_id=TENANT, role="tenant_admin")
        assert access_control.can_create(user, "tenant") is True

    def test_superadmin_can_create_public(self, access_control: KbAccessControl):
        user = UserContext(user_id=ADMIN_USER, tenant_id=TENANT, role="superadmin")
        assert access_control.can_create(user, "public") is True

    def test_tenant_admin_cannot_create_public(self, access_control: KbAccessControl):
        user = UserContext(user_id=ADMIN_USER, tenant_id=TENANT, role="tenant_admin")
        assert access_control.can_create(user, "public") is False


class TestKbAccessControlGetUserRole:
    @pytest.mark.asyncio
    async def test_owner_gets_owner_role(self, access_control: KbAccessControl):
        user = UserContext(user_id=OWNER, tenant_id=TENANT, role="user")
        kb = _make_kb(visibility="tenant")
        assert await access_control.get_user_kb_role(user, kb) == "owner"

    @pytest.mark.asyncio
    async def test_tenant_admin_gets_admin_role(self, access_control: KbAccessControl):
        user = UserContext(user_id=ADMIN_USER, tenant_id=TENANT, role="tenant_admin")
        kb = _make_kb(visibility="tenant")
        assert await access_control.get_user_kb_role(user, kb) == "admin"

    @pytest.mark.asyncio
    async def test_granted_user_gets_granted_role(self, access_control: KbAccessControl, perm_repo):
        await perm_repo.grant(
            knowledge_base_id="kb-1", tenant_id=TENANT, user_id=OTHER_USER, role="editor", granted_by=OWNER
        )
        user = UserContext(user_id=OTHER_USER, tenant_id=TENANT, role="user")
        kb = _make_kb(visibility="tenant")
        assert await access_control.get_user_kb_role(user, kb) == "editor"

    @pytest.mark.asyncio
    async def test_tenant_user_without_grant_gets_viewer(self, access_control: KbAccessControl):
        user = UserContext(user_id=OTHER_USER, tenant_id=TENANT, role="user")
        kb = _make_kb(visibility="tenant")
        assert await access_control.get_user_kb_role(user, kb) == "viewer"

    @pytest.mark.asyncio
    async def test_private_non_owner_gets_none(self, access_control: KbAccessControl):
        user = UserContext(user_id=OTHER_USER, tenant_id=TENANT, role="user")
        kb = _make_kb(visibility="private")
        assert await access_control.get_user_kb_role(user, kb) is None
