"""Unit tests for report_templates.permissions — §11.1 matrix predicates."""

from __future__ import annotations

from deerflow.report_templates.permissions import (
    Principal,
    check_permission,
)
from deerflow.report_templates.records import (
    ReportTemplateRecord,
    new_template_id,
    now_iso,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _template(
    *,
    visibility: str = "private",
    owner: str = "owner_user",
    tenant: str = "tenant_a",
    status: str = "draft",
) -> ReportTemplateRecord:
    return ReportTemplateRecord(
        id=new_template_id(),
        name="demo",
        display_name="Demo",
        owner_user_id=owner,
        tenant_id=tenant,
        visibility=visibility,  # type: ignore[arg-type]
        status=status,  # type: ignore[arg-type]
        current_version=1 if status == "published" else 0,
        created_at=now_iso(),
        updated_at=now_iso(),
        etag="etag-1",
    )


OWNER = Principal(user_id="owner_user", tenant_id="tenant_a")
TENANT_MEMBER = Principal(user_id="bob", tenant_id="tenant_a")
OTHER_TENANT = Principal(user_id="bob", tenant_id="tenant_b")
TENANT_ADMIN = Principal(user_id="admin", tenant_id="tenant_a", is_tenant_admin=True)
SUPERADMIN = Principal(user_id="root", tenant_id="tenant_b", is_superadmin=True)


# ---------------------------------------------------------------------------
# View
# ---------------------------------------------------------------------------


class TestView:
    def test_owner_can_view_private(self):
        assert check_permission(principal=OWNER, operation="view", template=_template()).allowed

    def test_non_owner_cannot_view_private(self):
        d = check_permission(principal=TENANT_MEMBER, operation="view", template=_template())
        assert not d.allowed and "owner" in d.reason

    def test_superadmin_can_view_private(self):
        assert check_permission(principal=SUPERADMIN, operation="view", template=_template()).allowed

    def test_tenant_member_can_view_tenant(self):
        t = _template(visibility="tenant")
        assert check_permission(principal=TENANT_MEMBER, operation="view", template=t).allowed

    def test_other_tenant_cannot_view_tenant(self):
        t = _template(visibility="tenant")
        d = check_permission(principal=OTHER_TENANT, operation="view", template=t)
        assert not d.allowed and "tenant" in d.reason

    def test_everyone_can_view_builtin(self):
        t = _template(visibility="builtin")
        for p in (OWNER, TENANT_MEMBER, OTHER_TENANT, TENANT_ADMIN, SUPERADMIN):
            assert check_permission(principal=p, operation="view", template=t).allowed


# ---------------------------------------------------------------------------
# Edit / Publish
# ---------------------------------------------------------------------------


class TestEdit:
    def test_owner_can_edit_private(self):
        assert check_permission(
            principal=OWNER, operation="edit_draft", template=_template()
        ).allowed

    def test_non_owner_cannot_edit_private(self):
        d = check_permission(
            principal=TENANT_MEMBER, operation="edit_draft", template=_template()
        )
        assert not d.allowed

    def test_tenant_admin_can_edit_tenant(self):
        t = _template(visibility="tenant")
        assert check_permission(
            principal=TENANT_ADMIN, operation="edit_draft", template=t
        ).allowed

    def test_tenant_member_cannot_edit_tenant(self):
        t = _template(visibility="tenant")
        d = check_permission(
            principal=TENANT_MEMBER, operation="edit_draft", template=t
        )
        assert not d.allowed and "tenant_admin" in d.reason

    def test_superadmin_can_edit_builtin(self):
        t = _template(visibility="builtin")
        assert check_permission(
            principal=SUPERADMIN, operation="edit_draft", template=t
        ).allowed

    def test_tenant_admin_cannot_edit_builtin(self):
        t = _template(visibility="builtin")
        d = check_permission(
            principal=TENANT_ADMIN, operation="edit_draft", template=t
        )
        assert not d.allowed

    def test_publish_uses_same_predicate(self):
        # Tenant admin can publish a tenant template; member cannot.
        t = _template(visibility="tenant")
        assert check_permission(principal=TENANT_ADMIN, operation="publish", template=t).allowed
        assert not check_permission(principal=TENANT_MEMBER, operation="publish", template=t).allowed


# ---------------------------------------------------------------------------
# Archive / Delete
# ---------------------------------------------------------------------------


class TestArchiveDelete:
    def test_owner_can_delete_private(self):
        assert check_permission(principal=OWNER, operation="delete", template=_template()).allowed

    def test_member_cannot_delete_tenant(self):
        t = _template(visibility="tenant")
        d = check_permission(principal=TENANT_MEMBER, operation="delete", template=t)
        assert not d.allowed

    def test_tenant_admin_can_delete_tenant(self):
        t = _template(visibility="tenant")
        assert check_permission(principal=TENANT_ADMIN, operation="delete", template=t).allowed

    def test_only_superadmin_can_delete_builtin(self):
        t = _template(visibility="builtin")
        assert check_permission(principal=SUPERADMIN, operation="delete", template=t).allowed
        assert not check_permission(principal=TENANT_ADMIN, operation="delete", template=t).allowed
        assert not check_permission(principal=OWNER, operation="delete", template=t).allowed


# ---------------------------------------------------------------------------
# Fork — anyone who can view can fork
# ---------------------------------------------------------------------------


class TestFork:
    def test_anyone_can_fork_builtin(self):
        t = _template(visibility="builtin")
        for p in (OWNER, TENANT_MEMBER, OTHER_TENANT, TENANT_ADMIN, SUPERADMIN):
            assert check_permission(principal=p, operation="fork", template=t).allowed

    def test_cannot_fork_unviewable_private(self):
        t = _template()
        d = check_permission(principal=TENANT_MEMBER, operation="fork", template=t)
        assert not d.allowed

    def test_tenant_member_can_fork_tenant(self):
        t = _template(visibility="tenant")
        assert check_permission(principal=TENANT_MEMBER, operation="fork", template=t).allowed


# ---------------------------------------------------------------------------
# Visibility promotion
# ---------------------------------------------------------------------------


class TestPromotion:
    def test_member_cannot_promote_to_tenant(self):
        t = _template()
        d = check_permission(principal=TENANT_MEMBER, operation="promote_to_tenant", template=t)
        assert not d.allowed

    def test_tenant_admin_can_promote_to_tenant(self):
        t = _template()  # private, tenant_a
        # promote_to_tenant requires tenant_admin AND same tenant
        assert check_permission(
            principal=TENANT_ADMIN, operation="promote_to_tenant", template=t
        ).allowed

    def test_tenant_admin_cannot_promote_other_tenants_template(self):
        t = _template(tenant="tenant_b")
        d = check_permission(
            principal=TENANT_ADMIN, operation="promote_to_tenant", template=t
        )
        assert not d.allowed

    def test_only_superadmin_can_promote_to_builtin(self):
        t = _template()
        for p in (OWNER, TENANT_MEMBER, TENANT_ADMIN):
            d = check_permission(principal=p, operation="promote_to_builtin", template=t)
            assert not d.allowed
        assert check_permission(
            principal=SUPERADMIN, operation="promote_to_builtin", template=t
        ).allowed


class TestUnknownOperation:
    def test_unknown_operation_denied(self):
        t = _template()
        d = check_permission(
            principal=SUPERADMIN, operation="totally_made_up", template=t  # type: ignore[arg-type]
        )
        assert not d.allowed
