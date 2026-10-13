"""Add nullable scope without changing physical reservations or old payloads."""

import sqlalchemy as sa
from alembic import op

revision = "e0002_workspace_scope"
down_revision = "e0001_execution_ledger"
branch_labels = None
depends_on = None


def upgrade():
    for name in ("ecs_execution_jobs", "ecs_native_affinities"):
        inspector = sa.inspect(op.get_bind())
        if "workspace_id" not in {column["name"] for column in inspector.get_columns(name)}:
            op.add_column(name, sa.Column("workspace_id", sa.String(36), nullable=True))
        index_name = f"ix_{name}_workspace_id"
        if index_name not in {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(name)}:
            op.create_index(index_name, name, ["workspace_id"])


def downgrade():
    raise RuntimeError("Executor tenant rollback requires drained physical execution and coherent backups; workspace ownership cannot be dropped")
