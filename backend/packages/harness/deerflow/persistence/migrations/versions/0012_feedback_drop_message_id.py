"""Drop the unused feedback.message_id column.

Feedback is bound to a run, not to a single message: nothing ever wrote or
read ``message_id`` (no API field, no frontend usage, no query), so the
column is redundant design and the domain aggregate no longer carries it.

Revision ID: 0012_feedback_drop_message_id
Revises: 0011_feedback_tags
Create Date: 2026-07-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from deerflow.persistence.migrations._helpers import safe_add_column, safe_drop_column

revision: str = "0012_feedback_drop_message_id"
down_revision: str | Sequence[str] | None = "0011_feedback_tags"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Idempotent: a DB provisioned by create_all from the new metadata never
    # had the column, and a retried upgrade must not fail on the second run.
    safe_drop_column("feedback", "message_id")


def downgrade() -> None:
    safe_add_column("feedback", sa.Column("message_id", sa.String(64), nullable=True))
