"""Conservative lifecycle markers for tracing snapshot cleanup."""

import sqlalchemy as sa
from alembic import op

revision = "0049_tracing_retention"
down_revision = "0048_merge_tracing_mcp_oauth"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("run_tracing_snapshots")}
    additions = [sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()), sa.Column("retention_state", sa.String(16), nullable=False, server_default="unmanaged")]
    missing = [column for column in additions if column.name not in columns]
    if missing:
        # SQLite cannot ALTER an existing table with a CURRENT_TIMESTAMP default.
        with op.batch_alter_table("run_tracing_snapshots", recreate="always" if bind.dialect.name == "sqlite" else "auto") as batch:
            for column in missing:
                batch.add_column(column)
    if "ix_run_tracing_snapshots_retention" not in {index["name"] for index in sa.inspect(bind).get_indexes("run_tracing_snapshots")}:
        op.create_index("ix_run_tracing_snapshots_retention", "run_tracing_snapshots", ["retention_state", "created_at"])


def downgrade():
    bind = op.get_bind()
    if "ix_run_tracing_snapshots_retention" in {index["name"] for index in sa.inspect(bind).get_indexes("run_tracing_snapshots")}:
        op.drop_index("ix_run_tracing_snapshots_retention", table_name="run_tracing_snapshots")
    columns = {column["name"] for column in sa.inspect(bind).get_columns("run_tracing_snapshots")}
    with op.batch_alter_table("run_tracing_snapshots") as batch:
        for column in ("retention_state", "created_at"):
            if column in columns:
                batch.drop_column(column)
