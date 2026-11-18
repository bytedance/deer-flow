"""Durable Run producer identity, without historical authority backfill."""

import sqlalchemy as sa
from alembic import op

from deerflow.persistence.migrations._helpers import safe_add_column, safe_drop_column

revision = "0049_run_producer_fencing"
down_revision = "0048_extension_execution_leases"


def upgrade():
    for name, length in (("run_incarnation", 64), ("producer_epoch", 64), ("producer_state", 16)):
        safe_add_column("runs", sa.Column(name, sa.String(length), nullable=True))
    if not sa.inspect(op.get_bind()).has_table("run_producer_policy"):
        op.create_table("run_producer_policy", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("strict", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("cutover_id", sa.String(64), nullable=True))
    from deerflow.persistence.run.producer import install_event_guard

    install_event_guard(op.get_bind())


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        if bind.scalar(sa.text("SELECT strict FROM run_producer_policy WHERE id=1")):
            raise RuntimeError("Cannot downgrade an activated producer fencing database")
        op.execute("DROP TRIGGER IF EXISTS run_event_producer_guard ON run_events")
        op.execute("DROP FUNCTION IF EXISTS run_event_producer_guard()")
    op.drop_table("run_producer_policy")
    for name in ("producer_state", "producer_epoch", "run_incarnation"):
        safe_drop_column("runs", name)
