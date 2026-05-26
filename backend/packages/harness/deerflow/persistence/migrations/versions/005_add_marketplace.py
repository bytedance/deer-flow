"""Add marketplace tables

Revision ID: 005
Revises: 004
Create Date: 2026-05-26

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "marketplace_listing",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("template_id", sa.String(64), nullable=False),
        sa.Column("template_version", sa.Integer(), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("visibility", sa.String(20), nullable=False, server_default="tenant"),
        sa.Column("category", sa.String(50), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("icon", sa.String(100), nullable=True),
        sa.Column("avg_rating", sa.Float(), nullable=False, server_default="0"),
        sa.Column("review_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("install_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("template_id", name="uq_marketplace_listing_template"),
    )
    op.create_index("ix_marketplace_tenant", "marketplace_listing", ["tenant_id"])
    op.create_index("ix_marketplace_visibility", "marketplace_listing", ["visibility"])
    op.create_index("ix_marketplace_category", "marketplace_listing", ["category"])
    op.create_index("ix_marketplace_status", "marketplace_listing", ["status"])

    op.create_table(
        "marketplace_review",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("listing_id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("listing_id", "user_id", name="uq_marketplace_review_listing_user"),
    )
    op.create_index("ix_review_listing", "marketplace_review", ["listing_id"])
    op.create_index("ix_review_tenant", "marketplace_review", ["tenant_id"])

    op.create_table(
        "marketplace_install_record",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("listing_id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("target_template_id", sa.String(64), nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=False),
        sa.Column("installed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_install_listing", "marketplace_install_record", ["listing_id"])
    op.create_index("ix_install_tenant_user", "marketplace_install_record", ["tenant_id", "user_id"])


def downgrade() -> None:
    op.drop_index("ix_install_tenant_user", table_name="marketplace_install_record")
    op.drop_index("ix_install_listing", table_name="marketplace_install_record")
    op.drop_table("marketplace_install_record")

    op.drop_index("ix_review_tenant", table_name="marketplace_review")
    op.drop_index("ix_review_listing", table_name="marketplace_review")
    op.drop_table("marketplace_review")

    op.drop_index("ix_marketplace_status", table_name="marketplace_listing")
    op.drop_index("ix_marketplace_category", table_name="marketplace_listing")
    op.drop_index("ix_marketplace_visibility", table_name="marketplace_listing")
    op.drop_index("ix_marketplace_tenant", table_name="marketplace_listing")
    op.drop_table("marketplace_listing")
