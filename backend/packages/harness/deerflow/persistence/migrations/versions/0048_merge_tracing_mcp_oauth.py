"""Join the tracing-profile and MCP OAuth token migration histories."""

revision = "0048_merge_tracing_mcp_oauth"
down_revision = ("0047_tracing_profiles", "0047_mcp_oauth_tokens")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
