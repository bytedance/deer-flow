"""Join audited native and historical user-fork ancestry without replaying intent."""

revision = "0035_native_fork_compatibility"
down_revision = ("0034_run_event_seq_watermark", "0022_fleet_main_merge")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    raise RuntimeError("Native/Fleet rollback requires drained writers and a coherent backup")
