"""Add ``runs.model_failure_ledger`` JSON column.

A compact, structured per-run ledger of model failures (retries, circuit
transitions, model fallback outcomes) surfaced read-only for SRE provider
health attribution. Nullable with no server default so a binary from before
this change can keep writing ``runs`` rows during a rolling upgrade.
"""

from __future__ import annotations

import sqlalchemy as sa

from deerflow.persistence.migrations._helpers import safe_add_column, safe_drop_column

# revision identifiers, used by Alembic.
revision: str = "0064_model_failure_ledger"
down_revision: str | None = "0063_scheduled_task_subagents"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    safe_add_column(
        "runs",
        sa.Column("model_failure_ledger", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    safe_drop_column("runs", "model_failure_ledger")
