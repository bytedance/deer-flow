"""Host-owned skill version and publication records (Alembic managed)."""

from __future__ import annotations

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, LargeBinary, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base


class SkillOwnerRow(Base):
    __tablename__ = "skill_mutation_owners"
    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    generation: Mapped[int] = mapped_column(Integer, default=0)
    deleting: Mapped[bool] = mapped_column(Boolean, default=False)


class SkillAssetRow(Base):
    __tablename__ = "skill_mutation_assets"
    target_ref: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    incarnation_id: Mapped[str] = mapped_column(String(32))
    mutation_seq: Mapped[int] = mapped_column(Integer)
    content_digest: Mapped[str] = mapped_column(String(64))
    enabled: Mapped[bool] = mapped_column(Boolean)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    mutating: Mapped[bool] = mapped_column(Boolean, default=False)
    operation_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_skill_asset_owner_name"),)


class SkillProposalRow(Base):
    __tablename__ = "skill_mutation_proposals"
    proposal_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    plugin_id: Mapped[str] = mapped_column(String(128))
    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    target_ref: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(64))
    base_revision: Mapped[dict] = mapped_column(JSON)
    sources: Mapped[list] = mapped_column(JSON)
    candidate_hash: Mapped[str] = mapped_column(String(64))
    package_blob: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True, deferred=True)
    candidate_blob: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True, deferred=True)
    state: Mapped[str] = mapped_column(String(16))
    expires_at: Mapped[float]
    check_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    operation_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    __table_args__ = (UniqueConstraint("plugin_id", "idempotency_key", name="uq_skill_proposal_key"),)


class SkillOperationRow(Base):
    __tablename__ = "skill_mutation_operations"
    operation_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    plugin_id: Mapped[str] = mapped_column(String(128))
    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    target_ref: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(64))
    method: Mapped[str] = mapped_column(String(16))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    proposal_id: Mapped[str | None] = mapped_column(String(32), nullable=True, unique=True)
    reverts_operation_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    before_operation_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    before_revision: Mapped[dict] = mapped_column(JSON)
    after_revision: Mapped[dict] = mapped_column(JSON)
    before_blob: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True, deferred=True)
    after_blob: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True, deferred=True)
    generation: Mapped[int] = mapped_column(Integer)
    publication: Mapped[str] = mapped_column(String(16), index=True)
    views: Mapped[str] = mapped_column(String(16))
    superseded_by_generation: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[float]
    rollback_expires_at: Mapped[float]
    assessment: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    __table_args__ = (UniqueConstraint("plugin_id", "method", "idempotency_key", name="uq_skill_operation_key"),)


class SkillScanAttemptRow(Base):
    __tablename__ = "skill_mutation_scan_attempts"
    token: Mapped[str] = mapped_column(String(32), primary_key=True)
    plugin_id: Mapped[str] = mapped_column(String(128), index=True)
    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    subject: Mapped[str] = mapped_column(String(80))
    started_at: Mapped[float]
    lease_until: Mapped[float]
