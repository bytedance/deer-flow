"""Tests for tenant-isolated agent CRUD operations."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from deerflow.config.agents_config import (
    AGENT_NAME_PATTERN,
    AgentConfig,
    load_agent_config,
    load_agent_soul,
    list_custom_agents,
)
from deerflow.config.paths import Paths
from deerflow.config.tenant import (
    _DEFAULT_TENANT_ID,
    get_current_tenant_id,
    reset_tenant_id,
    set_current_tenant_id,
)


class TestAgentNamePattern:
    def test_valid_names(self):
        for name in ["my-agent", "test", "agent-123", "a", "ab", "support-bot"]:
            assert AGENT_NAME_PATTERN.match(name), f"Should accept: {name!r}"

    def test_invalid_names(self):
        for name in ["", "../escape", "has space", "has/slash", "with_underscore"]:
            assert not AGENT_NAME_PATTERN.match(name), f"Should reject: {name!r}"


class TestAgentIsolation:
    def test_same_agent_name_different_tenants_separate_dirs(self, tmp_path):
        paths = Paths(base_dir=tmp_path)

        token_a = set_current_tenant_id("tenant-a")
        try:
            dir_a = paths.agent_dir("my-agent")
        finally:
            reset_tenant_id(token_a)

        token_b = set_current_tenant_id("tenant-b")
        try:
            dir_b = paths.agent_dir("my-agent")
        finally:
            reset_tenant_id(token_b)

        assert dir_a != dir_b
        assert str(dir_a).endswith("tenant-a/agents/my-agent".replace("/", "\\") if "\\" in str(dir_a) else "tenant-a/agents/my-agent")
        assert str(dir_b).endswith("tenant-b/agents/my-agent".replace("/", "\\") if "\\" in str(dir_b) else "tenant-b/agents/my-agent")

    def test_agent_memory_file_isolated_per_tenant(self, tmp_path):
        paths = Paths(base_dir=tmp_path)

        token_a = set_current_tenant_id("tenant-a")
        try:
            mem_a = paths.agent_memory_file("my-agent")
        finally:
            reset_tenant_id(token_a)

        token_b = set_current_tenant_id("tenant-b")
        try:
            mem_b = paths.agent_memory_file("my-agent")
        finally:
            reset_tenant_id(token_b)

        assert mem_a != mem_b

    def test_default_tenant_uses_flat_layout(self, tmp_path):
        paths = Paths(base_dir=tmp_path)
        assert paths.agent_dir("my-agent") == tmp_path / "agents" / "my-agent"
        assert "tenants" not in str(paths.agent_dir("my-agent"))


class TestLoadAgentConfig:
    def test_loads_from_tenant_dir(self, tmp_path):
        agent_dir = tmp_path / "tenants" / "acme" / "agents" / "test-agent"
        agent_dir.mkdir(parents=True)
        config_data = "name: test-agent\ndescription: A test agent\n"
        (agent_dir / "config.yaml").write_text(config_data)

        paths = Paths(base_dir=tmp_path)
        with patch("deerflow.config.agents_config.get_paths", return_value=paths):
            token = set_current_tenant_id("acme")
            try:
                config = load_agent_config("test-agent")
                assert config is not None
                assert config.name == "test-agent"
            finally:
                reset_tenant_id(token)

    def test_returns_none_for_missing_agent(self, tmp_path):
        paths = Paths(base_dir=tmp_path)
        with patch("deerflow.config.agents_config.get_paths", return_value=paths):
            token = set_current_tenant_id("acme")
            try:
                with pytest.raises(FileNotFoundError, match="Agent directory not found"):
                    load_agent_config("nonexistent")
            finally:
                reset_tenant_id(token)


class TestLoadAgentSoul:
    def test_loads_from_tenant_dir(self, tmp_path):
        agent_dir = tmp_path / "tenants" / "acme" / "agents" / "test-agent"
        agent_dir.mkdir(parents=True)
        (agent_dir / "SOUL.md").write_text("# Soul of test-agent")

        paths = Paths(base_dir=tmp_path)
        with patch("deerflow.config.agents_config.get_paths", return_value=paths):
            token = set_current_tenant_id("acme")
            try:
                soul = load_agent_soul("test-agent")
                assert soul is not None
                assert "Soul of test-agent" in soul
            finally:
                reset_tenant_id(token)

    def test_returns_none_for_missing_soul(self, tmp_path):
        paths = Paths(base_dir=tmp_path)
        with patch("deerflow.config.agents_config.get_paths", return_value=paths):
            token = set_current_tenant_id("acme")
            try:
                soul = load_agent_soul("nonexistent")
                assert soul is None
            finally:
                reset_tenant_id(token)


class TestListCustomAgents:
    def test_lists_only_current_tenant_agents(self, tmp_path):
        agent_dir_a = tmp_path / "tenants" / "tenant-a" / "agents" / "agent-a"
        agent_dir_a.mkdir(parents=True)
        (agent_dir_a / "config.yaml").write_text("name: agent-a")

        agent_dir_b = tmp_path / "tenants" / "tenant-b" / "agents" / "agent-b"
        agent_dir_b.mkdir(parents=True)
        (agent_dir_b / "config.yaml").write_text("name: agent-b")

        paths = Paths(base_dir=tmp_path)
        with patch("deerflow.config.agents_config.get_paths", return_value=paths):
            token = set_current_tenant_id("tenant-a")
            try:
                agents = list_custom_agents()
                names = [a.name for a in agents]
                assert "agent-a" in names
                assert "agent-b" not in names
            finally:
                reset_tenant_id(token)

    def test_empty_when_no_agents(self, tmp_path):
        paths = Paths(base_dir=tmp_path)
        with patch("deerflow.config.agents_config.get_paths", return_value=paths):
            token = set_current_tenant_id("empty-tenant")
            try:
                agents = list_custom_agents()
                assert agents == []
            finally:
                reset_tenant_id(token)
