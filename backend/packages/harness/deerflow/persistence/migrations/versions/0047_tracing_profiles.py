"""Shared tracing profiles, atomic bindings and encrypted immutable snapshots.

Revision ID: 0047_tracing_profiles
Revises: 0046_skill_mutations
"""

import sqlalchemy as sa
from alembic import op

from deerflow.persistence.migrations._helpers import safe_add_column, safe_drop_column

revision = "0047_tracing_profiles"
down_revision = "0046_skill_mutations"
branch_labels = None
depends_on = None


def _create(name, *columns):
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(name):
        op.create_table(name, *columns)
    elif not {column.name for column in columns} <= {column["name"] for column in inspector.get_columns(name)}:
        raise RuntimeError(f"Incompatible tracing storage table: {name}")


def upgrade():
    safe_add_column("scheduled_task_runs", sa.Column("tracing_snapshot_refs", sa.JSON(), nullable=True))
    _create("tracing_admission_fence", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("version", sa.BigInteger(), nullable=False))
    fence = sa.table("tracing_admission_fence", sa.column("id", sa.Integer()), sa.column("version", sa.BigInteger()))
    if op.get_bind().execute(sa.select(fence.c.id).where(fence.c.id == 1)).first() is None:
        op.get_bind().execute(fence.insert().values(id=1, version=0))
    _create(
        "tracing_profiles",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("providers_ciphertext", sa.Text(), nullable=False),
        sa.Column("allowed_user_ids", sa.JSON(), nullable=False),
    )
    _create(
        "tracing_profile_versions",
        sa.Column("profile_id", sa.String(128), primary_key=True),
        sa.Column("revision", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("providers_ciphertext", sa.Text(), nullable=False),
        sa.Column("allowed_user_ids", sa.JSON(), nullable=False),
    )
    _create(
        "agent_tracing_bindings",
        sa.Column("owner_user_id", sa.String(64), primary_key=True),
        sa.Column("agent_name", sa.String(128), primary_key=True),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("profile_id", sa.String(128), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("agent_incarnation", sa.String(256), nullable=True),
    )
    _create(
        "run_tracing_snapshots",
        sa.Column("snapshot_id", sa.String(32), primary_key=True),
        sa.Column("owner_user_id", sa.String(64), nullable=False),
        sa.Column("agent_name", sa.String(128), nullable=False),
        sa.Column("agent_incarnation", sa.String(256), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("binding_revision", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.String(128), nullable=True),
        sa.Column("profile_revision", sa.Integer(), nullable=True),
        sa.Column("payload_ciphertext", sa.Text(), nullable=False),
    )


def downgrade():
    safe_drop_column("scheduled_task_runs", "tracing_snapshot_refs")
    for name in ("run_tracing_snapshots", "agent_tracing_bindings", "tracing_profile_versions", "tracing_profiles", "tracing_admission_fence"):
        if sa.inspect(op.get_bind()).has_table(name):
            op.drop_table(name)
