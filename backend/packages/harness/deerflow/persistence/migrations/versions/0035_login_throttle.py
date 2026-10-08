"""Shared failed-login counter for cross-replica lockouts.

Revision ID: 0035_login_throttle
Revises: 0034_run_event_seq_watermark

Creates ``login_throttle``: one row per client IP that failed a local login,
keyed by ``ip``, with the consecutive failure count, the epoch timestamp the
lock started (NULL while only counting), the sentence committed for that lock
and ``updated_at``. Every Gateway replica sharing the application database
reads and writes the same row (``auth.local.throttle_storage``), replacing the
per-process dict that gave an attacker N x ``max_login_attempts`` guesses
behind a load balancer.

``_helpers.py`` only guards columns, so the table is guarded with a fresh
inspector in both directions: an upgrade that finds the table (an interrupted
earlier attempt, or an empty-database bootstrap that already ran
``create_all``) completes, and a downgrade after the table is gone still
moves the version row.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0035_login_throttle"
down_revision: str | Sequence[str] | None = "0034_run_event_seq_watermark"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "login_throttle"
_INDEX = "ix_login_throttle_updated_at"


def _has_table() -> bool:
    return sa.inspect(op.get_bind()).has_table(_TABLE)


def _has_index() -> bool:
    if not _has_table():
        return False
    return _INDEX in {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(_TABLE)}


def upgrade() -> None:
    if not _has_table():
        op.create_table(
            _TABLE,
            sa.Column("ip", sa.String(length=255), nullable=False),
            sa.Column("fail_count", sa.Integer(), nullable=False),
            sa.Column("locked_at", sa.Double(), nullable=True),
            sa.Column("lock_duration_seconds", sa.Double(), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("ip", name="pk_login_throttle"),
        )
    # Serves the sweep's stale-counter predicate; guarded separately so a
    # table left behind by an interrupted attempt still gets its index.
    if not _has_index():
        op.create_index(_INDEX, _TABLE, ["updated_at"])


def downgrade() -> None:
    if _has_index():
        op.drop_index(_INDEX, table_name=_TABLE)
    if _has_table():
        op.drop_table(_TABLE)
