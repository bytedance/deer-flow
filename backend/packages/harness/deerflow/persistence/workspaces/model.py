"""Native tenant control-plane models; no parallel task or Agent authority."""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import JSON, BigInteger, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base


class WorkspaceRow(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(36), nullable=False, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    personal_user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    policy_version: Mapped[int] = mapped_column(Integer(), nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    purge_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("personal_user_id", name="uq_workspace_personal_user"),
        CheckConstraint("kind IN ('personal', 'team')", name="ck_workspace_kind"),
        CheckConstraint("(kind = 'personal' AND personal_user_id IS NOT NULL) OR (kind = 'team' AND personal_user_id IS NULL)", name="ck_workspace_personal_identity"),
        CheckConstraint("policy_version >= 1", name="ck_workspace_policy_version"),
    )


class WorkspaceMembershipRow(Base):
    __tablename__ = "workspace_memberships"

    workspace_id: Mapped[str] = mapped_column(String(36), ForeignKey("workspaces.id"), nullable=False, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, primary_key=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    version: Mapped[int] = mapped_column(Integer(), nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))

    __table_args__ = (
        CheckConstraint("role IN ('owner', 'admin', 'member')", name="ck_workspace_member_role"),
        CheckConstraint("status IN ('active', 'removed')", name="ck_workspace_member_status"),
        CheckConstraint("version >= 1", name="ck_workspace_member_version"),
        Index("ix_workspace_memberships_user", "user_id", "status"),
        Index("uq_workspace_active_owner", "workspace_id", unique=True, sqlite_where=text("role = 'owner' AND status = 'active'"), postgresql_where=text("role = 'owner' AND status = 'active'")),
    )


class WorkspaceInvitationRow(Base):
    __tablename__ = "workspace_invitations"

    id: Mapped[str] = mapped_column(String(36), nullable=False, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(36), ForeignKey("workspaces.id"), nullable=False)
    email_canonical: Mapped[str] = mapped_column(String(320), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    inviter_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))

    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_workspace_invitation_token"),
        CheckConstraint("role IN ('admin', 'member')", name="ck_workspace_invitation_role"),
        Index("ix_workspace_invitation_email", "workspace_id", "email_canonical"),
    )


class AuthActionTokenRow(Base):
    __tablename__ = "auth_action_tokens"

    id: Mapped[str] = mapped_column(String(36), nullable=False, primary_key=True)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))

    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_auth_action_token_hash"),
        CheckConstraint("purpose IN ('verify_email', 'reset_password')", name="ck_auth_action_token_purpose"),
        Index("ix_auth_action_tokens_subject", "user_id", "purpose"),
    )


class WorkspaceConnectionRow(Base):
    __tablename__ = "workspace_connections"

    id: Mapped[str] = mapped_column(String(36), nullable=False, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(36), ForeignKey("workspaces.id"), nullable=False)
    owner_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    encrypted_secret_ref: Mapped[str | None] = mapped_column(Text(), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    version: Mapped[int] = mapped_column(Integer(), nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))

    __table_args__ = (Index("ix_workspace_connections_scope", "workspace_id", "owner_user_id"),)


class WorkspaceKnowledgeBindingRow(Base):
    __tablename__ = "workspace_knowledge_bindings"

    id: Mapped[str] = mapped_column(String(36), nullable=False, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(36), ForeignKey("workspaces.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    dataset_id: Mapped[str] = mapped_column(String(255), nullable=False)
    visibility: Mapped[str] = mapped_column(String(16), nullable=False)
    connection_id: Mapped[str] = mapped_column(String(36), ForeignKey("workspace_connections.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")

    __table_args__ = (
        UniqueConstraint("workspace_id", "provider", "dataset_id", "visibility", name="uq_workspace_knowledge_binding"),
        CheckConstraint("visibility IN ('private', 'workspace')", name="ck_workspace_knowledge_visibility"),
        Index("ix_workspace_knowledge_scope", "workspace_id", "status"),
    )


class WorkspaceQuotaRow(Base):
    __tablename__ = "workspace_quotas"

    workspace_id: Mapped[str] = mapped_column(String(36), ForeignKey("workspaces.id"), nullable=False, primary_key=True)
    max_concurrent_runs: Mapped[int] = mapped_column(Integer(), nullable=False, default=2)
    max_daily_runs: Mapped[int] = mapped_column(Integer(), nullable=False, default=50)
    max_storage_bytes: Mapped[int] = mapped_column(BigInteger(), nullable=False, default=1073741824)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))

    __table_args__ = (CheckConstraint("max_concurrent_runs >= 0 AND max_daily_runs >= 0 AND max_storage_bytes >= 0", name="ck_workspace_quotas_nonnegative"),)


class WorkspaceUsageRow(Base):
    __tablename__ = "workspace_usage"

    event_id: Mapped[str] = mapped_column(String(128), nullable=False, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(36), ForeignKey("workspaces.id"), nullable=False)
    actor_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    metric: Mapped[str] = mapped_column(String(32), nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger(), nullable=False)
    bucket_date: Mapped[date] = mapped_column(Date(), nullable=False)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="consumed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))

    __table_args__ = (
        CheckConstraint("amount >= 0", name="ck_workspace_usage_amount"),
        Index("ix_workspace_usage_bucket", "workspace_id", "metric", "bucket_date"),
    )


class WorkspaceAuditEventRow(Base):
    __tablename__ = "workspace_audit_events"

    id: Mapped[str] = mapped_column(String(36), nullable=False, primary_key=True)
    workspace_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("workspaces.id"), nullable=True)
    actor_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))

    __table_args__ = (Index("ix_workspace_audit_time", "workspace_id", "created_at"),)


class WorkspaceOperationOutboxRow(Base):
    __tablename__ = "workspace_operation_outbox"

    operation_id: Mapped[str] = mapped_column(String(64), nullable=False, primary_key=True)
    workspace_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("workspaces.id"), nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    payload_ciphertext: Mapped[str | None] = mapped_column(Text(), nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSON(), nullable=True)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt: Mapped[int] = mapped_column(Integer(), nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))

    __table_args__ = (Index("ix_workspace_outbox_pending", "state", "lease_expires_at"),)
