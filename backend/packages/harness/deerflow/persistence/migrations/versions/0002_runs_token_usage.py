"""Add ``runs.token_usage_by_model`` column.

Revision ID: 0002_runs_token_usage
Revises: 0001_baseline
Create Date: 2026-06-22

Fixes GitHub issue #3682: any pre-existing DB (created before commit e7a03e52
on PR #3658) lacks the ``token_usage_by_model`` JSON column on ``runs``.
Without this migration, every endpoint that ``SELECT``s from ``runs`` raises
``no such column: runs.token_usage_by_model``.

Schema parity with ``Base.metadata``
------------------------------------

The ORM model declares the column as ``Mapped[dict] = mapped_column(JSON,
default=dict, server_default=text("'{}'"))`` -- non-Optional, so SQLAlchemy
infers ``nullable=False``. ``Base.metadata.create_all`` (the empty-DB
bootstrap path) therefore produces ``token_usage_by_model JSON NOT NULL
DEFAULT '{}'`` on fresh databases.

To keep legacy-upgraded databases schema-identical to fresh ones, this
migration adds the column with the same ``nullable=False`` and
``server_default='{}'``. The server default is also what lets
``ALTER TABLE runs ADD COLUMN ... NOT NULL`` succeed on a populated table:
existing rows pick up the empty-object default at ALTER time instead of
triggering ``NOT NULL`` violations.

Idempotency
-----------

Uses ``safe_add_column`` so re-running this revision against a DB where the
column already exists is a no-op. That covers two real cases:

1. Users who applied the workaround in the issue manually
   (``ALTER TABLE runs ADD COLUMN token_usage_by_model JSON``).
2. Concurrent bootstrap on multiple Gateway instances if the cross-process
   lock is somehow bypassed -- defence-in-depth on top of
   ``bootstrap_schema``'s advisory-lock / sentinel-row mutex.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from deerflow.persistence.migrations._helpers import safe_add_column, safe_drop_column

# revision identifiers, used by Alembic.
revision: str = "0002_runs_token_usage"
down_revision: str | Sequence[str] | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    safe_add_column(
        "runs",
        sa.Column(
            "token_usage_by_model",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )


def downgrade() -> None:
    safe_drop_column("runs", "token_usage_by_model")
