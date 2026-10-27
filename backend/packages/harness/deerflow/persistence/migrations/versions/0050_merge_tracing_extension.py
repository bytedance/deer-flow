"""Join tracing retention and upstream extension execution lease histories."""

revision = "0050_merge_tracing_extension"
down_revision = ("0049_tracing_retention", "0048_extension_execution_leases")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
