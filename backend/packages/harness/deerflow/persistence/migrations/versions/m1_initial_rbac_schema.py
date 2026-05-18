"""Initial enterprise RBAC schema.

- Adds ``users.roles`` (TEXT, JSON-encoded list, default ``"[]"``).
- Creates the ``roles`` and ``role_permissions`` tables.
- Seeds ``DEFAULT_ROLE_PERMISSIONS`` so a fresh database is usable on
  first boot.
- Migrates existing ``users.system_role`` data into ``users.roles``
  idempotently — only rows whose ``roles`` is still NULL or ``'[]'`` are
  rewritten so re-running the migration after an operator manually
  populates ``roles`` does not clobber their work (plan §9.4 idempotency
  requirement).

Schema changes that touch existing tables (``users.roles``) go through
``op.batch_alter_table`` so SQLite — which lacks in-place
``ALTER TABLE`` support — works without manual table-rebuild
boilerplate. PostgreSQL handles the same syntax via Alembic's pass-
through.

Revision ID: m1_initial_rbac
Revises:
Create Date: 2026-05-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# Alembic identifiers --------------------------------------------------

revision = "m1_initial_rbac"
down_revision = None
branch_labels = None
depends_on = None


# Built-in role / permission seed data. Kept inline (not imported from
# ``deerflow.enterprise.rbac.models``) because Alembic migrations must
# remain stable even if the source-of-truth enums are later renamed —
# the migration captures the schema state of THIS release.

_DEFAULT_ROLES: list[tuple[str, str, str | None]] = [
    ("admin", "admin", "Full system access including user/role management"),
    ("project_manager", "project_manager", "Manage projects, agents, approvals"),
    ("member", "member", "Standard contributor"),
    ("viewer", "viewer", "Read-only access"),
]

_DEFAULT_ROLE_PERMISSIONS: dict[str, list[str]] = {
    "admin": [
        "agent:create",
        "agent:delete",
        "agent:view",
        "agent:execute",
        "thread:create",
        "thread:read",
        "thread:write",
        "thread:delete",
        "approval:create",
        "approval:grant",
        "approval:reject",
        "approval:view",
        "data:read",
        "data:write",
        "data:delete",
        "data:export",
        "user:manage",
        "role:manage",
        "system:settings",
    ],
    "project_manager": [
        "agent:create",
        "agent:view",
        "agent:execute",
        "thread:create",
        "thread:read",
        "thread:write",
        "approval:create",
        "approval:grant",
        "approval:reject",
        "approval:view",
        "data:read",
        "data:write",
    ],
    "member": [
        "agent:view",
        "agent:execute",
        "thread:create",
        "thread:read",
        "thread:write",
        "approval:view",
        "data:read",
        "data:write",
    ],
    "viewer": [
        "agent:view",
        "thread:read",
        "data:read",
        "approval:view",
    ],
}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # 1) Add users.roles column (idempotent: only when missing). The
    #    ``users`` table itself is created by an earlier deerflow-core
    #    migration; we extend it here.
    user_columns = {c["name"] for c in inspector.get_columns("users")} if "users" in inspector.get_table_names() else set()
    if "users" in inspector.get_table_names() and "roles" not in user_columns:
        with op.batch_alter_table("users", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "roles",
                    sa.Text(),
                    nullable=False,
                    server_default="[]",
                )
            )

    # 2) Create roles table.
    if "roles" not in inspector.get_table_names():
        op.create_table(
            "roles",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("name", sa.String(length=128), nullable=False, unique=True),
            sa.Column("description", sa.String(length=512), nullable=True),
            sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        )

    # 3) Create role_permissions table.
    if "role_permissions" not in inspector.get_table_names():
        op.create_table(
            "role_permissions",
            sa.Column(
                "role_id",
                sa.String(length=64),
                sa.ForeignKey("roles.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("permission", sa.String(length=64), primary_key=True),
            sa.Column("granted_by", sa.String(length=64), nullable=True),
        )

    # 4) Seed built-in roles / role_permissions. Use plain INSERTs; on a
    #    re-run we skip rows that already exist by checking with a WHERE
    #    NOT EXISTS subquery — Alembic does not give us a portable
    #    ON CONFLICT, so we fall back to "delete then insert" only for
    #    rows that match the default seed (so operator overrides
    #    survive).
    roles_table = sa.table(
        "roles",
        sa.column("id", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.String),
        sa.column("is_default", sa.Boolean),
    )
    role_permissions_table = sa.table(
        "role_permissions",
        sa.column("role_id", sa.String),
        sa.column("permission", sa.String),
        sa.column("granted_by", sa.String),
    )

    existing_role_ids = {r[0] for r in bind.execute(sa.select(roles_table.c.id)).all()}
    new_roles = [{"id": rid, "name": name, "description": desc, "is_default": True} for (rid, name, desc) in _DEFAULT_ROLES if rid not in existing_role_ids]
    if new_roles:
        op.bulk_insert(roles_table, new_roles)

    existing_permission_pairs = {(r[0], r[1]) for r in bind.execute(sa.select(role_permissions_table.c.role_id, role_permissions_table.c.permission)).all()}
    new_permissions: list[dict[str, str]] = []
    for role_id, perms in _DEFAULT_ROLE_PERMISSIONS.items():
        for perm in perms:
            if (role_id, perm) in existing_permission_pairs:
                continue
            new_permissions.append({"role_id": role_id, "permission": perm, "granted_by": "system:default"})
    if new_permissions:
        op.bulk_insert(role_permissions_table, new_permissions)

    # 5) Data migration for existing users:
    #    system_role='admin' -> roles='["admin"]'
    #    system_role='user'  -> roles='["member"]'
    #    Idempotent guard via WHERE roles IS NULL OR roles='[]' so a
    #    re-run never overwrites operator edits (plan §3.4 risk
    #    register).
    if "users" in inspector.get_table_names():
        op.execute("UPDATE users SET roles='[\"admin\"]' WHERE system_role='admin' AND (roles IS NULL OR roles='[]')")
        op.execute("UPDATE users SET roles='[\"member\"]' WHERE system_role='user' AND (roles IS NULL OR roles='[]')")


def downgrade() -> None:
    """Drop the RBAC tables and the ``users.roles`` column.

    Data migration is intentionally one-way: rolling back drops the
    ``roles`` column entirely. Operators relying on RBAC should NOT use
    ``alembic downgrade`` against a populated database — use
    ``scripts/migrate_enterprise.py --rollback`` (planned in M5) which
    preserves an audit trail. We keep this function correct so the
    automated round-trip test in M5-3b can run on a fresh fixture.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "role_permissions" in inspector.get_table_names():
        op.drop_table("role_permissions")
    if "roles" in inspector.get_table_names():
        op.drop_table("roles")

    if "users" in inspector.get_table_names():
        user_columns = {c["name"] for c in inspector.get_columns("users")}
        if "roles" in user_columns:
            with op.batch_alter_table("users", schema=None) as batch_op:
                batch_op.drop_column("roles")
