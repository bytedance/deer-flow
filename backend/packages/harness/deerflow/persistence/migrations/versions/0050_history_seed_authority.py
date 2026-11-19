"""Refresh the installed producer guard with host history-seed authorization."""

from alembic import op

from deerflow.persistence.run.producer import install_event_guard

revision = "0050_history_seed_authority"
down_revision = "0049_run_producer_fencing"
branch_labels = None
depends_on = None


def upgrade():
    install_event_guard(op.get_bind())


def downgrade():
    # No schema or policy changes to undo. Retain cumulative enforcement until
    # the producer-fencing migration removes it, which forbids active downgrade.
    pass
