"""Backfill eval run environment fingerprint column.

Revision ID: 0006_eval_run_environment_fingerprint
Revises: 0005_evaluations
Create Date: 2026-07-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from deerflow.persistence.migrations._helpers import safe_add_column

revision: str = "0006_eval_run_environment_fingerprint"
down_revision: str | Sequence[str] | None = "0005_evaluations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    safe_add_column(
        "eval_runs",
        sa.Column(
            "environment_fingerprint_json",
            sa.JSON(),
            nullable=True,
        ),
    )
    eval_runs = sa.table(
        "eval_runs",
        sa.column("environment_fingerprint_json", sa.JSON()),
    )
    op.execute(eval_runs.update().where(eval_runs.c.environment_fingerprint_json.is_(None)).values(environment_fingerprint_json={}))


def downgrade() -> None:
    # 0005's canonical schema already includes this column. This revision only
    # repairs databases that were stamped at 0005 while missing it, so
    # downgrading to 0005 must preserve the column.
    return None
