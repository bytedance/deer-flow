"""run ownership.

Revision ID: 0004_run_ownership
Revises: 0003_scheduled_tasks
Create Date: 2026-07-07
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

logger = logging.getLogger(__name__)

revision: str = "0004_run_ownership"
down_revision: str | Sequence[str] | None = "0003_scheduled_tasks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _dedupe_active_runs_per_thread() -> None:
    """Cancel superseded active rows so the partial unique index can be built.

    ``uq_runs_thread_active`` enforces at most one pending/running row per
    ``thread_id``. A DB that already has two+ active rows for the same thread
    (reachable in the field: Postgres deployments had reconciliation skipped
    by the old sqlite-only gate, and anyone who ran ``GATEWAY_WORKERS>1``
    before this PR can have duplicates) would fail ``CREATE UNIQUE INDEX``
    and abort the alembic upgrade, blocking gateway startup.

    Keep the newest active row per ``thread_id`` (by ``created_at`` DESC,
    ``run_id`` DESC as a deterministic tiebreaker) and mark the rest as
    ``error``. Cancelled rows get an explanatory ``error`` string so
    operators can see why the run was killed.
    """
    bind = op.get_bind()
    cancel_message = "cancelled during migration 0004_run_ownership: superseded by a newer active run for the same thread (partial unique index uq_runs_thread_active)"
    find_dupe_rows = sa.text(
        """
        SELECT run_id, thread_id
        FROM runs AS r1
        WHERE r1.status IN ('pending', 'running')
          AND EXISTS (
            SELECT 1 FROM runs AS r2
            WHERE r2.thread_id = r1.thread_id
              AND r2.status IN ('pending', 'running')
              AND r2.run_id <> r1.run_id
              AND (
                r2.created_at > r1.created_at
                OR (r2.created_at = r1.created_at AND r2.run_id > r1.run_id)
              )
          )
        """
    )
    rows = list(bind.execute(find_dupe_rows).fetchall())
    if not rows:
        return
    for run_id, thread_id in rows:
        logger.warning(
            "migration 0004_run_ownership: cancelling duplicate active run %s on thread %s",
            run_id,
            thread_id,
        )
    bind.execute(
        sa.text(
            """
            UPDATE runs
            SET status = 'error',
                error = :error_message
            WHERE status IN ('pending', 'running')
              AND EXISTS (
                SELECT 1 FROM runs AS r2
                WHERE r2.thread_id = runs.thread_id
                  AND r2.status IN ('pending', 'running')
                  AND r2.run_id <> runs.run_id
                  AND (
                    r2.created_at > runs.created_at
                    OR (r2.created_at = runs.created_at AND r2.run_id > runs.run_id)
                  )
              )
            """
        ),
        {"error_message": cancel_message},
    )


def upgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_add_column

    safe_add_column("runs", sa.Column("owner_worker_id", sa.String(length=128), nullable=True))
    safe_add_column("runs", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))

    # Idempotent index creation: the legacy bootstrap path runs create_all
    # (which creates the index from the ORM __table_args__) before upgrade
    # head, so the migration must not fail when the index already exists.
    insp = sa.inspect(op.get_bind())
    existing = {ix["name"] for ix in insp.get_indexes("runs")}
    if "ix_runs_lease" not in existing:
        with op.batch_alter_table("runs", schema=None) as batch_op:
            batch_op.create_index("ix_runs_lease", ["lease_expires_at"], unique=False)
    if "uq_runs_thread_active" not in existing:
        # Cancel duplicate active rows first so the partial UNIQUE index can
        # be built on DBs that already violate the invariant. No-op on clean
        # DBs (the common path -- create_all already created the index, so
        # this branch only runs on legacy DBs that pre-date the index).
        _dedupe_active_runs_per_thread()
        with op.batch_alter_table("runs", schema=None) as batch_op:
            batch_op.create_index(
                "uq_runs_thread_active",
                ["thread_id"],
                unique=True,
                sqlite_where=sa.text("status IN ('pending', 'running')"),
                postgresql_where=sa.text("status IN ('pending', 'running')"),
            )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing = {ix["name"] for ix in insp.get_indexes("runs")}
    if "uq_runs_thread_active" in existing:
        with op.batch_alter_table("runs", schema=None) as batch_op:
            batch_op.drop_index("uq_runs_thread_active")
    if "ix_runs_lease" in existing:
        with op.batch_alter_table("runs", schema=None) as batch_op:
            batch_op.drop_index("ix_runs_lease")

    from deerflow.persistence.migrations._helpers import safe_drop_column

    safe_drop_column("runs", "lease_expires_at")
    safe_drop_column("runs", "owner_worker_id")
