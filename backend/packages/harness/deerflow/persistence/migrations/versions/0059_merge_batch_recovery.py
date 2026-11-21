"""Join the batch recovery and MCP browser OAuth migration histories."""

from deerflow.persistence.migrations._batch_recovery import check_recovery_downgrade

revision = "0059_merge_batch_recovery"
down_revision = ("0058_mcp_browser_oauth", "0056_merge_batch_recovery")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    check_recovery_downgrade(revision)
