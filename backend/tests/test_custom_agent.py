"""Tests for custom agent support."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_paths(base_dir: Path):
    """Return a Paths instance pointing to base_dir."""
    from deerflow.config.paths import Paths

    return Paths(base_dir=base_dir)


def _write_agent(base_dir: Path, name: str, config: dict, soul: str = "You are helpful.") -> None:
    """Write an agent directory with config.yaml and SOUL.md."""
    agent_dir = base_dir / "agents" / name
    agent_dir.mkdir(parents=True, exist_ok=True)

    config_copy = dict(config)
    if "name" not in config_copy:
        config_copy["name"] = name

    with open(agent_dir / "config.yaml", "w") as f:
        yaml.dump(config_copy, f)

    (agent_dir / "SOUL.md").write_text(soul, encoding="utf-8")


# ===========================================================================
# 1. Paths class – agent path methods
# ===========================================================================


class TestPaths:
    def test_agents_dir(self, tmp_path):
        paths = _make_paths(tmp_path)
        assert paths.agents_dir == tmp_path / "agents"

    def test_agent_dir(self, tmp_path):
        paths = _make_paths(tmp_path)
        assert paths.agent_dir("code-reviewer") == tmp_path / "agents" / "code-reviewer"

    def test_agent_memory_file(self, tmp_path):
        paths = _make_paths(tmp_path)
        assert paths.agent_memory_file("code-reviewer") == tmp_path / "agents" / "code-reviewer" / "memory.json"

    def test_user_md_file(self, tmp_path):
        paths = _make_paths(tmp_path)
        assert paths.user_md_file == tmp_path / "USER.md"

    def test_paths_are_different_from_global(self, tmp_path):
        paths = _make_paths(tmp_path)
        assert paths.memory_file != paths.agent_memory_file("my-agent")
        assert paths.memory_file == tmp_path / "memory.json"
        assert paths.agent_memory_file("my-agent") == tmp_path / "agents" / "my-agent" / "memory.json"


# ===========================================================================
# 2. AgentConfig – Pydantic parsing
# ===========================================================================


class TestAgentConfig:
    def test_minimal_config(self):
        from deerflow.config.agents_config import AgentConfig

        cfg = AgentConfig(name="my-agent")
        assert cfg.name == "my-agent"
        assert cfg.description == ""
        assert cfg.model is None
        assert cfg.tool_groups is None

    def test_full_config(self):
        from deerflow.config.agents_config import AgentConfig

        cfg = AgentConfig(
            name="code-reviewer",
            description="Specialized for code review",
            model="deepseek-v3",
            tool_groups=["file:read", "bash"],
        )
        assert cfg.name == "code-reviewer"
        assert cfg.model == "deepseek-v3"
        assert cfg.tool_groups == ["file:read", "bash"]

    def test_full_config_with_display_name(self):
        from deerflow.config.agents_config import AgentConfig

        cfg = AgentConfig(
            name="code-reviewer",
            display_name="代码审查",
            description="Specialized for code review",
        )
        assert cfg.name == "code-reviewer"
        assert cfg.display_name == "代码审查"
        assert cfg.description == "Specialized for code review"

    def test_config_from_dict(self):
        from deerflow.config.agents_config import AgentConfig

        data = {"name": "test-agent", "description": "A test", "model": "gpt-4"}
        cfg = AgentConfig(**data)
        assert cfg.name == "test-agent"
        assert cfg.model == "gpt-4"
        assert cfg.tool_groups is None


# ===========================================================================
# 3. load_agent_config
# ===========================================================================


class TestLoadAgentConfig:
    def test_load_valid_config(self, tmp_path):
        config_dict = {"name": "code-reviewer", "description": "Code review agent", "model": "deepseek-v3"}
        _write_agent(tmp_path, "code-reviewer", config_dict)

        with patch("deerflow.config.agents_config.get_paths", return_value=_make_paths(tmp_path)):
            from deerflow.config.agents_config import load_agent_config

            cfg = load_agent_config("code-reviewer")

        assert cfg.name == "code-reviewer"
        assert cfg.description == "Code review agent"
        assert cfg.model == "deepseek-v3"

    def test_load_valid_config_with_display_name(self, tmp_path):
        config_dict = {
            "name": "code-reviewer",
            "display_name": "代码审查",
            "description": "Code review agent",
        }
        _write_agent(tmp_path, "code-reviewer", config_dict)

        with patch("deerflow.config.agents_config.get_paths", return_value=_make_paths(tmp_path)):
            from deerflow.config.agents_config import load_agent_config

            cfg = load_agent_config("code-reviewer")

        assert cfg.name == "code-reviewer"
        assert cfg.display_name == "代码审查"
        assert cfg.description == "Code review agent"

    def test_load_missing_agent_raises(self, tmp_path):
        with patch("deerflow.config.agents_config.get_paths", return_value=_make_paths(tmp_path)):
            from deerflow.config.agents_config import load_agent_config

            with pytest.raises(FileNotFoundError):
                load_agent_config("nonexistent-agent")

    def test_load_missing_config_yaml_raises(self, tmp_path):
        # Create directory without config.yaml
        (tmp_path / "agents" / "broken-agent").mkdir(parents=True)

        with patch("deerflow.config.agents_config.get_paths", return_value=_make_paths(tmp_path)):
            from deerflow.config.agents_config import load_agent_config

            with pytest.raises(FileNotFoundError):
                load_agent_config("broken-agent")

    def test_get_agent_display_name_missing_agent_returns_none(self, tmp_path):
        with patch("deerflow.config.agents_config.get_paths", return_value=_make_paths(tmp_path)):
            from deerflow.config.agents_config import get_agent_display_name

            assert get_agent_display_name("missing-agent") is None

    def test_get_agent_display_name_invalid_agent_returns_none(self, tmp_path):
        with patch("deerflow.config.agents_config.get_paths", return_value=_make_paths(tmp_path)):
            from deerflow.config.agents_config import get_agent_display_name

            assert get_agent_display_name("bad agent") is None


class TestSetupAgentTool:
    def test_setup_agent_normalizes_display_name(self, tmp_path):
        paths_instance = _make_paths(tmp_path)

        with patch("deerflow.tools.builtins.setup_agent_tool.get_paths", return_value=paths_instance):
            from deerflow.tools.builtins.setup_agent_tool import setup_agent

            runtime = MagicMock(
                context={
                    "agent_name": "code-reviewer",
                    "agent_display_name": "  代码助手  ",
                },
                tool_call_id="tc-1",
            )

            setup_agent.func("Soul", "Reviews code", runtime=runtime)

        config_data = yaml.safe_load((tmp_path / "agents" / "code-reviewer" / "config.yaml").read_text(encoding="utf-8"))
        assert config_data["display_name"] == "代码助手"

    def test_setup_agent_rejects_invalid_display_name(self, tmp_path):
        paths_instance = _make_paths(tmp_path)

        with patch("deerflow.tools.builtins.setup_agent_tool.get_paths", return_value=paths_instance):
            from deerflow.tools.builtins.setup_agent_tool import setup_agent

            runtime = MagicMock(
                context={
                    "agent_name": "code-reviewer",
                    "agent_display_name": "   ",
                },
                tool_call_id="tc-2",
            )

            result = setup_agent.func("Soul", "Reviews code", runtime=runtime)

        assert "Display name must be a non-empty string." in result.update["messages"][0].content
        assert not (tmp_path / "agents" / "code-reviewer").exists()

    def test_load_config_infers_name_from_dir(self, tmp_path):
        """Config without 'name' field should use directory name."""
        agent_dir = tmp_path / "agents" / "inferred-name"
        agent_dir.mkdir(parents=True)
        (agent_dir / "config.yaml").write_text("description: My agent\n")
        (agent_dir / "SOUL.md").write_text("Hello")

        with patch("deerflow.config.agents_config.get_paths", return_value=_make_paths(tmp_path)):
            from deerflow.config.agents_config import load_agent_config

            cfg = load_agent_config("inferred-name")

        assert cfg.name == "inferred-name"

    def test_load_config_with_tool_groups(self, tmp_path):
        config_dict = {"name": "restricted", "tool_groups": ["file:read", "file:write"]}
        _write_agent(tmp_path, "restricted", config_dict)

        with patch("deerflow.config.agents_config.get_paths", return_value=_make_paths(tmp_path)):
            from deerflow.config.agents_config import load_agent_config

            cfg = load_agent_config("restricted")

        assert cfg.tool_groups == ["file:read", "file:write"]

    def test_load_config_with_skills_empty_list(self, tmp_path):
        config_dict = {"name": "no-skills-agent", "skills": []}
        _write_agent(tmp_path, "no-skills-agent", config_dict)

        with patch("deerflow.config.agents_config.get_paths", return_value=_make_paths(tmp_path)):
            from deerflow.config.agents_config import load_agent_config

            cfg = load_agent_config("no-skills-agent")

        assert cfg.skills == []

    def test_load_config_with_skills_omitted(self, tmp_path):
        config_dict = {"name": "default-skills-agent"}
        _write_agent(tmp_path, "default-skills-agent", config_dict)

        with patch("deerflow.config.agents_config.get_paths", return_value=_make_paths(tmp_path)):
            from deerflow.config.agents_config import load_agent_config

            cfg = load_agent_config("default-skills-agent")

        assert cfg.skills is None

    def test_legacy_prompt_file_field_ignored(self, tmp_path):
        """Unknown fields like the old prompt_file should be silently ignored."""
        agent_dir = tmp_path / "agents" / "legacy-agent"
        agent_dir.mkdir(parents=True)
        (agent_dir / "config.yaml").write_text("name: legacy-agent\nprompt_file: system.md\n")
        (agent_dir / "SOUL.md").write_text("Soul content")

        with patch("deerflow.config.agents_config.get_paths", return_value=_make_paths(tmp_path)):
            from deerflow.config.agents_config import load_agent_config

            cfg = load_agent_config("legacy-agent")

        assert cfg.name == "legacy-agent"


# ===========================================================================
# 4. load_agent_soul
# ===========================================================================


class TestLoadAgentSoul:
    def test_reads_soul_file(self, tmp_path):
        expected_soul = "You are a specialized code review expert."
        _write_agent(tmp_path, "code-reviewer", {"name": "code-reviewer"}, soul=expected_soul)

        with patch("deerflow.config.agents_config.get_paths", return_value=_make_paths(tmp_path)):
            from deerflow.config.agents_config import AgentConfig, load_agent_soul

            cfg = AgentConfig(name="code-reviewer")
            soul = load_agent_soul(cfg.name)

        assert soul == expected_soul

    def test_missing_soul_file_returns_none(self, tmp_path):
        agent_dir = tmp_path / "agents" / "no-soul"
        agent_dir.mkdir(parents=True)
        (agent_dir / "config.yaml").write_text("name: no-soul\n")
        # No SOUL.md created

        with patch("deerflow.config.agents_config.get_paths", return_value=_make_paths(tmp_path)):
            from deerflow.config.agents_config import AgentConfig, load_agent_soul

            cfg = AgentConfig(name="no-soul")
            soul = load_agent_soul(cfg.name)

        assert soul is None

    def test_empty_soul_file_returns_none(self, tmp_path):
        agent_dir = tmp_path / "agents" / "empty-soul"
        agent_dir.mkdir(parents=True)
        (agent_dir / "config.yaml").write_text("name: empty-soul\n")
        (agent_dir / "SOUL.md").write_text("   \n   ")

        with patch("deerflow.config.agents_config.get_paths", return_value=_make_paths(tmp_path)):
            from deerflow.config.agents_config import AgentConfig, load_agent_soul

            cfg = AgentConfig(name="empty-soul")
            soul = load_agent_soul(cfg.name)

        assert soul is None


# ===========================================================================
# 5. list_custom_agents
# ===========================================================================


class TestListCustomAgents:
    def test_empty_when_no_agents_dir(self, tmp_path):
        with patch("deerflow.config.agents_config.get_paths", return_value=_make_paths(tmp_path)):
            from deerflow.config.agents_config import list_custom_agents

            agents = list_custom_agents()

        assert agents == []

    def test_discovers_multiple_agents(self, tmp_path):
        _write_agent(tmp_path, "agent-a", {"name": "agent-a"})
        _write_agent(tmp_path, "agent-b", {"name": "agent-b", "description": "B"})

        with patch("deerflow.config.agents_config.get_paths", return_value=_make_paths(tmp_path)):
            from deerflow.config.agents_config import list_custom_agents

            agents = list_custom_agents()

        names = [a.name for a in agents]
        assert "agent-a" in names
        assert "agent-b" in names

    def test_skips_dirs_without_config_yaml(self, tmp_path):
        # Valid agent
        _write_agent(tmp_path, "valid-agent", {"name": "valid-agent"})
        # Invalid dir (no config.yaml)
        (tmp_path / "agents" / "invalid-dir").mkdir(parents=True)

        with patch("deerflow.config.agents_config.get_paths", return_value=_make_paths(tmp_path)):
            from deerflow.config.agents_config import list_custom_agents

            agents = list_custom_agents()

        assert len(agents) == 1
        assert agents[0].name == "valid-agent"

    def test_skips_non_directory_entries(self, tmp_path):
        # Create the agents dir with a file (not a dir)
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "not-a-dir.txt").write_text("hello")
        _write_agent(tmp_path, "real-agent", {"name": "real-agent"})

        with patch("deerflow.config.agents_config.get_paths", return_value=_make_paths(tmp_path)):
            from deerflow.config.agents_config import list_custom_agents

            agents = list_custom_agents()

        assert len(agents) == 1
        assert agents[0].name == "real-agent"

    def test_returns_sorted_by_name(self, tmp_path):
        _write_agent(tmp_path, "z-agent", {"name": "z-agent"})
        _write_agent(tmp_path, "a-agent", {"name": "a-agent"})
        _write_agent(tmp_path, "m-agent", {"name": "m-agent"})

        with patch("deerflow.config.agents_config.get_paths", return_value=_make_paths(tmp_path)):
            from deerflow.config.agents_config import list_custom_agents

            agents = list_custom_agents()

        names = [a.name for a in agents]
        assert names == sorted(names)


# ===========================================================================
# 7. Memory isolation: _get_memory_file_path
# ===========================================================================


class TestMemoryFilePath:
    def test_global_memory_path(self, tmp_path):
        """None agent_name should return global memory file."""
        from deerflow.agents.memory.storage import FileMemoryStorage
        from deerflow.config.memory_config import MemoryConfig

        with (
            patch("deerflow.agents.memory.storage.get_paths", return_value=_make_paths(tmp_path)),
            patch("deerflow.agents.memory.storage.get_memory_config", return_value=MemoryConfig(storage_path="")),
        ):
            storage = FileMemoryStorage()
            path = storage._get_memory_file_path(None)
        assert path == tmp_path / "memory.json"

    def test_agent_memory_path(self, tmp_path):
        """Providing agent_name should return per-agent memory file."""
        from deerflow.agents.memory.storage import FileMemoryStorage
        from deerflow.config.memory_config import MemoryConfig

        with (
            patch("deerflow.agents.memory.storage.get_paths", return_value=_make_paths(tmp_path)),
            patch("deerflow.agents.memory.storage.get_memory_config", return_value=MemoryConfig(storage_path="")),
        ):
            storage = FileMemoryStorage()
            path = storage._get_memory_file_path("code-reviewer")
        assert path == tmp_path / "agents" / "code-reviewer" / "memory.json"

    def test_different_paths_for_different_agents(self, tmp_path):
        from deerflow.agents.memory.storage import FileMemoryStorage
        from deerflow.config.memory_config import MemoryConfig

        with (
            patch("deerflow.agents.memory.storage.get_paths", return_value=_make_paths(tmp_path)),
            patch("deerflow.agents.memory.storage.get_memory_config", return_value=MemoryConfig(storage_path="")),
        ):
            storage = FileMemoryStorage()
            path_global = storage._get_memory_file_path(None)
            path_a = storage._get_memory_file_path("agent-a")
            path_b = storage._get_memory_file_path("agent-b")

        assert path_global != path_a
        assert path_global != path_b
        assert path_a != path_b


# ===========================================================================
# 8. Gateway API – Agents endpoints
# ===========================================================================


def _make_test_app(tmp_path: Path):
    """Create a FastAPI app with the agents router, patching paths to tmp_path."""
    from fastapi import FastAPI

    from app.gateway.routers.agents import router

    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture()
def agent_client(tmp_path):
    """TestClient with agents router, using tmp_path as base_dir."""
    paths_instance = _make_paths(tmp_path)

    with patch("deerflow.config.agents_config.get_paths", return_value=paths_instance), patch("app.gateway.routers.agents.get_paths", return_value=paths_instance):
        app = _make_test_app(tmp_path)
        with TestClient(app) as client:
            client._tmp_path = tmp_path  # type: ignore[attr-defined]
            yield client


class TestAgentsAPI:
    def test_list_agents_empty(self, agent_client):
        response = agent_client.get("/api/agents")
        assert response.status_code == 200
        data = response.json()
        assert data["agents"] == []

    def test_create_agent(self, agent_client):
        payload = {
            "name": "code-reviewer",
            "description": "Reviews code",
            "soul": "You are a code reviewer.",
        }
        response = agent_client.post("/api/agents", json=payload)
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "code-reviewer"
        assert data["description"] == "Reviews code"
        assert data["soul"] == "You are a code reviewer."
        assert data["display_name"] == "code-reviewer"

    def test_check_agent_display_name_generates_slug(self, agent_client):
        response = agent_client.get("/api/agents/check", params={"display_name": "代码助手"})
        assert response.status_code == 200
        data = response.json()
        assert data["available"] is True
        assert data["display_name"] == "代码助手"
        assert data["name"] == "agent"

    def test_create_agent_with_display_name_only(self, agent_client, tmp_path):
        payload = {
            "display_name": "代码助手",
            "description": "中文展示名",
            "soul": "You are a helpful assistant.",
        }
        response = agent_client.post("/api/agents", json=payload)
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "agent"
        assert data["display_name"] == "代码助手"
        assert data["description"] == "中文展示名"

        config_data = yaml.safe_load((tmp_path / "agents" / "agent" / "config.yaml").read_text(encoding="utf-8"))
        assert config_data["name"] == "agent"
        assert config_data["display_name"] == "代码助手"

    def test_create_agent_invalid_name(self, agent_client):
        payload = {"name": "Code Reviewer!", "soul": "test"}
        response = agent_client.post("/api/agents", json=payload)
        assert response.status_code == 422

    def test_create_duplicate_agent_409(self, agent_client):
        payload = {"name": "my-agent", "soul": "test"}
        agent_client.post("/api/agents", json=payload)

        # Second create should fail
        response = agent_client.post("/api/agents", json=payload)
        assert response.status_code == 409

    def test_create_duplicate_agent_display_name_409(self, agent_client):
        agent_client.post("/api/agents", json={"display_name": "代码助手", "soul": "first"})
        response = agent_client.post("/api/agents", json={"display_name": "代码助手", "soul": "second"})
        assert response.status_code == 409

    def test_list_agents_after_create(self, agent_client):
        agent_client.post("/api/agents", json={"name": "agent-one", "soul": "p1"})
        agent_client.post("/api/agents", json={"name": "agent-two", "soul": "p2"})

        response = agent_client.get("/api/agents")
        assert response.status_code == 200
        names = [a["name"] for a in response.json()["agents"]]
        assert "agent-one" in names
        assert "agent-two" in names

    def test_get_agent(self, agent_client):
        agent_client.post("/api/agents", json={"name": "test-agent", "soul": "Hello world"})

        response = agent_client.get("/api/agents/test-agent")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "test-agent"
        assert data["soul"] == "Hello world"
        assert data["display_name"] == "test-agent"

    def test_get_missing_agent_404(self, agent_client):
        response = agent_client.get("/api/agents/nonexistent")
        assert response.status_code == 404

    def test_update_agent_soul(self, agent_client):
        agent_client.post("/api/agents", json={"name": "update-me", "soul": "original"})

        response = agent_client.put("/api/agents/update-me", json={"soul": "updated"})
        assert response.status_code == 200
        assert response.json()["soul"] == "updated"

    def test_update_agent_description(self, agent_client):
        agent_client.post("/api/agents", json={"name": "desc-agent", "description": "old desc", "soul": "p"})

        response = agent_client.put("/api/agents/desc-agent", json={"description": "new desc"})
        assert response.status_code == 200
        assert response.json()["description"] == "new desc"

    def test_update_agent_display_name(self, agent_client):
        agent_client.post("/api/agents", json={"name": "desc-agent", "soul": "p"})

        response = agent_client.put("/api/agents/desc-agent", json={"display_name": "代码审查"})
        assert response.status_code == 200
        assert response.json()["display_name"] == "代码审查"

    def test_update_missing_agent_404(self, agent_client):
        response = agent_client.put("/api/agents/ghost-agent", json={"soul": "new"})
        assert response.status_code == 404

    def test_delete_agent(self, agent_client):
        agent_client.post("/api/agents", json={"name": "del-me", "soul": "bye"})

        response = agent_client.delete("/api/agents/del-me")
        assert response.status_code == 204

        # Verify it's gone
        response = agent_client.get("/api/agents/del-me")
        assert response.status_code == 404

    def test_delete_missing_agent_404(self, agent_client):
        response = agent_client.delete("/api/agents/does-not-exist")
        assert response.status_code == 404

    def test_create_agent_with_model_and_tool_groups(self, agent_client):
        payload = {
            "name": "specialized",
            "description": "Specialized agent",
            "model": "deepseek-v3",
            "tool_groups": ["file:read", "bash"],
            "soul": "You are specialized.",
        }
        response = agent_client.post("/api/agents", json=payload)
        assert response.status_code == 201
        data = response.json()
        assert data["model"] == "deepseek-v3"
        assert data["tool_groups"] == ["file:read", "bash"]
        assert data["display_name"] == "specialized"

    def test_create_persists_files_on_disk(self, agent_client, tmp_path):
        agent_client.post("/api/agents", json={"name": "disk-check", "soul": "disk soul"})

        agent_dir = tmp_path / "agents" / "disk-check"
        assert agent_dir.exists()
        assert (agent_dir / "config.yaml").exists()
        assert (agent_dir / "SOUL.md").exists()
        assert (agent_dir / "SOUL.md").read_text() == "disk soul"

    def test_delete_removes_files_from_disk(self, agent_client, tmp_path):
        agent_client.post("/api/agents", json={"name": "remove-me", "soul": "bye"})
        agent_dir = tmp_path / "agents" / "remove-me"
        assert agent_dir.exists()

        agent_client.delete("/api/agents/remove-me")
        assert not agent_dir.exists()


class TestAssistantsCompat:
    def test_custom_agent_uses_display_name_for_assistant_name(self, tmp_path):
        _write_agent(
            tmp_path,
            "code-reviewer",
            {
                "name": "code-reviewer",
                "display_name": "代码审查",
                "description": "Reviews code",
            },
        )

        with patch("deerflow.config.agents_config.get_paths", return_value=_make_paths(tmp_path)):
            from app.gateway.routers.assistants_compat import _list_assistants

            assistants = _list_assistants()

        assistant = next(item for item in assistants if item.assistant_id == "code-reviewer")
        assert assistant.assistant_id == "code-reviewer"
        assert assistant.name == "代码审查"
        assert assistant.description == "Reviews code"


# ===========================================================================
# 9. Gateway API – User Profile endpoints
# ===========================================================================


class TestUserProfileAPI:
    def test_get_user_profile_empty(self, agent_client):
        response = agent_client.get("/api/user-profile")
        assert response.status_code == 200
        assert response.json()["content"] is None

    def test_put_user_profile(self, agent_client, tmp_path):
        content = "# User Profile\n\nI am a developer."
        response = agent_client.put("/api/user-profile", json={"content": content})
        assert response.status_code == 200
        assert response.json()["content"] == content

        # File should be written to disk
        user_md = tmp_path / "USER.md"
        assert user_md.exists()
        assert user_md.read_text(encoding="utf-8") == content

    def test_get_user_profile_after_put(self, agent_client):
        content = "# Profile\n\nI work on data science."
        agent_client.put("/api/user-profile", json={"content": content})

        response = agent_client.get("/api/user-profile")
        assert response.status_code == 200
        assert response.json()["content"] == content

    def test_put_empty_user_profile_returns_none(self, agent_client):
        response = agent_client.put("/api/user-profile", json={"content": ""})
        assert response.status_code == 200
        assert response.json()["content"] is None
