"""Account disabled flag on ``users``.

Revision ID: 0036_user_disabled
Revises: 0035_login_throttle

Adds ``users.disabled`` (NOT NULL, server default ``0``): an
operator-disabled account is rejected at every authentication surface while
the row — credentials, role, OAuth linkage — is retained, so re-enabling
restores exactly what was suspended (RFC #4063 / issue #3462 gap 3).

Column-guarded in both directions: an upgrade over a database that already
has the column (an interrupted earlier attempt, or an empty-database
bootstrap whose ``create_all`` saw the model first) completes, and a
downgrade after the column is gone still moves the version row.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0038_user_disabled"
down_revision: str | None = "0037_project_document_summaries"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "users"
_COLUMN = "disabled"


def _has_column() -> bool:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(_TABLE):
        return False
    return _COLUMN in {column["name"] for column in sa.inspect(bind).get_columns(_TABLE)}


def upgrade() -> None:
    if not _has_column():
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    if _has_column():
        op.drop_column(_TABLE, _COLUMN)
