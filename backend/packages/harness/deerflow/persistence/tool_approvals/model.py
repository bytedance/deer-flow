"""Durable approvals; thread incarnation prevents reuse after deletion/recreation."""

from sqlalchemy import JSON, Double, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base


class ToolApprovalRow(Base):
    __tablename__ = "tool_approvals"
    __table_args__ = (
        Index("ix_tool_approvals_scope", "user_id", "thread_id", "incarnation", "fingerprint"),
        Index("ix_tool_approvals_run", "run_id", "status"),
    )

    request_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False)
    incarnation: Mapped[str] = mapped_column(String(64), nullable=False)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    decision: Mapped[str | None] = mapped_column(String(24))
    payload: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False)
    response: Mapped[dict | None] = mapped_column(JSON().with_variant(JSONB, "postgresql"))
    created_at: Mapped[float] = mapped_column(Double, nullable=False)
    expires_at: Mapped[float | None] = mapped_column(Double)
