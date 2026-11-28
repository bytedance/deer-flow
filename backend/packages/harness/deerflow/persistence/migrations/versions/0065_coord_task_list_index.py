"""Index owner-scoped top-level tasks in creation order."""

import sqlalchemy as sa
from alembic import op

revision = "0065_coord_task_list_index"
down_revision = "0064_coordination_channel_origin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("coord_tasks")}
    if "ix_coord_tasks_owner_created" not in indexes:
        op.create_index(
            "ix_coord_tasks_owner_created",
            "coord_tasks",
            ["owner_id", "created_at", "id"],
            sqlite_where=sa.text("parent_id IS NULL"),
            postgresql_where=sa.text("parent_id IS NULL"),
        )


def downgrade() -> None:
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("coord_tasks")}
    if "ix_coord_tasks_owner_created" in indexes:
        op.drop_index("ix_coord_tasks_owner_created", table_name="coord_tasks")
