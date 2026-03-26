"""Unit tests for ACP agent configuration."""

import json

import pytest
import yaml
from pydantic import ValidationError

from deerflow.config.acp_config import ACPAgentConfig, get_acp_agents, load_acp_config_from_dict
from deerflow.config.app_config import AppConfig


def setup_function():
    """Reset ACP config before each test."""
    load_acp_config_from_dict({})


def test_load_acp_config_sets_agents():
    load_acp_config_from_dict(
        {
            "claude_code": {
                "command": "claude-code-acp",
                "args": [],
                "description": "Claude Code for coding tasks",
                "model": None,
            }
        }
    )
    agents = get_acp_agents()
    assert "claude_code" in agents
    assert agents["claude_code"].command == "claude-code-acp"
    assert agents["claude_code"].description == "Claude Code for coding tasks"
    assert agents["claude_code"].model is None


def test_load_acp_config_multiple_agents():
    load_acp_config_from_dict(
        {
            "claude_code": {"command": "claude-code-acp", "args": [], "description": "Claude Code"},
            "codex": {"command": "codex-acp", "args": ["--flag"], "description": "Codex CLI"},
        }
    )
    agents = get_acp_agents()
    assert len(agents) == 2
    assert agents["codex"].args == ["--flag"]


def test_load_acp_config_empty_clears_agents():
    load_acp_config_from_dict({"agent": {"command": "cmd", "args": [], "description": "desc"}})
    assert len(get_acp_agents()) == 1

    load_acp_config_from_dict({})
    assert len(get_acp_agents()) == 0


def test_load_acp_config_none_clears_agents():
    load_acp_config_from_dict({"agent": {"command": "cmd", "args": [], "description": "desc"}})
    assert len(get_acp_agents()) == 1

    load_acp_config_from_dict(None)
    assert get_acp_agents() == {}


def test_acp_agent_config_defaults():
    cfg = ACPAgentConfig(command="my-agent", description="My agent")
    assert cfg.args == []
    assert cfg.model is None
    assert cfg.auto_approve_permissions is False


def test_acp_agent_config_with_model():
    cfg = ACPAgentConfig(command="my-agent", description="desc", model="claude-opus-4")
    assert cfg.model == "claude-opus-4"


def test_acp_agent_config_auto_approve_permissions():
    """P1.2: auto_approve_permissions can be explicitly enabled."""
    cfg = ACPAgentConfig(command="my-agent", description="desc", auto_approve_permissions=True)
    assert cfg.auto_approve_permissions is True


def test_acp_agent_config_missing_command_raises():
    with pytest.raises(ValidationError):
        ACPAgentConfig(description="No command provided")


def test_acp_agent_config_missing_description_raises():
    with pytest.raises(ValidationError):
        ACPAgentConfig(command="my-agent")


def test_get_acp_agents_returns_empty_by_default():
    """After clearing, should return empty dict."""
    load_acp_config_from_dict({})
    assert get_acp_agents() == {}


def test_app_config_reload_without_acp_agents_clears_previous_state(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    extensions_path = tmp_path / "extensions_config.json"
    extensions_path.write_text(json.dumps({"mcpServers": {}, "skills": {}}), encoding="utf-8")

    config_with_acp = {
        "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
        "models": [
            {
                "name": "test-model",
                "use": "langchain_openai:ChatOpenAI",
                "model": "gpt-test",
            }
        ],
        "acp_agents": {
            "codex": {
                "command": "codex-acp",
                "args": [],
                "description": "Codex CLI",
            }
        },
    }
    config_without_acp = {
        "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
        "models": [
            {
                "name": "test-model",
                "use": "langchain_openai:ChatOpenAI",
                "model": "gpt-test",
            }
        ],
    }

    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))

    config_path.write_text(yaml.safe_dump(config_with_acp), encoding="utf-8")
    AppConfig.from_file(str(config_path))
    assert set(get_acp_agents()) == {"codex"}

    config_path.write_text(yaml.safe_dump(config_without_acp), encoding="utf-8")
    AppConfig.from_file(str(config_path))
    assert get_acp_agents() == {}
