"""Run origin, per-user thread read state and scheduled-task lifecycle events.

Revision ID: 0032_activity_and_task_events
Revises: 0031_scheduled_streak_boundary

All schema of the scheduled-signals change in one revision:

- ``runs.origin_kind`` (nullable, never backfilled: legacy runs stay NULL, the
  "interactive or unknown" value) and ``ix_runs_thread_change_seq``;
- ``thread_read_markers`` and ``thread_read_versions`` (per-user read state);
- ``scheduled_task_events`` (lifecycle events for the originating chat,
  unique on ``(task_id, anchor, event)``).

``_helpers.py`` only guards columns, so every table and index is guarded on
its own with a fresh inspector. A partially applied upgrade (for example one
table created before a crash) therefore completes on the next start, and a
downgrade can run again after an interrupted attempt.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0032_activity_and_task_events"
down_revision: str | Sequence[str] | None = "0031_scheduled_streak_boundary"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EVENT_INDEXES = (
    ("ix_scheduled_task_events_thread", ["thread_id", "created_at"]),
    ("ix_scheduled_task_events_user_id", ["user_id"]),
)


def _insp():
    return sa.inspect(op.get_bind())


def _has_table(table: str) -> bool:
    return _insp().has_table(table)


def _has_index(table: str, name: str) -> bool:
    if not _has_table(table):
        return False
    return name in {index["name"] for index in _insp().get_indexes(table)}


def upgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_add_column

    # Denormalized run origin (NULL = interactive or legacy) and the per-thread
    # change clock index used by unread checks.
    safe_add_column("runs", sa.Column("origin_kind", sa.String(32), nullable=True))
    if not _has_index("runs", "ix_runs_thread_change_seq"):
        op.create_index("ix_runs_thread_change_seq", "runs", ["thread_id", "change_seq"])

    # Per-user read markers.
    if not _has_table("thread_read_markers"):
        op.create_table(
            "thread_read_markers",
            sa.Column("user_id", sa.String(64), nullable=False),
            sa.Column("thread_id", sa.String(64), nullable=False),
            sa.Column("seen_change_seq", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("user_id", "thread_id", name="pk_thread_read_markers"),
        )
    if not _has_index("thread_read_markers", "ix_thread_read_markers_thread_id"):
        op.create_index("ix_thread_read_markers_thread_id", "thread_read_markers", ["thread_id"])

    # Per-user monotonic read clock, one row per user.
    if not _has_table("thread_read_versions"):
        op.create_table(
            "thread_read_versions",
            sa.Column("user_id", sa.String(64), nullable=False),
            sa.Column("version", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
            sa.PrimaryKeyConstraint("user_id", name="pk_thread_read_versions"),
        )

    # Durable lifecycle events for the originating chat.
    if not _has_table("scheduled_task_events"):
        op.create_table(
            "scheduled_task_events",
            sa.Column("id", sa.String(64), nullable=False),
            sa.Column("user_id", sa.String(64), nullable=False),
            sa.Column("task_id", sa.String(64), nullable=False),
            sa.Column("thread_id", sa.String(64), nullable=False),
            sa.Column("occurrence_id", sa.String(64), nullable=True),
            sa.Column("anchor", sa.String(96), nullable=False),
            sa.Column("event", sa.String(32), nullable=False),
            sa.Column("reason_code", sa.String(32), nullable=False),
            sa.Column("after_run_id", sa.String(64), nullable=True),
            sa.Column("payload_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id", name="pk_scheduled_task_events"),
            sa.UniqueConstraint("task_id", "anchor", "event", name="uq_scheduled_task_event"),
        )
    for name, columns in _EVENT_INDEXES:
        if not _has_index("scheduled_task_events", name):
            op.create_index(name, "scheduled_task_events", columns)


def downgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_drop_column

    for name, _columns in reversed(_EVENT_INDEXES):
        if _has_index("scheduled_task_events", name):
            op.drop_index(name, table_name="scheduled_task_events")
    if _has_table("scheduled_task_events"):
        op.drop_table("scheduled_task_events")
    if _has_table("thread_read_versions"):
        op.drop_table("thread_read_versions")
    if _has_index("thread_read_markers", "ix_thread_read_markers_thread_id"):
        op.drop_index("ix_thread_read_markers_thread_id", table_name="thread_read_markers")
    if _has_table("thread_read_markers"):
        op.drop_table("thread_read_markers")
    if _has_index("runs", "ix_runs_thread_change_seq"):
        op.drop_index("ix_runs_thread_change_seq", table_name="runs")
    safe_drop_column("runs", "origin_kind")
