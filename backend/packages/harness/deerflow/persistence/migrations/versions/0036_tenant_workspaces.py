"""Add tenant metadata and nullable resource scope without guessing ownership."""

import sqlalchemy as sa
from alembic import op

revision = "0036_tenant_workspaces"
down_revision = "0035_native_fork_compatibility"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "workspaces",
        sa.Column("id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("personal_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("purge_after", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("personal_user_id", name="uq_workspace_personal_user"),
        sa.CheckConstraint("kind IN ('personal', 'team')", name="ck_workspace_kind"),
        sa.CheckConstraint("(kind = 'personal' AND personal_user_id IS NOT NULL) OR (kind = 'team' AND personal_user_id IS NULL)", name="ck_workspace_personal_identity"),
        sa.CheckConstraint("policy_version >= 1", name="ck_workspace_policy_version"),
    )
    op.create_table(
        "workspace_memberships",
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False, primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False, primary_key=True),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("role IN ('owner', 'admin', 'member')", name="ck_workspace_member_role"),
        sa.CheckConstraint("status IN ('active', 'removed')", name="ck_workspace_member_status"),
        sa.CheckConstraint("version >= 1", name="ck_workspace_member_version"),
    )
    op.create_index("ix_workspace_memberships_user", "workspace_memberships", ["user_id", "status"])
    op.create_index("uq_workspace_active_owner", "workspace_memberships", ["workspace_id"], unique=True, sqlite_where=sa.text("role = 'owner' AND status = 'active'"), postgresql_where=sa.text("role = 'owner' AND status = 'active'"))
    op.create_table(
        "workspace_invitations",
        sa.Column("id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("email_canonical", sa.String(320), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("inviter_user_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("token_hash", name="uq_workspace_invitation_token"),
        sa.CheckConstraint("role IN ('admin', 'member')", name="ck_workspace_invitation_role"),
    )
    op.create_index("ix_workspace_invitation_email", "workspace_invitations", ["workspace_id", "email_canonical"])
    op.create_table(
        "auth_action_tokens",
        sa.Column("id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("purpose", sa.String(32), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("token_hash", name="uq_auth_action_token_hash"),
        sa.CheckConstraint("purpose IN ('verify_email', 'reset_password')", name="ck_auth_action_token_purpose"),
    )
    op.create_index("ix_auth_action_tokens_subject", "auth_action_tokens", ["user_id", "purpose"])
    op.create_table(
        "workspace_connections",
        sa.Column("id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("owner_user_id", sa.String(36), nullable=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("encrypted_secret_ref", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_workspace_connections_scope", "workspace_connections", ["workspace_id", "owner_user_id"])
    op.create_table(
        "workspace_knowledge_bindings",
        sa.Column("id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("dataset_id", sa.String(255), nullable=False),
        sa.Column("visibility", sa.String(16), nullable=False),
        sa.Column("connection_id", sa.String(36), sa.ForeignKey("workspace_connections.id"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.UniqueConstraint("workspace_id", "provider", "dataset_id", "visibility", name="uq_workspace_knowledge_binding"),
        sa.CheckConstraint("visibility IN ('private', 'workspace')", name="ck_workspace_knowledge_visibility"),
    )
    op.create_index("ix_workspace_knowledge_scope", "workspace_knowledge_bindings", ["workspace_id", "status"])
    op.create_table(
        "workspace_quotas",
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False, primary_key=True),
        sa.Column("max_concurrent_runs", sa.Integer(), nullable=False),
        sa.Column("max_daily_runs", sa.Integer(), nullable=False),
        sa.Column("max_storage_bytes", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("max_concurrent_runs >= 0 AND max_daily_runs >= 0 AND max_storage_bytes >= 0", name="ck_workspace_quotas_nonnegative"),
    )
    op.create_table(
        "workspace_usage",
        sa.Column("event_id", sa.String(128), nullable=False, primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("actor_user_id", sa.String(36), nullable=False),
        sa.Column("metric", sa.String(32), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("bucket_date", sa.Date(), nullable=False),
        sa.Column("run_id", sa.String(64), nullable=True),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount >= 0", name="ck_workspace_usage_amount"),
    )
    op.create_index("ix_workspace_usage_bucket", "workspace_usage", ["workspace_id", "metric", "bucket_date"])
    op.create_table(
        "workspace_audit_events",
        sa.Column("id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=True),
        sa.Column("actor_user_id", sa.String(36), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.String(128), nullable=True),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_workspace_audit_time", "workspace_audit_events", ["workspace_id", "created_at"])
    op.create_table(
        "workspace_operation_outbox",
        sa.Column("operation_id", sa.String(64), nullable=False, primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=True),
        sa.Column("user_id", sa.String(36), nullable=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("payload_ciphertext", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("lease_owner", sa.String(128), nullable=True),
        sa.Column("lease_token", sa.String(64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_workspace_outbox_pending", "workspace_operation_outbox", ["state", "lease_expires_at"])
    op.add_column("users", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("account_status", sa.String(16), nullable=False, server_default="active"))
    op.add_column("threads_meta", sa.Column("workspace_id", sa.String(36), nullable=True))
    op.create_index("ix_threads_meta_workspace_id", "threads_meta", ["workspace_id"])
    op.add_column("runs", sa.Column("workspace_id", sa.String(36), nullable=True))
    op.create_index("ix_runs_workspace_id", "runs", ["workspace_id"])
    op.add_column("projects", sa.Column("workspace_id", sa.String(36), nullable=True))
    op.create_index("ix_projects_workspace_id", "projects", ["workspace_id"])
    op.add_column("project_documents", sa.Column("workspace_id", sa.String(36), nullable=True))
    op.create_index("ix_project_documents_workspace_id", "project_documents", ["workspace_id"])
    op.add_column("mcp_tasks", sa.Column("workspace_id", sa.String(36), nullable=True))
    op.create_index("ix_mcp_tasks_workspace_id", "mcp_tasks", ["workspace_id"])
    op.add_column("scheduled_tasks", sa.Column("workspace_id", sa.String(36), nullable=True))
    op.create_index("ix_scheduled_tasks_workspace_id", "scheduled_tasks", ["workspace_id"])
    op.add_column("scheduled_task_runs", sa.Column("workspace_id", sa.String(36), nullable=True))
    op.create_index("ix_scheduled_task_runs_workspace_id", "scheduled_task_runs", ["workspace_id"])
    op.add_column("scheduled_task_events", sa.Column("workspace_id", sa.String(36), nullable=True))
    op.create_index("ix_scheduled_task_events_workspace_id", "scheduled_task_events", ["workspace_id"])
    op.add_column("run_events", sa.Column("workspace_id", sa.String(36), nullable=True))
    op.create_index("ix_run_events_workspace_id", "run_events", ["workspace_id"])


def downgrade():
    raise RuntimeError("Tenant rollback requires drained execution and a coherent two-database/file backup; ownership cannot be dropped")
