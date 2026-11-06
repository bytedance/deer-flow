"""Bounded interactive input state on the existing run row.

Revision ID: 0049_run_inputs
Revises: 0048_extension_execution_leases
"""

import sqlalchemy as sa
from alembic import op

revision = "0049_run_inputs"
down_revision = "0048_extension_execution_leases"
branch_labels = None
depends_on = None


def upgrade():
    if "run_inputs_json" not in {x["name"] for x in sa.inspect(op.get_bind()).get_columns("runs")}:
        op.add_column("runs", sa.Column("run_inputs_json", sa.JSON(), nullable=True))


def downgrade():
    if "run_inputs_json" in {x["name"] for x in sa.inspect(op.get_bind()).get_columns("runs")}:
        op.drop_column("runs", "run_inputs_json")
