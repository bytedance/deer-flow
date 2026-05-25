"""ISSUE-04: Permission consistency verification tests.

Validates that KB access control is consistent across the three consumption
chains (REST API search, RAG tool retrieval, report generation).
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from deerflow.knowledge_base.access_control import KbAccessControl, UserContext
from deerflow.persistence.knowledge_base.permission_repository import KbPermissionRepository


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_kb(**overrides) -> dict:
    """Build a KB dict with defaults that represent a private, active KB."""
    kb = {
        "id": "kb-test-1",
        "tenant_id": "tenant-a",
        "owner_user_id": "owner-1",
        "visibility": "private",
        "status": "active",
        "deleted_at": None,
        "name": "Test KB",
        "collection_name": "test_collection",
    }
    kb.update(overrides)
    return kb


def _make_user(**overrides) -> UserContext:
    return UserContext(
        user_id=overrides.get("user_id", "owner-1"),
        tenant_id=overrides.get("tenant_id", "tenant-a"),
        role=overrides.get("role", "user"),
    )


def _make_mock_permission_repo(*, granted_role: str | None = None):
    """Create a mock KbPermissionRepo that returns ``granted_role`` from get_user_role."""
    repo = MagicMock(spec=KbPermissionRepository)
    repo.get_user_role = AsyncMock(return_value=granted_role)
    return repo


# ---------------------------------------------------------------------------
# can_read — visibility-based access (sync, deterministic)
# ---------------------------------------------------------------------------


class TestCanRead:
    """can_read is the foundation: private→owner, tenant→tenant-members, public→everyone."""

    def test_private_kb_owner_can_read(self):
        ac = KbAccessControl(permission_repo=None)
        kb = _make_kb(visibility="private")
        user = _make_user(user_id="owner-1")
        assert ac.can_read(user, kb) is True

    def test_private_kb_non_owner_cannot_read(self):
        ac = KbAccessControl(permission_repo=None)
        kb = _make_kb(visibility="private")
        user = _make_user(user_id="other-user")
        assert ac.can_read(user, kb) is False

    def test_tenant_kb_same_tenant_can_read(self):
        ac = KbAccessControl(permission_repo=None)
        kb = _make_kb(visibility="tenant")
        user = _make_user(user_id="anyone", tenant_id="tenant-a")
        assert ac.can_read(user, kb) is True

    def test_tenant_kb_different_tenant_cannot_read(self):
        ac = KbAccessControl(permission_repo=None)
        kb = _make_kb(visibility="tenant", tenant_id="tenant-a")
        user = _make_user(user_id="anyone", tenant_id="tenant-b")
        assert ac.can_read(user, kb) is False

    def test_public_kb_anyone_can_read(self):
        ac = KbAccessControl(permission_repo=None)
        kb = _make_kb(visibility="public")
        user = _make_user(user_id="anyone", tenant_id="any-tenant")
        assert ac.can_read(user, kb) is True

    def test_deleted_kb_cannot_read(self):
        ac = KbAccessControl(permission_repo=None)
        kb = _make_kb(visibility="public", deleted_at="2024-01-01")
        user = _make_user()
        assert ac.can_read(user, kb) is False


# ---------------------------------------------------------------------------
# can_create — visibility-level creation permissions
# ---------------------------------------------------------------------------


class TestCanCreate:
    def test_anyone_can_create_private_kb(self):
        ac = KbAccessControl(permission_repo=None)
        assert ac.can_create(_make_user(role="user"), "private") is True

    def test_only_admin_can_create_tenant_kb(self):
        ac = KbAccessControl(permission_repo=None)
        assert ac.can_create(_make_user(role="user"), "tenant") is False
        assert ac.can_create(_make_user(role="tenant_admin"), "tenant") is True
        assert ac.can_create(_make_user(role="superadmin"), "tenant") is True

    def test_only_superadmin_can_create_public_kb(self):
        ac = KbAccessControl(permission_repo=None)
        assert ac.can_create(_make_user(role="tenant_admin"), "public") is False
        assert ac.can_create(_make_user(role="superadmin"), "public") is True


# ---------------------------------------------------------------------------
# get_user_kb_role — effective role resolution
# ---------------------------------------------------------------------------


class TestGetUserKbRole:
    @pytest.mark.asyncio
    async def test_owner_gets_owner_role(self):
        ac = KbAccessControl(permission_repo=None)
        kb = _make_kb(visibility="private")
        user = _make_user(user_id="owner-1")
        role = await ac.get_user_kb_role(user, kb)
        assert role == "owner"

    @pytest.mark.asyncio
    async def test_non_owner_on_private_gets_none(self):
        ac = KbAccessControl(permission_repo=None)
        kb = _make_kb(visibility="private")
        user = _make_user(user_id="stranger")
        role = await ac.get_user_kb_role(user, kb)
        assert role is None

    @pytest.mark.asyncio
    async def test_tenant_member_gets_viewer(self):
        ac = KbAccessControl(permission_repo=_make_mock_permission_repo(granted_role=None))
        kb = _make_kb(visibility="tenant")
        user = _make_user(user_id="member-1")
        role = await ac.get_user_kb_role(user, kb)
        assert role == "viewer"

    @pytest.mark.asyncio
    async def test_public_kb_stranger_gets_viewer(self):
        ac = KbAccessControl(permission_repo=_make_mock_permission_repo(granted_role=None))
        kb = _make_kb(visibility="public")
        user = _make_user(user_id="stranger", tenant_id="other-tenant")
        role = await ac.get_user_kb_role(user, kb)
        assert role == "viewer"


# ---------------------------------------------------------------------------
# Consistency: the three read paths MUST use the same visibility rules
# ---------------------------------------------------------------------------


class TestCrossChainConsistency:
    """The same visibility model governs all three consumption chains:

    1. REST API search  → ``KnowledgeBaseRepository.get_accessible()``
    2. RAG tool retrieve → ``KnowledgeBaseRepository.resolve_accessible_by_ids()``
    3. Report generation  → same RAG tool path as #2

    Both repository methods delegate to ``_build_access_conditions()`` which
    encodes the three-level visibility model (private/tenant/public).  These
    tests verify the access control model that underlies all three paths.
    """

    @pytest.mark.parametrize(
        "visibility,user_id,tenant_id,kb_tenant_id,expected",
        [
            # Private: only owner in same tenant
            ("private", "owner-1", "t1", "t1", True),
            ("private", "other", "t1", "t1", False),
            ("private", "owner-1", "t2", "t1", False),
            # Tenant: any member of the same tenant
            ("tenant", "anyone", "t1", "t1", True),
            ("tenant", "anyone", "t2", "t1", False),
            # Public: anyone
            ("public", "anyone", "t1", "t1", True),
            ("public", "anyone", "t2", "t1", True),
        ],
    )
    def test_access_control_consistency(
        self, visibility, user_id, tenant_id, kb_tenant_id, expected
    ):
        """All three chains ultimately resolve through the same visibility model."""
        ac = KbAccessControl(permission_repo=None)
        kb = _make_kb(visibility=visibility, tenant_id=kb_tenant_id)
        user = _make_user(user_id=user_id, tenant_id=tenant_id)
        # can_read is the base permission check used by all three chains
        assert ac.can_read(user, kb) is expected

    def test_private_kb_stays_isolated_across_tenants(self):
        """A private KB in tenant A must not be readable by anyone in tenant B."""
        ac = KbAccessControl(permission_repo=None)
        kb = _make_kb(visibility="private", tenant_id="tenant-a", owner_user_id="alice")
        # Owner in correct tenant
        assert ac.can_read(_make_user(user_id="alice", tenant_id="tenant-a"), kb) is True
        # Same user ID but wrong tenant — still denied
        assert ac.can_read(_make_user(user_id="alice", tenant_id="tenant-b"), kb) is False
        # Tenant admin in wrong tenant — denied
        assert ac.can_read(_make_user(user_id="bob", tenant_id="tenant-b", role="tenant_admin"), kb) is False

    def test_public_kb_excludes_deleted_kbs(self):
        """Deleted KBs are invisible regardless of visibility."""
        ac = KbAccessControl(permission_repo=None)
        kb = _make_kb(visibility="public", deleted_at="2024-01-01")
        assert ac.can_read(_make_user(), kb) is False
