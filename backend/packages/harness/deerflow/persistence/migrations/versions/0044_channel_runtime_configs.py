"""Shared, encrypted IM channel runtime configuration.

Revision ID: 0044_channel_runtime_configs
Revises: 0043_runtime_im_notices

Creates ``channel_runtime_configs``: one row per IM provider holding the
credentials an admin entered in the web UI, as ``DEER_FLOW_CREDENTIALS_KEY``
ciphertext of the provider's JSON config block (NULL for a disconnect), a
plaintext ``disconnected`` tombstone flag, a ``version`` bumped on every save
so peers notice changes, and ``updated_at``. It succeeds the per-host
``{base_dir}/channels/runtime-config.json``, which the Gateway imports once
and deletes (``app.channels.runtime_config_store``); this revision moves no
data, so a database without IM channels gets an empty table.

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

revision: str = "0044_channel_runtime_configs"
down_revision: str | Sequence[str] | None = "0043_runtime_im_notices"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "channel_runtime_configs"


def _has_table() -> bool:
    return sa.inspect(op.get_bind()).has_table(_TABLE)


def upgrade() -> None:
    if _has_table():
        return
    op.create_table(
        _TABLE,
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("config_ciphertext", sa.Text(), nullable=True),
        sa.Column("disconnected", sa.Boolean(), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.Double(), nullable=False),
        sa.PrimaryKeyConstraint("provider", name="pk_channel_runtime_configs"),
    )


def downgrade() -> None:
    if _has_table():
        op.drop_table(_TABLE)
