"""Explicit project publication; historical projects remain private."""

import sqlalchemy as sa
from alembic import op

revision = "0037_project_visibility"
down_revision = "0036_tenant_workspaces"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("projects")}
    constraints = {constraint["name"] for constraint in inspector.get_check_constraints("projects")}
    with op.batch_alter_table("projects") as batch:
        if "visibility" not in columns:
            batch.add_column(sa.Column("visibility", sa.String(16), nullable=False, server_default="private"))
        if "ck_project_visibility" not in constraints:
            batch.create_check_constraint("ck_project_visibility", "visibility IN ('private', 'workspace')")


def downgrade():
    raise RuntimeError("Project sharing scope cannot be discarded; restore a matched backup generation")
