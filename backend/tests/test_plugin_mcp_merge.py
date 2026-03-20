"""Tests for MCP server merging from plugins."""

from src.plugins.mcp_merge import merge_plugin_mcp_servers, namespace_server_name


class TestNamespaceServerName:
    """Tests for namespacing MCP server names."""

    def test_simple_namespace(self):
        assert namespace_server_name("sales", "crm") == "sales:crm"

    def test_preserves_original_name(self):
        assert namespace_server_name("data", "postgres") == "data:postgres"


class TestMergePluginMcpServers:
    """Tests for merging plugin MCP servers into existing config."""

    def test_merge_new_servers(self):
        """Should add namespaced plugin servers to existing config."""
        existing = {
            "postgres": {"type": "stdio", "command": "pg"},
        }
        plugin_mcp = {
            "mcpServers": {
                "crm": {"type": "http", "url": "http://crm"},
                "email": {"type": "http", "url": "http://email"},
            },
        }

        result = merge_plugin_mcp_servers("sales", plugin_mcp, existing)

        assert "postgres" in result  # Original preserved
        assert "sales:crm" in result
        assert "sales:email" in result
        assert result["sales:crm"]["type"] == "http"

    def test_no_overwrite_existing(self):
        """Should not overwrite existing servers even with same namespaced name."""
        existing = {
            "sales:crm": {"type": "stdio", "command": "original"},
        }
        plugin_mcp = {
            "mcpServers": {
                "crm": {"type": "http", "url": "http://new-crm"},
            },
        }

        result = merge_plugin_mcp_servers("sales", plugin_mcp, existing)

        # Should keep the original
        assert result["sales:crm"]["type"] == "stdio"

    def test_empty_plugin_mcp(self):
        """Should return existing unchanged when plugin has no MCP servers."""
        existing = {"pg": {"type": "stdio"}}
        result = merge_plugin_mcp_servers("sales", {}, existing)
        assert result == existing

    def test_empty_existing(self):
        """Should work with empty existing config."""
        plugin_mcp = {
            "mcpServers": {
                "crm": {"type": "http", "url": "http://crm"},
            },
        }

        result = merge_plugin_mcp_servers("sales", plugin_mcp, {})

        assert "sales:crm" in result

    def test_multiple_plugins_merge(self):
        """Should correctly namespace servers from multiple plugins."""
        existing = {}

        plugin1_mcp = {"mcpServers": {"slack": {"type": "http"}}}
        plugin2_mcp = {"mcpServers": {"slack": {"type": "sse"}}}

        existing = merge_plugin_mcp_servers("sales", plugin1_mcp, existing)
        existing = merge_plugin_mcp_servers("support", plugin2_mcp, existing)

        assert "sales:slack" in existing
        assert "support:slack" in existing
        assert existing["sales:slack"]["type"] == "http"
        assert existing["support:slack"]["type"] == "sse"

    def test_missing_mcp_servers_key(self):
        """Should handle plugin_mcp dict without 'mcpServers' key."""
        existing = {"pg": {"type": "stdio"}}
        result = merge_plugin_mcp_servers("sales", {"other_key": 123}, existing)
        assert result == existing
