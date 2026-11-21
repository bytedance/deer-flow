"""Join the batch recovery and thread sharing migration histories."""

from deerflow.persistence.migrations._batch_recovery import check_recovery_downgrade

revision = "0056_merge_batch_recovery"
down_revision = ("0055_thread_shares", "0053_batch_recovery")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    check_recovery_downgrade(revision)
