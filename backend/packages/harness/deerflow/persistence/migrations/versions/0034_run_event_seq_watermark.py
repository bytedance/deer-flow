"""Persist the per-thread run-event sequence watermark."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0034_run_event_seq_watermark"
down_revision: str | Sequence[str] | None = "0033_batch_result_artifact"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "run_event_thread_seq"


def _has_table() -> bool:
    return sa.inspect(op.get_bind()).has_table(_TABLE)


def upgrade() -> None:
    if _has_table():
        return

    op.create_table(
        _TABLE,
        sa.Column("thread_id", sa.String(64), nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.PrimaryKeyConstraint("thread_id", name="pk_run_event_thread_seq"),
    )
    # Existing rows predate the durable watermark; seed it so a subsequent
    # single-run deletion cannot lower the thread's allocation floor.
    op.execute(sa.text(f"INSERT INTO {_TABLE} (thread_id, seq) SELECT thread_id, MAX(seq) FROM run_events GROUP BY thread_id"))


def downgrade() -> None:
    if _has_table():
        op.drop_table(_TABLE)
