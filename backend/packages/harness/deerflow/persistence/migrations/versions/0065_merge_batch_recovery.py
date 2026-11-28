"""Join the batch recovery and coordination channel origin histories."""

from deerflow.persistence.migrations._batch_recovery import check_recovery_downgrade

revision = "0065_merge_batch_recovery"
down_revision = ("0064_coordination_channel_origin", "0061_merge_batch_recovery")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    check_recovery_downgrade(revision)
