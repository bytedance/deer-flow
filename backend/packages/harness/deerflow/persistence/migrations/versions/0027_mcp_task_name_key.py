"""Add Unicode name keys and an index for MCP cancellation target lookup."""

import sqlalchemy as sa
from alembic import op

from deerflow.persistence.migrations._helpers import safe_add_column

revision = "0027_mcp_task_name_key"
down_revision = "0026_mcp_task_lease_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"]: column for column in sa.inspect(bind).get_columns("mcp_tasks")}
    if "task_name_key" not in columns:
        safe_add_column("mcp_tasks", sa.Column("task_name_key", sa.LargeBinary(), nullable=True))
    tasks = sa.table("mcp_tasks", sa.column("id", sa.String()), sa.column("task_name", sa.String()), sa.column("task_name_key", sa.LargeBinary()))
    # Backfill in primary-key batches during upgrade; runtime lookups do not load all active tasks.
    last_id = None
    while True:
        query = sa.select(tasks.c.id, tasks.c.task_name).where(tasks.c.task_name_key.is_(None)).order_by(tasks.c.id).limit(500)
        if last_id is not None:
            query = query.where(tasks.c.id > last_id)
        rows = bind.execute(query).all()
        if not rows:
            break
        bind.execute(
            tasks.update().where(tasks.c.id == sa.bindparam("row_id")).values(task_name_key=sa.bindparam("name_key")),
            [{"row_id": row.id, "name_key": row.task_name.casefold().encode("utf-8")} for row in rows],
        )
        last_id = rows[-1].id
    columns = {column["name"]: column for column in sa.inspect(bind).get_columns("mcp_tasks")}
    if columns["task_name_key"]["nullable"]:
        with op.batch_alter_table("mcp_tasks") as batch:
            batch.alter_column("task_name_key", existing_type=sa.LargeBinary(), nullable=False)
    if "ix_mcp_tasks_name_scope" not in {index["name"] for index in sa.inspect(bind).get_indexes("mcp_tasks")}:
        op.create_index("ix_mcp_tasks_name_scope", "mcp_tasks", ["user_id", "thread_id", "task_name_key"])


def downgrade() -> None:
    bind = op.get_bind()
    if "ix_mcp_tasks_name_scope" in {index["name"] for index in sa.inspect(bind).get_indexes("mcp_tasks")}:
        op.drop_index("ix_mcp_tasks_name_scope", table_name="mcp_tasks")
    if "task_name_key" in {column["name"] for column in sa.inspect(bind).get_columns("mcp_tasks")}:
        with op.batch_alter_table("mcp_tasks") as batch:
            batch.drop_column("task_name_key")
