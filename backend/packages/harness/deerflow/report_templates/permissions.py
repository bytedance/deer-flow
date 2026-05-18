"""Permission matrix for report templates (§11.1).

Stateless predicate helpers — callers pull authentication context (user_id,
tenant_id, role) from request scope and pass it explicitly. Repository writes
do **not** consult this module; permission enforcement lives in the API
(gateway) and tool (LLM-facing) layers per §8.1.

Roles (reused from ``tenant_agents.py``):
    - "superadmin"     → platform admin
    - "tenant_admin"   → tenant admin / editor
    - "member"         → regular user (default; any other string)

Decision matrix (§11.1 verbatim):

    operation     | private              | tenant                  | builtin
    ────────────────────────────────────────────────────────────────────────
    view          | owner                | tenant member           | all users
    run           | owner                | tenant member           | all users
    edit_draft    | owner                | tenant_admin            | platform_admin
    publish       | owner                | tenant_admin            | platform_admin
    archive       | owner                | tenant_admin            | platform_admin
    fork          | readable user        | readable user           | readable user
    delete        | owner                | tenant_admin            | platform_admin
    promote_*     | --                   | tenant_admin (priv→ten) | superadmin (ten→builtin)

``Decision`` carries both the boolean and a structured ``reason`` so callers
can return helpful error messages without leaking internal state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from deerflow.report_templates.records import (
    ReportTemplateRecord,
    Visibility,
)

Operation = Literal[
    "view",
    "run",
    "edit_draft",
    "publish",
    "archive",
    "fork",
    "delete",
    "promote_to_tenant",
    "promote_to_builtin",
]


@dataclass(frozen=True)
class Principal:
    """Authenticated subject performing the operation."""

    user_id: str
    tenant_id: str
    is_superadmin: bool = False
    is_tenant_admin: bool = False


@dataclass(frozen=True)
class Decision:
    """Permission decision."""

    allowed: bool
    reason: str

    @classmethod
    def allow(cls) -> "Decision":
        return cls(True, "allowed")

    @classmethod
    def deny(cls, reason: str) -> "Decision":
        return cls(False, reason)


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------


def check_permission(
    *,
    principal: Principal,
    operation: Operation,
    template: ReportTemplateRecord,
) -> Decision:
    """Decide whether ``principal`` may perform ``operation`` on ``template``."""
    if operation == "view":
        return _check_read(principal, template)
    if operation == "run":
        return _check_read(principal, template)
    if operation == "fork":
        return _check_read(principal, template)
    if operation == "edit_draft":
        return _check_write(principal, template)
    if operation == "publish":
        return _check_write(principal, template)
    if operation == "archive":
        return _check_admin_or_owner(principal, template)
    if operation == "delete":
        return _check_admin_or_owner(principal, template)
    if operation == "promote_to_tenant":
        if not principal.is_tenant_admin and not principal.is_superadmin:
            return Decision.deny("promoting to tenant visibility requires tenant_admin")
        if template.tenant_id != principal.tenant_id and not principal.is_superadmin:
            return Decision.deny("cannot promote a template from another tenant")
        return Decision.allow()
    if operation == "promote_to_builtin":
        if not principal.is_superadmin:
            return Decision.deny("promoting to builtin visibility requires superadmin")
        return Decision.allow()
    return Decision.deny(f"unknown operation {operation!r}")


# ---------------------------------------------------------------------------
# Sub-predicates
# ---------------------------------------------------------------------------


def _check_read(principal: Principal, template: ReportTemplateRecord) -> Decision:
    if template.visibility == "builtin":
        return Decision.allow()
    if template.visibility == "tenant":
        if template.tenant_id == principal.tenant_id:
            return Decision.allow()
        if principal.is_superadmin:
            return Decision.allow()
        return Decision.deny("template belongs to a different tenant")
    # private
    if template.owner_user_id == principal.user_id:
        return Decision.allow()
    if principal.is_superadmin:
        return Decision.allow()
    return Decision.deny("private template — only the owner can access")


def _check_write(principal: Principal, template: ReportTemplateRecord) -> Decision:
    """``edit_draft`` and ``publish`` share the same predicate."""
    if template.visibility == "builtin":
        if principal.is_superadmin:
            return Decision.allow()
        return Decision.deny("builtin templates are read-only outside platform admins")
    if template.visibility == "tenant":
        if template.tenant_id != principal.tenant_id and not principal.is_superadmin:
            return Decision.deny("cannot modify another tenant's template")
        if principal.is_tenant_admin or principal.is_superadmin:
            return Decision.allow()
        return Decision.deny("tenant templates require tenant_admin to modify")
    # private
    if template.owner_user_id == principal.user_id:
        return Decision.allow()
    if principal.is_superadmin:
        return Decision.allow()
    return Decision.deny("private template — only the owner can modify")


def _check_admin_or_owner(
    principal: Principal, template: ReportTemplateRecord
) -> Decision:
    """archive/delete: same as write but explicitly allow superadmin everywhere."""
    if template.visibility == "builtin":
        if principal.is_superadmin:
            return Decision.allow()
        return Decision.deny("builtin templates require superadmin for archive/delete")
    if template.visibility == "tenant":
        if template.tenant_id != principal.tenant_id and not principal.is_superadmin:
            return Decision.deny("cannot administer another tenant's template")
        if principal.is_tenant_admin or principal.is_superadmin:
            return Decision.allow()
        return Decision.deny("tenant template archive/delete requires tenant_admin")
    # private
    if template.owner_user_id == principal.user_id:
        return Decision.allow()
    if principal.is_superadmin:
        return Decision.allow()
    return Decision.deny("private template — only the owner can administer")
