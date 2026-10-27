"""Store private run idempotency request identities outside public kwargs."""

from __future__ import annotations

import sqlalchemy as sa

revision = "0036_run_idempotency_request"
down_revision = "0035_login_throttle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_add_column

    safe_add_column("runs", sa.Column("idempotency_request_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_drop_column

    safe_drop_column("runs", "idempotency_request_json")
