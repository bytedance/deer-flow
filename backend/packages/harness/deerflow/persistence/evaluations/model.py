from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base

EVAL_RUN_STATUS_QUEUED = "queued"
EVAL_RUN_STATUS_RUNNING = "running"
EVAL_RUN_STATUS_COMPLETED = "completed"
EVAL_RUN_STATUS_FAILED = "failed"
EVAL_RUN_STATUS_CANCELLED = "cancelled"

EVAL_ITEM_STATUS_QUEUED = "queued"
EVAL_ITEM_STATUS_RUNNING = "running"
EVAL_ITEM_STATUS_PASSED = "passed"
EVAL_ITEM_STATUS_FAILED = "failed"
EVAL_ITEM_STATUS_ERROR = "error"
EVAL_ITEM_STATUS_SKIPPED = "skipped"
EVAL_ITEM_STATUS_CANCELLED = "cancelled"

EVAL_ATTEMPT_STATUS_QUEUED = "queued"
EVAL_ATTEMPT_STATUS_RUNNING = "running"
EVAL_ATTEMPT_STATUS_SUCCESS = "success"
EVAL_ATTEMPT_STATUS_FAILED = "failed"
EVAL_ATTEMPT_STATUS_ERROR = "error"
EVAL_ATTEMPT_STATUS_CANCELLED = "cancelled"

EVAL_RUN_TERMINAL_STATUSES: frozenset[str] = frozenset(
    {
        EVAL_RUN_STATUS_COMPLETED,
        EVAL_RUN_STATUS_FAILED,
        EVAL_RUN_STATUS_CANCELLED,
    }
)
EVAL_ITEM_TERMINAL_STATUSES: frozenset[str] = frozenset(
    {
        EVAL_ITEM_STATUS_PASSED,
        EVAL_ITEM_STATUS_FAILED,
        EVAL_ITEM_STATUS_ERROR,
        EVAL_ITEM_STATUS_SKIPPED,
        EVAL_ITEM_STATUS_CANCELLED,
    }
)
EVAL_ATTEMPT_TERMINAL_STATUSES: frozenset[str] = frozenset(
    {
        EVAL_ATTEMPT_STATUS_SUCCESS,
        EVAL_ATTEMPT_STATUS_FAILED,
        EVAL_ATTEMPT_STATUS_ERROR,
        EVAL_ATTEMPT_STATUS_CANCELLED,
    }
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class EvalRunRow(Base):
    __tablename__ = "eval_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)

    suite_name: Mapped[str] = mapped_column(String(255), nullable=False)
    suite_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    suite_digest: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    suite_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    environment_fingerprint_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    config_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    variants_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default=EVAL_RUN_STATUS_QUEUED, index=True)
    total_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    summary_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    effect_summary_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    comparison_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    report_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    report_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)

    infrastructure_gate: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    trace_export: Mapped[str] = mapped_column(String(32), nullable=False, default="disabled")
    trace_sync_status: Mapped[str] = mapped_column(String(20), nullable=False, default="disabled")

    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now, onupdate=_utc_now)

    __table_args__ = (
        UniqueConstraint("owner_id", "idempotency_key", name="uq_eval_runs_owner_idempotency_key"),
        Index("idx_eval_runs_claim", "status", "lease_expires_at", "created_at"),
    )


class EvalRunItemRow(Base):
    __tablename__ = "eval_run_items"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    eval_run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("eval_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    suite_item_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    variant_id: Mapped[str] = mapped_column(String(128), nullable=False, default="default", index=True)
    sample_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    execution_key: Mapped[str] = mapped_column(String(512), nullable=False)
    paired_item_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default=EVAL_ITEM_STATUS_QUEUED, index=True)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    selected_attempt_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    selected_attempt_index: Mapped[int | None] = mapped_column(Integer, nullable=True)

    thread_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    workspace_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    checks_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    check_results_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    metrics_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    comparison_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    run_event_summary_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    failure_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    trace_sync_status: Mapped[str] = mapped_column(String(20), nullable=False, default="disabled")
    langsmith_dataset_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    langsmith_example_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    langsmith_trace_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now, onupdate=_utc_now)

    __table_args__ = (
        UniqueConstraint(
            "eval_run_id",
            "suite_item_id",
            "variant_id",
            "sample_index",
            name="uq_eval_items_run_suite_variant_sample",
        ),
        UniqueConstraint("eval_run_id", "execution_key", name="uq_eval_items_run_execution_key"),
        Index("idx_eval_items_run_status", "eval_run_id", "status"),
    )


class EvalItemAttemptRow(Base):
    __tablename__ = "eval_item_attempts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    eval_run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("eval_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    eval_run_item_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("eval_run_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    attempt_index: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=EVAL_ATTEMPT_STATUS_QUEUED, index=True)

    thread_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    workspace_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    checks_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    check_results_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    metrics_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    comparison_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    run_event_summary_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    failure_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    trace_sync_status: Mapped[str] = mapped_column(String(20), nullable=False, default="disabled")
    langsmith_trace_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now, onupdate=_utc_now)

    __table_args__ = (
        UniqueConstraint("eval_run_item_id", "attempt_index", name="uq_eval_attempts_item_attempt_index"),
        Index("idx_eval_attempts_item_status", "eval_run_item_id", "status"),
    )
