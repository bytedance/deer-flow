"""Task state and ordered inputs, independent of agent runs."""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base


class TaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"


class CoordinationTaskRow(Base):
    __tablename__ = "coord_tasks"
    __table_args__ = (
        UniqueConstraint("owner_id", "request_id", name="uq_coord_task_request"),
        Index("ix_coord_tasks_owner_root", "owner_id", "root_id"),
        Index("ix_coord_tasks_owner_parent", "owner_id", "parent_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64))
    request_id: Mapped[str] = mapped_column(String(200))
    project_id: Mapped[str | None] = mapped_column(String(64))
    root_id: Mapped[str] = mapped_column(String(64))
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("coord_tasks.id"))
    depends_on: Mapped[list[str]] = mapped_column(JSON)
    objective: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))
    revision: Mapped[int] = mapped_column(BigInteger)
    execution_epoch: Mapped[int] = mapped_column(BigInteger)
    latest_input_seq: Mapped[int] = mapped_column(BigInteger)
    result_ref: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CoordinationInputRow(Base):
    __tablename__ = "coord_inputs"
    __table_args__ = (UniqueConstraint("task_id", "request_id", name="uq_coord_input_request"),)

    task_id: Mapped[str] = mapped_column(ForeignKey("coord_tasks.id"), primary_key=True)
    sequence: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    request_id: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
