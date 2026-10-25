"""Per-provider IM transport leader lease.

Revision ID: 0042_channel_leases
Revises: 0041_im_notice_preferences

Creates ``channel_leases``: one row per IM provider naming the Gateway
instance that holds its platform connection (``owner_id``), a fencing
``epoch`` bumped on every acquisition, the database-clock epoch seconds the
lease expires at, whether the holder's transport was running at its last
renewal, and ``updated_at``. Only instances with ``channels.leader_lease``
active write it; a single-instance deployment leaves it empty.

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

revision: str = "0042_channel_leases"
down_revision: str | Sequence[str] | None = "0041_im_notice_preferences"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "channel_leases"


def _has_table() -> bool:
    return sa.inspect(op.get_bind()).has_table(_TABLE)


def upgrade() -> None:
    if _has_table():
        return
    op.create_table(
        _TABLE,
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("owner_id", sa.String(length=128), nullable=False),
        sa.Column("epoch", sa.BigInteger(), nullable=False),
        sa.Column("lease_expires_at", sa.Double(), nullable=False),
        sa.Column("transport_running", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.Double(), nullable=False),
        sa.PrimaryKeyConstraint("provider", name="pk_channel_leases"),
    )


def downgrade() -> None:
    if _has_table():
        op.drop_table(_TABLE)
