"""Keep original native Run authority without attributing historical rows."""

import sqlalchemy as sa

from deerflow.persistence.migrations._helpers import safe_add_column

revision = "0039_run_workspace_identity"
down_revision = "0038_workspace_read_clocks"
branch_labels = None
depends_on = None


def upgrade():
    safe_add_column("runs", sa.Column("workspace_context_json", sa.JSON(), nullable=True))
    safe_add_column("runs", sa.Column("thread_incarnation", sa.String(32), nullable=True))


def downgrade():
    raise RuntimeError("Run workspace authority requires restoring a matched backup generation")
