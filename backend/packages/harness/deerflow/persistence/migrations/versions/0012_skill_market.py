"""Add marketplace skills and tenant-specific installations."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_skill_market"
down_revision: str | Sequence[str] | None = "0011_billing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "market_skills",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("published", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "market_skill_installs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("market_skill_id", sa.String(64), nullable=False),
        sa.Column("installed_version", sa.String(32), nullable=False),
        sa.Column("installed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "market_skill_id", name="uq_user_market_skill"),
    )
    op.create_index("ix_market_skill_installs_user_id", "market_skill_installs", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_market_skill_installs_user_id", table_name="market_skill_installs")
    op.drop_table("market_skill_installs")
    op.drop_table("market_skills")
