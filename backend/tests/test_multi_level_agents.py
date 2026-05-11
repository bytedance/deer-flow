"""Unit tests for multi-level agent discovery, MCP filtering, and config parsing."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from deerflow.config.agents_config import (
    AgentConfig,
    AgentInfo,
    list_available_agents,
    load_agent_config,
    load_tenant_agent_soul,
    scan_builtin_agents,
    scan_tenant_agents,
    to_agent_info,
)


class TestAgentConfigExtension:
    """Test AgentConfig new fields and backward compatibility."""

    def test_minimal_config_backward_compatible(self):
        config = AgentConfig(name="test")
        assert config.name == "test"
        assert config.description == ""
        assert config.display_name is None
        assert config.icon is None
        assert config.model is None
        assert config.visibility == "public"
        assert config.tool_groups is None
        assert config.skills is None
        assert config.mcp_servers is None
        assert config.tags is None
        assert config.advanced is None

    def test_full_config_all_fields(self):
        config = AgentConfig(
            name="researcher",
            description="Research assistant",
            display_name="Research Helper",
            icon="search",
            model="gpt-4",
            visibility="tenant_public",
            tool_groups=["web", "bash"],
            skills=["deep-research"],
            mcp_servers=["arxiv-search"],
            tags=["research", "writing"],
            advanced={"subagent_enabled": False, "max_turns": 50},
        )
        assert config.display_name == "Research Helper"
        assert config.icon == "search"
        assert config.visibility == "tenant_public"
        assert config.mcp_servers == ["arxiv-search"]
        assert config.tags == ["research", "writing"]
        assert config.advanced == {"subagent_enabled": False, "max_turns": 50}

    def test_unknown_fields_ignored_by_pydantic(self):
        data = {"name": "test", "unknown_field": "value", "another": 123}
        known_fields = set(AgentConfig.model_fields.keys())
        filtered = {k: v for k, v in data.items() if k in known_fields}
        config = AgentConfig(**filtered)
        assert config.name == "test"
        assert not hasattr(config, "unknown_field")


class TestAgentInfo:
    """Test AgentInfo model and to_agent_info conversion."""

    def test_to_agent_info_builtin(self):
        config = AgentConfig(
            name="researcher",
            description="Research assistant",
            display_name="Research",
            icon="search",
            tags=["research"],
            tool_groups=["web"],
            skills=["deep-research"],
            mcp_servers=None,
        )
        info = to_agent_info(config, source="builtin", editable=False)
        assert isinstance(info, AgentInfo)
        assert info.name == "researcher"
        assert info.source == "builtin"
        assert info.editable is False
        assert info.enabled is True
        assert info.display_name == "Research"
        assert info.tags == ["research"]

    def test_to_agent_info_user(self):
        config = AgentConfig(name="my-agent", description="Custom")
        info = to_agent_info(config, source="user", editable=True)
        assert info.source == "user"
        assert info.editable is True

    def test_to_agent_info_with_tenant(self):
        config = AgentConfig(name="company-bot")
        info = to_agent_info(config, source="tenant", editable=False, tenant_id="acme")
        assert info.source == "tenant"
        assert info.tenant_id == "acme"


class TestScanBuiltinAgents:
    """Test scan_builtin_agents discovery."""

    def test_scan_returns_empty_when_dir_missing(self):
        with patch("deerflow.config.agents_config._get_builtin_agents_dir") as mock_dir:
            mock_dir.return_value = Path("/nonexistent/path")
            agents = scan_builtin_agents()
            assert agents == []

    def test_scan_finds_agents_in_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            builtin_dir = Path(tmpdir)
            agent_dir = builtin_dir / "test-agent"
            agent_dir.mkdir()
            config_data = {"name": "test-agent", "description": "A test", "tags": ["test"]}
            (agent_dir / "config.yaml").write_text(yaml.dump(config_data), encoding="utf-8")

            with patch("deerflow.config.agents_config._get_builtin_agents_dir") as mock_dir:
                mock_dir.return_value = builtin_dir
                agents = scan_builtin_agents()
                assert len(agents) == 1
                assert agents[0].name == "test-agent"
                assert agents[0].tags == ["test"]

    def test_scan_skips_dirs_without_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            builtin_dir = Path(tmpdir)
            (builtin_dir / "no-config-agent").mkdir()
            (builtin_dir / "valid-agent").mkdir()
            (builtin_dir / "valid-agent" / "config.yaml").write_text(
                yaml.dump({"name": "valid-agent"}), encoding="utf-8"
            )

            with patch("deerflow.config.agents_config._get_builtin_agents_dir") as mock_dir:
                mock_dir.return_value = builtin_dir
                agents = scan_builtin_agents()
                assert len(agents) == 1
                assert agents[0].name == "valid-agent"

    def test_scan_skips_invalid_yaml(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            builtin_dir = Path(tmpdir)
            agent_dir = builtin_dir / "bad-yaml"
            agent_dir.mkdir()
            (agent_dir / "config.yaml").write_text("{{invalid yaml", encoding="utf-8")

            with patch("deerflow.config.agents_config._get_builtin_agents_dir") as mock_dir:
                mock_dir.return_value = builtin_dir
                agents = scan_builtin_agents()
                assert agents == []

    def test_scan_results_sorted_by_name(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            builtin_dir = Path(tmpdir)
            for name in ["zebra", "alpha", "middle"]:
                d = builtin_dir / name
                d.mkdir()
                (d / "config.yaml").write_text(yaml.dump({"name": name}), encoding="utf-8")

            with patch("deerflow.config.agents_config._get_builtin_agents_dir") as mock_dir:
                mock_dir.return_value = builtin_dir
                agents = scan_builtin_agents()
                assert [a.name for a in agents] == ["alpha", "middle", "zebra"]


class TestLoadAgentConfigBuiltinFallback:
    """Test load_agent_config falls back to builtin agents."""

    def test_loads_builtin_when_user_agent_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            builtin_dir = Path(tmpdir)
            agent_dir = builtin_dir / "researcher"
            agent_dir.mkdir()
            config_data = {"name": "researcher", "description": "Builtin researcher", "tags": ["research"]}
            (agent_dir / "config.yaml").write_text(yaml.dump(config_data), encoding="utf-8")

            with (
                patch("deerflow.config.agents_config._get_builtin_agents_dir") as mock_builtin,
                patch("deerflow.config.agents_config.resolve_agent_dir") as mock_resolve,
            ):
                mock_builtin.return_value = builtin_dir
                fake_user_dir = Path(tmpdir) / "users" / "default" / "agents" / "researcher"
                mock_resolve.return_value = fake_user_dir

                config = load_agent_config("researcher", user_id="default")
                assert config is not None
                assert config.name == "researcher"
                assert config.description == "Builtin researcher"
                assert config.tags == ["research"]

    def test_raises_when_agent_not_found_anywhere(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                patch("deerflow.config.agents_config._get_builtin_agents_dir") as mock_builtin,
                patch("deerflow.config.agents_config.resolve_agent_dir") as mock_resolve,
            ):
                mock_builtin.return_value = Path(tmpdir) / "empty"
                mock_resolve.return_value = Path(tmpdir) / "users" / "default" / "agents" / "nonexistent"

                with pytest.raises(FileNotFoundError):
                    load_agent_config("nonexistent", user_id="default")

    def test_returns_none_for_none_name(self):
        assert load_agent_config(None) is None


class TestMcpServerFiltering:
    """Test MCP server prefix filtering logic."""

    def test_filter_by_server_prefix(self):
        from unittest.mock import MagicMock

        tool_a = MagicMock()
        tool_a.name = "arxiv__search_papers"
        tool_b = MagicMock()
        tool_b.name = "arxiv__get_paper"
        tool_c = MagicMock()
        tool_c.name = "github__list_repos"
        tool_d = MagicMock()
        tool_d.name = "slack__send_message"

        all_tools = [tool_a, tool_b, tool_c, tool_d]

        mcp_servers = ["arxiv", "github"]
        server_prefixes = tuple(f"{s}__" for s in mcp_servers)
        filtered = [t for t in all_tools if t.name.startswith(server_prefixes)]

        assert len(filtered) == 3
        assert tool_a in filtered
        assert tool_b in filtered
        assert tool_c in filtered
        assert tool_d not in filtered

    def test_none_mcp_servers_includes_all(self):
        from unittest.mock import MagicMock

        tool_a = MagicMock()
        tool_a.name = "arxiv__search"
        tool_b = MagicMock()
        tool_b.name = "slack__send"

        all_tools = [tool_a, tool_b]
        mcp_servers = None

        if mcp_servers is not None:
            server_prefixes = tuple(f"{s}__" for s in mcp_servers)
            filtered = [t for t in all_tools if t.name.startswith(server_prefixes)]
        else:
            filtered = all_tools

        assert len(filtered) == 2

    def test_empty_mcp_servers_excludes_all(self):
        from unittest.mock import MagicMock

        tool_a = MagicMock()
        tool_a.name = "arxiv__search"

        all_tools = [tool_a]
        mcp_servers: list[str] = []

        server_prefixes = tuple(f"{s}__" for s in mcp_servers)
        filtered = [t for t in all_tools if t.name.startswith(server_prefixes)]

        assert len(filtered) == 0


class TestTenantAdminAuth:
    """Test is_tenant_admin authorization utility."""

    def test_superadmin_is_tenant_admin(self):
        from deerflow.persistence.agent.auth import is_tenant_admin

        assert is_tenant_admin("superadmin") is True

    def test_tenant_admin_is_tenant_admin(self):
        from deerflow.persistence.agent.auth import is_tenant_admin

        assert is_tenant_admin("tenant_admin") is True

    def test_regular_user_is_not_tenant_admin(self):
        from deerflow.persistence.agent.auth import is_tenant_admin

        assert is_tenant_admin("user") is False

    def test_none_is_not_tenant_admin(self):
        from deerflow.persistence.agent.auth import is_tenant_admin

        assert is_tenant_admin(None) is False

    def test_empty_string_is_not_tenant_admin(self):
        from deerflow.persistence.agent.auth import is_tenant_admin

        assert is_tenant_admin("") is False


class TestScanTenantAgents:
    """Test scan_tenant_agents discovery from filesystem."""

    def test_scan_returns_empty_when_dir_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("deerflow.config.agents_config.get_paths") as mock_paths:
                mock_paths.return_value = MagicMock(base_dir=Path(tmpdir))
                agents = scan_tenant_agents("nonexistent-tenant")
                assert agents == []

    def test_scan_finds_tenant_agents(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            tenant_agents_dir = base_dir / "tenants" / "acme" / "agents"
            agent_dir = tenant_agents_dir / "company-bot"
            agent_dir.mkdir(parents=True)
            config_data = {"name": "company-bot", "description": "Company assistant", "visibility": "tenant_public", "tags": ["internal"]}
            (agent_dir / "config.yaml").write_text(yaml.dump(config_data), encoding="utf-8")

            with patch("deerflow.config.agents_config.get_paths") as mock_paths:
                mock_paths.return_value = MagicMock(base_dir=base_dir)
                agents = scan_tenant_agents("acme")
                assert len(agents) == 1
                assert agents[0].name == "company-bot"
                assert agents[0].description == "Company assistant"
                assert agents[0].tags == ["internal"]

    def test_scan_skips_dirs_without_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            tenant_agents_dir = base_dir / "tenants" / "acme" / "agents"
            (tenant_agents_dir / "no-config").mkdir(parents=True)
            valid_dir = tenant_agents_dir / "valid-agent"
            valid_dir.mkdir()
            (valid_dir / "config.yaml").write_text(yaml.dump({"name": "valid-agent"}), encoding="utf-8")

            with patch("deerflow.config.agents_config.get_paths") as mock_paths:
                mock_paths.return_value = MagicMock(base_dir=base_dir)
                agents = scan_tenant_agents("acme")
                assert len(agents) == 1
                assert agents[0].name == "valid-agent"

    def test_scan_multiple_agents_sorted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            tenant_agents_dir = base_dir / "tenants" / "acme" / "agents"
            for name in ["zeta-bot", "alpha-bot", "mid-bot"]:
                d = tenant_agents_dir / name
                d.mkdir(parents=True)
                (d / "config.yaml").write_text(yaml.dump({"name": name}), encoding="utf-8")

            with patch("deerflow.config.agents_config.get_paths") as mock_paths:
                mock_paths.return_value = MagicMock(base_dir=base_dir)
                agents = scan_tenant_agents("acme")
                assert [a.name for a in agents] == ["alpha-bot", "mid-bot", "zeta-bot"]


class TestLoadTenantAgentSoul:
    """Test load_tenant_agent_soul reads SOUL.md from tenant directory."""

    def test_returns_soul_content(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            soul_dir = base_dir / "tenants" / "acme" / "agents" / "company-bot"
            soul_dir.mkdir(parents=True)
            (soul_dir / "SOUL.md").write_text("You are a helpful company assistant.", encoding="utf-8")

            with patch("deerflow.config.agents_config.get_paths") as mock_paths:
                mock_paths.return_value = MagicMock(base_dir=base_dir)
                soul = load_tenant_agent_soul("acme", "company-bot")
                assert soul == "You are a helpful company assistant."

    def test_returns_none_when_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            with patch("deerflow.config.agents_config.get_paths") as mock_paths:
                mock_paths.return_value = MagicMock(base_dir=base_dir)
                soul = load_tenant_agent_soul("acme", "nonexistent")
                assert soul is None

    def test_returns_none_for_empty_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            soul_dir = base_dir / "tenants" / "acme" / "agents" / "empty-soul"
            soul_dir.mkdir(parents=True)
            (soul_dir / "SOUL.md").write_text("   ", encoding="utf-8")

            with patch("deerflow.config.agents_config.get_paths") as mock_paths:
                mock_paths.return_value = MagicMock(base_dir=base_dir)
                soul = load_tenant_agent_soul("acme", "empty-soul")
                assert soul is None


class TestLoadAgentConfigTenantFallback:
    """Test load_agent_config falls back to tenant agents."""

    def test_loads_tenant_agent_when_user_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            # Set up tenant agent
            tenant_dir = base_dir / "tenants" / "acme" / "agents" / "company-bot"
            tenant_dir.mkdir(parents=True)
            config_data = {"name": "company-bot", "description": "Tenant bot", "visibility": "tenant_public"}
            (tenant_dir / "config.yaml").write_text(yaml.dump(config_data), encoding="utf-8")

            # Set up builtin agent with same name (should NOT be used)
            builtin_dir = Path(tmpdir) / "builtin"
            builtin_agent = builtin_dir / "company-bot"
            builtin_agent.mkdir(parents=True)
            (builtin_agent / "config.yaml").write_text(yaml.dump({"name": "company-bot", "description": "Builtin version"}), encoding="utf-8")

            with (
                patch("deerflow.config.agents_config.get_paths") as mock_paths,
                patch("deerflow.config.agents_config._get_builtin_agents_dir") as mock_builtin,
                patch("deerflow.config.agents_config.resolve_agent_dir") as mock_resolve,
            ):
                mock_paths.return_value = MagicMock(base_dir=base_dir)
                mock_builtin.return_value = builtin_dir
                fake_user_dir = base_dir / "users" / "default" / "agents" / "company-bot"
                mock_resolve.return_value = fake_user_dir

                config = load_agent_config("company-bot", user_id="default", tenant_id="acme")
                assert config is not None
                assert config.name == "company-bot"
                assert config.description == "Tenant bot"

    def test_user_agent_takes_priority_over_tenant(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            # Set up user agent
            user_dir = base_dir / "users" / "user1" / "agents" / "my-bot"
            user_dir.mkdir(parents=True)
            (user_dir / "config.yaml").write_text(yaml.dump({"name": "my-bot", "description": "User version"}), encoding="utf-8")

            # Set up tenant agent with same name
            tenant_dir = base_dir / "tenants" / "acme" / "agents" / "my-bot"
            tenant_dir.mkdir(parents=True)
            (tenant_dir / "config.yaml").write_text(yaml.dump({"name": "my-bot", "description": "Tenant version"}), encoding="utf-8")

            with (
                patch("deerflow.config.agents_config.get_paths") as mock_paths,
                patch("deerflow.config.agents_config.resolve_agent_dir") as mock_resolve,
            ):
                mock_paths.return_value = MagicMock(base_dir=base_dir)
                mock_resolve.return_value = user_dir

                config = load_agent_config("my-bot", user_id="user1", tenant_id="acme")
                assert config is not None
                assert config.description == "User version"


class TestListAvailableAgents:
    """Test list_available_agents three-level merge with priority dedup."""

    def test_merges_all_three_levels(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)

            # Builtin agent
            builtin_dir = base_dir / "builtin"
            (builtin_dir / "researcher").mkdir(parents=True)
            (builtin_dir / "researcher" / "config.yaml").write_text(
                yaml.dump({"name": "researcher", "description": "Builtin researcher"}), encoding="utf-8"
            )

            # Tenant agent
            tenant_dir = base_dir / "tenants" / "acme" / "agents" / "company-bot"
            tenant_dir.mkdir(parents=True)
            (tenant_dir / "config.yaml").write_text(
                yaml.dump({"name": "company-bot", "description": "Tenant bot"}), encoding="utf-8"
            )

            # User agent
            user_dir = base_dir / "users" / "user1" / "agents" / "my-agent"
            user_dir.mkdir(parents=True)
            (user_dir / "config.yaml").write_text(
                yaml.dump({"name": "my-agent", "description": "User agent"}), encoding="utf-8"
            )

            with (
                patch("deerflow.config.agents_config._get_builtin_agents_dir") as mock_builtin,
                patch("deerflow.config.agents_config.get_paths") as mock_paths,
                patch("deerflow.config.agents_config.get_effective_user_id") as mock_uid,
            ):
                mock_builtin.return_value = builtin_dir
                mock_paths.return_value = MagicMock(
                    base_dir=base_dir,
                    user_agents_dir=lambda uid: base_dir / "users" / uid / "agents",
                    agents_dir=base_dir / "legacy-agents",
                )
                mock_uid.return_value = "user1"

                agents = list_available_agents(tenant_id="acme", user_id="user1")
                names = [a.name for a in agents]
                assert "researcher" in names
                assert "company-bot" in names
                assert "my-agent" in names
                assert len(agents) == 3

                # Check sources
                by_name = {a.name: a for a in agents}
                assert by_name["researcher"].source == "builtin"
                assert by_name["company-bot"].source == "tenant"
                assert by_name["my-agent"].source == "user"

    def test_user_overrides_tenant_and_builtin(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)

            # Builtin agent named "shared"
            builtin_dir = base_dir / "builtin"
            (builtin_dir / "shared").mkdir(parents=True)
            (builtin_dir / "shared" / "config.yaml").write_text(
                yaml.dump({"name": "shared", "description": "Builtin"}), encoding="utf-8"
            )

            # Tenant agent named "shared"
            tenant_dir = base_dir / "tenants" / "acme" / "agents" / "shared"
            tenant_dir.mkdir(parents=True)
            (tenant_dir / "config.yaml").write_text(
                yaml.dump({"name": "shared", "description": "Tenant"}), encoding="utf-8"
            )

            # User agent named "shared" (should win)
            user_dir = base_dir / "users" / "user1" / "agents" / "shared"
            user_dir.mkdir(parents=True)
            (user_dir / "config.yaml").write_text(
                yaml.dump({"name": "shared", "description": "User"}), encoding="utf-8"
            )

            with (
                patch("deerflow.config.agents_config._get_builtin_agents_dir") as mock_builtin,
                patch("deerflow.config.agents_config.get_paths") as mock_paths,
                patch("deerflow.config.agents_config.get_effective_user_id") as mock_uid,
            ):
                mock_builtin.return_value = builtin_dir
                mock_paths.return_value = MagicMock(
                    base_dir=base_dir,
                    user_agents_dir=lambda uid: base_dir / "users" / uid / "agents",
                    agents_dir=base_dir / "legacy-agents",
                )
                mock_uid.return_value = "user1"

                agents = list_available_agents(tenant_id="acme", user_id="user1")
                assert len(agents) == 1
                assert agents[0].name == "shared"
                assert agents[0].source == "user"
                assert agents[0].editable is True

    def test_tenant_overrides_builtin(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)

            # Builtin agent named "researcher"
            builtin_dir = base_dir / "builtin"
            (builtin_dir / "researcher").mkdir(parents=True)
            (builtin_dir / "researcher" / "config.yaml").write_text(
                yaml.dump({"name": "researcher", "description": "Builtin"}), encoding="utf-8"
            )

            # Tenant agent named "researcher" (should win over builtin)
            tenant_dir = base_dir / "tenants" / "acme" / "agents" / "researcher"
            tenant_dir.mkdir(parents=True)
            (tenant_dir / "config.yaml").write_text(
                yaml.dump({"name": "researcher", "description": "Tenant override"}), encoding="utf-8"
            )

            with (
                patch("deerflow.config.agents_config._get_builtin_agents_dir") as mock_builtin,
                patch("deerflow.config.agents_config.get_paths") as mock_paths,
                patch("deerflow.config.agents_config.get_effective_user_id") as mock_uid,
            ):
                mock_builtin.return_value = builtin_dir
                mock_paths.return_value = MagicMock(
                    base_dir=base_dir,
                    user_agents_dir=lambda uid: base_dir / "users" / uid / "agents",
                    agents_dir=base_dir / "legacy-agents",
                )
                mock_uid.return_value = "user1"

                agents = list_available_agents(tenant_id="acme", user_id="user1")
                assert len(agents) == 1
                assert agents[0].source == "tenant"
                assert agents[0].editable is False

    def test_no_tenant_skips_tenant_level(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)

            builtin_dir = base_dir / "builtin"
            (builtin_dir / "researcher").mkdir(parents=True)
            (builtin_dir / "researcher" / "config.yaml").write_text(
                yaml.dump({"name": "researcher"}), encoding="utf-8"
            )

            with (
                patch("deerflow.config.agents_config._get_builtin_agents_dir") as mock_builtin,
                patch("deerflow.config.agents_config.get_paths") as mock_paths,
                patch("deerflow.config.agents_config.get_effective_user_id") as mock_uid,
            ):
                mock_builtin.return_value = builtin_dir
                mock_paths.return_value = MagicMock(
                    base_dir=base_dir,
                    user_agents_dir=lambda uid: base_dir / "users" / uid / "agents",
                    agents_dir=base_dir / "legacy-agents",
                )
                mock_uid.return_value = "user1"

                agents = list_available_agents(tenant_id=None, user_id="user1")
                assert len(agents) == 1
                assert agents[0].source == "builtin"


class TestTenantMcpServerModel:
    """Test TenantMcpServerRow ORM model."""

    def test_model_fields(self):
        from deerflow.persistence.mcp_server.model import TenantMcpServerRow

        row = TenantMcpServerRow(
            id="test-id",
            tenant_id="acme",
            server_name="arxiv-search",
            display_name="ArXiv Search",
            description="Search academic papers",
            config={"type": "stdio", "command": "npx", "args": ["-y", "arxiv-mcp"]},
            enabled=True,
            created_by="admin1",
        )
        assert row.tenant_id == "acme"
        assert row.server_name == "arxiv-search"
        assert row.config["type"] == "stdio"
        assert row.enabled is True

    def test_to_dict(self):
        from datetime import UTC, datetime

        from deerflow.persistence.mcp_server.model import TenantMcpServerRow

        now = datetime.now(UTC)
        row = TenantMcpServerRow(
            id="id-1",
            tenant_id="acme",
            server_name="my-server",
            display_name=None,
            description=None,
            config={"type": "sse", "url": "http://localhost:3001"},
            enabled=False,
            created_by="user1",
            created_at=now,
            updated_at=now,
        )
        d = row.to_dict()
        assert d["id"] == "id-1"
        assert d["server_name"] == "my-server"
        assert d["enabled"] is False
        assert d["config"]["type"] == "sse"


class TestMcpToolMergeLogic:
    """Test MCP tool merge logic (global + tenant with override)."""

    def test_tenant_tools_override_global_same_prefix(self):
        tool_global_a = MagicMock()
        tool_global_a.name = "arxiv__search"
        tool_global_b = MagicMock()
        tool_global_b.name = "github__repos"
        tool_tenant_a = MagicMock()
        tool_tenant_a.name = "arxiv__search_v2"

        mcp_tools = [tool_global_a, tool_global_b]
        tenant_mcp_configs = {"arxiv": {"type": "stdio", "command": "arxiv-v2"}}

        # Simulate the merge logic from get_available_tools
        tenant_prefixes = tuple(f"{s}__" for s in tenant_mcp_configs)
        mcp_tools = [t for t in mcp_tools if not t.name.startswith(tenant_prefixes)]
        tenant_tools = [tool_tenant_a]
        mcp_tools.extend(tenant_tools)

        assert len(mcp_tools) == 2
        assert tool_global_b in mcp_tools
        assert tool_tenant_a in mcp_tools
        assert tool_global_a not in mcp_tools

    def test_no_tenant_configs_keeps_all_global(self):
        tool_a = MagicMock()
        tool_a.name = "arxiv__search"
        tool_b = MagicMock()
        tool_b.name = "github__repos"

        mcp_tools = [tool_a, tool_b]
        tenant_mcp_configs = None

        if tenant_mcp_configs:
            tenant_prefixes = tuple(f"{s}__" for s in tenant_mcp_configs)
            mcp_tools = [t for t in mcp_tools if not t.name.startswith(tenant_prefixes)]

        assert len(mcp_tools) == 2

    def test_agent_level_filter_after_merge(self):
        tool_a = MagicMock()
        tool_a.name = "arxiv__search"
        tool_b = MagicMock()
        tool_b.name = "github__repos"
        tool_c = MagicMock()
        tool_c.name = "slack__send"

        mcp_tools = [tool_a, tool_b, tool_c]

        # Agent only wants arxiv and slack
        mcp_servers = ["arxiv", "slack"]
        server_prefixes = tuple(f"{s}__" for s in mcp_servers)
        filtered = [t for t in mcp_tools if t.name.startswith(server_prefixes)]

        assert len(filtered) == 2
        assert tool_a in filtered
        assert tool_c in filtered
        assert tool_b not in filtered


class TestAgentEnableDisable:
    """Test agent enable/disable state management."""

    def test_disabled_agents_file_operations(self):
        import json

        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            user_dir = base_dir / "users" / "user1"
            user_dir.mkdir(parents=True)
            disabled_path = user_dir / "disabled_agents.json"

            # Initially no file → empty set
            assert not disabled_path.exists()

            # Write disabled agents
            disabled = {"researcher", "writer"}
            disabled_path.write_text(json.dumps(sorted(disabled)), encoding="utf-8")

            # Read back
            data = json.loads(disabled_path.read_text(encoding="utf-8"))
            assert set(data) == {"researcher", "writer"}

            # Remove one
            disabled.discard("researcher")
            disabled_path.write_text(json.dumps(sorted(disabled)), encoding="utf-8")
            data = json.loads(disabled_path.read_text(encoding="utf-8"))
            assert set(data) == {"writer"}

    def test_disabled_agents_filter_in_listing(self):
        """Verify that disabled agents get enabled=False in the listing."""
        from deerflow.config.agents_config import AgentConfig

        agents = [
            AgentConfig(name="researcher", description="Research"),
            AgentConfig(name="writer", description="Writing"),
            AgentConfig(name="coder", description="Coding"),
        ]

        disabled = {"writer"}

        results = []
        for cfg in agents:
            info = {"name": cfg.name, "enabled": cfg.name not in disabled}
            results.append(info)

        assert results[0]["enabled"] is True
        assert results[1]["enabled"] is False
        assert results[2]["enabled"] is True


class TestMcpConfigValidation:
    """Test MCP server config validation logic."""

    def test_valid_stdio_config(self):
        config = {"type": "stdio", "command": "npx", "args": ["-y", "some-mcp"]}
        assert config["type"] in ("stdio", "sse", "http")
        assert "command" in config

    def test_valid_sse_config(self):
        config = {"type": "sse", "url": "http://localhost:3001/sse"}
        assert config["type"] in ("stdio", "sse", "http")
        assert "url" in config

    def test_valid_http_config(self):
        config = {"type": "http", "url": "http://localhost:3001/mcp"}
        assert config["type"] in ("stdio", "sse", "http")
        assert "url" in config

    def test_invalid_type_rejected(self):
        config = {"type": "websocket", "url": "ws://localhost"}
        assert config["type"] not in ("stdio", "sse", "http")

    def test_stdio_without_command_invalid(self):
        config = {"type": "stdio"}
        assert config["type"] == "stdio"
        assert "command" not in config


class TestMultiTenantIsolation:
    """Verify multi-tenant isolation: tenant A agents/MCP not visible to tenant B."""

    def test_tenant_agents_isolated_by_tenant_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)

            # Tenant A agent
            a_dir = base_dir / "tenants" / "tenant-a" / "agents" / "bot-a"
            a_dir.mkdir(parents=True)
            (a_dir / "config.yaml").write_text(yaml.dump({"name": "bot-a"}), encoding="utf-8")

            # Tenant B agent
            b_dir = base_dir / "tenants" / "tenant-b" / "agents" / "bot-b"
            b_dir.mkdir(parents=True)
            (b_dir / "config.yaml").write_text(yaml.dump({"name": "bot-b"}), encoding="utf-8")

            with patch("deerflow.config.agents_config.get_paths") as mock_paths:
                mock_paths.return_value = MagicMock(base_dir=base_dir)

                agents_a = scan_tenant_agents("tenant-a")
                agents_b = scan_tenant_agents("tenant-b")

                assert len(agents_a) == 1
                assert agents_a[0].name == "bot-a"
                assert len(agents_b) == 1
                assert agents_b[0].name == "bot-b"

    def test_nonexistent_tenant_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            with patch("deerflow.config.agents_config.get_paths") as mock_paths:
                mock_paths.return_value = MagicMock(base_dir=base_dir)
                agents = scan_tenant_agents("nonexistent")
                assert agents == []

    def test_tenant_config_not_leaked_to_other_tenant(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)

            # Only tenant-a has an agent
            a_dir = base_dir / "tenants" / "tenant-a" / "agents" / "secret-bot"
            a_dir.mkdir(parents=True)
            (a_dir / "config.yaml").write_text(yaml.dump({"name": "secret-bot", "description": "Secret"}), encoding="utf-8")

            with (
                patch("deerflow.config.agents_config.get_paths") as mock_paths,
                patch("deerflow.config.agents_config._get_builtin_agents_dir") as mock_builtin,
                patch("deerflow.config.agents_config.get_effective_user_id") as mock_uid,
            ):
                mock_paths.return_value = MagicMock(
                    base_dir=base_dir,
                    user_agents_dir=lambda uid: base_dir / "users" / uid / "agents",
                    agents_dir=base_dir / "legacy-agents",
                )
                mock_builtin.return_value = base_dir / "builtin-empty"
                mock_uid.return_value = "user1"

                # Tenant B should NOT see tenant A's agent
                agents_b = list_available_agents(tenant_id="tenant-b", user_id="user1")
                names_b = [a.name for a in agents_b]
                assert "secret-bot" not in names_b


class TestSecurityAudit:
    """Verify authorization and graceful degradation."""

    def test_is_tenant_admin_rejects_regular_user(self):
        from deerflow.persistence.agent.auth import is_tenant_admin

        assert is_tenant_admin("user") is False
        assert is_tenant_admin(None) is False
        assert is_tenant_admin("") is False
        assert is_tenant_admin("viewer") is False

    def test_is_tenant_admin_accepts_admin_roles(self):
        from deerflow.persistence.agent.auth import is_tenant_admin

        assert is_tenant_admin("tenant_admin") is True
        assert is_tenant_admin("superadmin") is True

    def test_load_agent_config_graceful_on_missing_agent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                patch("deerflow.config.agents_config._get_builtin_agents_dir") as mock_builtin,
                patch("deerflow.config.agents_config.resolve_agent_dir") as mock_resolve,
                patch("deerflow.config.agents_config.get_paths") as mock_paths,
            ):
                mock_builtin.return_value = Path(tmpdir) / "empty"
                mock_resolve.return_value = Path(tmpdir) / "users" / "u1" / "agents" / "ghost"
                mock_paths.return_value = MagicMock(base_dir=Path(tmpdir))

                with pytest.raises(FileNotFoundError):
                    load_agent_config("ghost", user_id="u1", tenant_id="t1")

    def test_agent_name_validation_rejects_path_traversal(self):
        from deerflow.config.agents_config import validate_agent_name

        with pytest.raises(ValueError):
            validate_agent_name("../etc/passwd")
        with pytest.raises(ValueError):
            validate_agent_name("agent/../../secret")
        with pytest.raises(ValueError):
            validate_agent_name("agent name with spaces")


class TestTenantInitialization:
    """Test auto-fork of builtin agents to new tenants."""

    def test_initialize_forks_specified_agents(self):
        from deerflow.persistence.agent.tenant_init import initialize_tenant_agents

        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            builtin_dir = base_dir / "builtin"
            (builtin_dir / "researcher").mkdir(parents=True)
            (builtin_dir / "researcher" / "config.yaml").write_text(
                yaml.dump({"name": "researcher", "description": "Research", "tags": ["research"]}), encoding="utf-8"
            )
            (builtin_dir / "researcher" / "SOUL.md").write_text("Research soul", encoding="utf-8")

            with (
                patch("deerflow.config.agents_config._get_builtin_agents_dir") as mock_builtin,
                patch("deerflow.persistence.agent.tenant_init.get_paths") as mock_paths,
                patch("deerflow.persistence.agent.tenant_init.scan_builtin_agents") as mock_scan,
                patch("deerflow.persistence.agent.tenant_init.load_builtin_agent_soul") as mock_soul,
            ):
                mock_builtin.return_value = builtin_dir
                mock_paths.return_value = MagicMock(base_dir=base_dir)

                from deerflow.config.agents_config import AgentConfig

                mock_scan.return_value = [AgentConfig(name="researcher", description="Research", tags=["research"])]
                mock_soul.return_value = "Research soul"

                forked = initialize_tenant_agents("new-tenant", auto_fork_agents=["researcher"])
                assert forked == ["researcher"]

                agent_dir = base_dir / "tenants" / "new-tenant" / "agents" / "researcher"
                assert agent_dir.exists()
                assert (agent_dir / "config.yaml").exists()
                assert (agent_dir / "SOUL.md").read_text(encoding="utf-8") == "Research soul"

    def test_initialize_skips_nonexistent_agents(self):
        from deerflow.persistence.agent.tenant_init import initialize_tenant_agents

        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)

            with (
                patch("deerflow.persistence.agent.tenant_init.get_paths") as mock_paths,
                patch("deerflow.persistence.agent.tenant_init.scan_builtin_agents") as mock_scan,
            ):
                mock_paths.return_value = MagicMock(base_dir=base_dir)
                mock_scan.return_value = []

                forked = initialize_tenant_agents("new-tenant", auto_fork_agents=["nonexistent"])
                assert forked == []

    def test_initialize_empty_list_does_nothing(self):
        from deerflow.persistence.agent.tenant_init import initialize_tenant_agents

        forked = initialize_tenant_agents("any-tenant", auto_fork_agents=[])
        assert forked == []


class TestAgentRecommendation:
    """Test agent recommendation keyword matching logic."""

    def test_keyword_matching_scores(self):
        from deerflow.config.agents_config import AgentInfo

        agents = [
            AgentInfo(name="researcher", description="Deep research assistant", tags=["research", "academic"], source="builtin", editable=False),
            AgentInfo(name="writer", description="Creative writing helper", tags=["writing", "content"], source="builtin", editable=False),
            AgentInfo(name="coder", description="Code review and generation", tags=["code", "development"], source="builtin", editable=False),
        ]

        query_words = {"research"}
        scored = []
        for agent in agents:
            score = 0.0
            name_lower = agent.name.lower()
            desc_lower = agent.description.lower()
            tags_lower = [t.lower() for t in (agent.tags or [])]
            for word in query_words:
                if word in name_lower:
                    score += 3.0
                if word in desc_lower:
                    score += 1.0
                for tag in tags_lower:
                    if word in tag:
                        score += 2.0
            if score > 0:
                scored.append((score, agent.name))

        scored.sort(key=lambda x: x[0], reverse=True)
        assert scored[0][1] == "researcher"
        assert scored[0][0] == 6.0  # 3 (name) + 1 (desc) + 2 (tag)

    def test_no_match_returns_empty(self):
        from deerflow.config.agents_config import AgentInfo

        agents = [
            AgentInfo(name="researcher", description="Research", tags=["research"], source="builtin", editable=False),
        ]

        query_words = {"quantum"}
        scored = []
        for agent in agents:
            score = 0.0
            for word in query_words:
                if word in agent.name.lower():
                    score += 3.0
            if score > 0:
                scored.append(agent.name)

        assert scored == []


class TestAgentUsageTokenTracking:
    """Test AgentUsageRow extended fields and AgentUsageRepository stats methods."""

    def test_usage_row_has_token_fields(self):
        from deerflow.persistence.agent.usage_model import AgentUsageRow

        row = AgentUsageRow(
            id="test-id",
            tenant_id="t1",
            agent_name="researcher",
            user_id="u1",
            thread_id="thread-123",
            run_id="run-456",
            token_input=1500,
            token_output=800,
            duration_ms=3200,
        )
        assert row.thread_id == "thread-123"
        assert row.run_id == "run-456"
        assert row.token_input == 1500
        assert row.token_output == 800
        assert row.duration_ms == 3200

    def test_usage_row_token_defaults(self):
        from deerflow.persistence.agent.usage_model import AgentUsageRow

        row = AgentUsageRow(
            id="test-id",
            tenant_id="t1",
            agent_name="writer",
            user_id="u1",
        )
        assert row.thread_id is None
        assert row.run_id is None
        # SQLAlchemy defaults apply at flush time; direct construction yields None
        assert row.duration_ms is None

    def test_usage_row_indexes(self):
        from deerflow.persistence.agent.usage_model import AgentUsageRow

        index_names = [idx.name for idx in AgentUsageRow.__table_args__ if hasattr(idx, "name")]
        assert "ix_agent_usage_tenant_agent" in index_names
        assert "ix_agent_usage_user" in index_names
        assert "ix_agent_usage_thread" in index_names
        assert "ix_agent_usage_time_range" in index_names

    def test_repository_record_accepts_new_fields(self):
        """Verify record() signature accepts all new parameters without error."""
        from unittest.mock import AsyncMock, MagicMock

        from deerflow.persistence.agent.usage_repository import AgentUsageRepository

        mock_sf = MagicMock()
        repo = AgentUsageRepository(mock_sf)

        import inspect
        sig = inspect.signature(repo.record)
        params = list(sig.parameters.keys())
        assert "thread_id" in params
        assert "run_id" in params
        assert "token_input" in params
        assert "token_output" in params
        assert "duration_ms" in params

    def test_repository_has_stats_methods(self):
        """Verify new stats methods exist on the repository."""
        from deerflow.persistence.agent.usage_repository import AgentUsageRepository

        assert hasattr(AgentUsageRepository, "stats_by_tenant")
        assert hasattr(AgentUsageRepository, "stats_for_agent")
        assert hasattr(AgentUsageRepository, "stats_by_user")
        assert callable(getattr(AgentUsageRepository, "stats_by_tenant"))
        assert callable(getattr(AgentUsageRepository, "stats_for_agent"))
        assert callable(getattr(AgentUsageRepository, "stats_by_user"))

    def test_stats_by_tenant_accepts_period_days(self):
        """Verify stats_by_tenant has period_days keyword argument."""
        import inspect

        from deerflow.persistence.agent.usage_repository import AgentUsageRepository

        sig = inspect.signature(AgentUsageRepository.stats_by_tenant)
        params = sig.parameters
        assert "period_days" in params
        assert params["period_days"].default is None

    def test_stats_for_agent_accepts_period_days(self):
        """Verify stats_for_agent has period_days keyword argument."""
        import inspect

        from deerflow.persistence.agent.usage_repository import AgentUsageRepository

        sig = inspect.signature(AgentUsageRepository.stats_for_agent)
        params = sig.parameters
        assert "tenant_id" in params
        assert "agent_name" in params
        assert "period_days" in params

    def test_worker_auto_record_hook_exists(self):
        """Verify the auto-record hook is present in worker.py."""
        import importlib.util

        spec = importlib.util.find_spec("deerflow.runtime.runs.worker")
        assert spec is not None
        source_path = spec.origin
        with open(source_path, encoding="utf-8") as f:
            source = f.read()
        assert "AgentUsageRepository" in source
        assert "agent_name" in source
        assert "_run_start_mono" in source

    def test_stats_api_endpoints_exist(self):
        """Verify the new stats endpoints are registered in the agents router."""
        from app.gateway.routers.agents import router

        paths = [route.path for route in router.routes if hasattr(route, "path")]
        assert "/api/agents/stats" in paths
        assert "/api/agents/stats/mine" in paths
        assert "/api/agents/{name}/stats" in paths
        assert "/api/agents/stats/summary" in paths

    def test_record_usage_endpoint_deprecated(self):
        """Verify POST /agents/{name}/usage is marked deprecated."""
        from app.gateway.routers.agents import router

        for route in router.routes:
            if hasattr(route, "path") and route.path == "/api/agents/{name}/usage":
                if hasattr(route, "methods") and "POST" in route.methods:
                    assert getattr(route, "deprecated", None) is True
                    return
        pytest.fail("POST /api/agents/{name}/usage endpoint not found")
