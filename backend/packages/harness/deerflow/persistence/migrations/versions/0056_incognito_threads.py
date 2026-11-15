"""Add incognito markers to ``threads_meta``.

``incognito`` marks a thread that must never surface in a thread list, search
result, project, archive view or share. ``expires_at`` is the deadline the
incognito lifetime sweep compares against the database clock.

Both columns are nullable with no server default: a binary sharing the database
during a rolling upgrade keeps inserting and reading rows, and NULL reads as
"not incognito". The composite index backs the sweep's
``incognito = true AND expires_at <= now`` predicate.
"""

import sqlalchemy as sa
from alembic import op

revision = "0056_incognito_threads"
down_revision = "0055_thread_shares"
branch_labels = None
depends_on = None

_TABLE = "threads_meta"
_INDEX = "ix_threads_meta_incognito_expires_at"


def _has_index() -> bool:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in inspector.get_table_names():
        return False
    return _INDEX in {index["name"] for index in inspector.get_indexes(_TABLE)}


def upgrade():
    from deerflow.persistence.migrations._helpers import safe_add_column

    safe_add_column(_TABLE, sa.Column("incognito", sa.Boolean(), nullable=True))
    safe_add_column(_TABLE, sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    if not _has_index():
        op.create_index(_INDEX, _TABLE, ["incognito", "expires_at"])


def downgrade():
    from deerflow.persistence.migrations._helpers import safe_drop_column

    if _has_index():
        op.drop_index(_INDEX, table_name=_TABLE)
    safe_drop_column(_TABLE, "expires_at")
    safe_drop_column(_TABLE, "incognito")
