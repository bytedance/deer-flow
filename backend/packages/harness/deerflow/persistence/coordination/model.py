"""Task state and ordered inputs, independent of agent runs."""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import JSON, BigInteger, DateTime, Double, ForeignKey, ForeignKeyConstraint, Index, LargeBinary, String, Text, UniqueConstraint
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
    run_settings: Mapped[dict[str, int | bool] | None] = mapped_column(JSON(none_as_null=True))
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


class CoordinationAssignmentRow(Base):
    """One active worker per task. Parallel work uses child tasks."""

    __tablename__ = "coord_assignments"
    task_id: Mapped[str] = mapped_column(ForeignKey("coord_tasks.id"), primary_key=True)
    epoch: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    thread_id: Mapped[str] = mapped_column(String(64), unique=True)
    assistant_id: Mapped[str] = mapped_column(String(128))


class CoordinationGrantRow(Base):
    """One current delegation per task. Reauthorization rotates its ID."""

    __tablename__ = "coord_task_grants"
    task_id: Mapped[str] = mapped_column(ForeignKey("coord_tasks.id"), primary_key=True)
    id: Mapped[str] = mapped_column(String(64))
    authority: Mapped[dict] = mapped_column(JSON)
    channel: Mapped[dict | None] = mapped_column(JSON)
    expires_at: Mapped[float] = mapped_column(Double)


class CoordinationExecutionRow(Base):
    __tablename__ = "coord_executions"
    __table_args__ = (
        ForeignKeyConstraint(["task_id", "epoch"], ["coord_assignments.task_id", "coord_assignments.epoch"]),
        UniqueConstraint("task_id", "turn", name="uq_coord_execution_turn"),
        UniqueConstraint("task_id", "resume_key", name="uq_coord_execution_resume"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(64))
    epoch: Mapped[int] = mapped_column(BigInteger)
    turn: Mapped[int] = mapped_column(BigInteger)
    resume_key: Mapped[str | None] = mapped_column(String(200))
    covered_seq: Mapped[int] = mapped_column(BigInteger)
    frozen_input: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32))
    run_id: Mapped[str | None] = mapped_column(String(64), unique=True)


class CoordinationArtifactRow(Base):
    __tablename__ = "coord_artifacts"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    execution_id: Mapped[str] = mapped_column(ForeignKey("coord_executions.id"), index=True)
    path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(BigInteger)
    content: Mapped[bytes] = mapped_column(LargeBinary)
