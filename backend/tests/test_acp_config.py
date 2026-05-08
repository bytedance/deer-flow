"""Unit tests for ACP agent configuration."""

import json

import pytest
import yaml
from pydantic import ValidationError

from deerflow.config.acp_config import ACPAgentConfig
from deerflow.config.app_config import AppConfig


def test_acp_agent_config_defaults():
    cfg = ACPAgentConfig(command="my-agent", description="My agent")
    assert cfg.args == []
    assert cfg.env == {}
    assert cfg.model is None
    assert cfg.auto_approve_permissions is False


def test_acp_agent_config_env_literal():
    cfg = ACPAgentConfig(command="my-agent", description="desc", env={"OPENAI_API_KEY": "sk-test"})
    assert cfg.env == {"OPENAI_API_KEY": "sk-test"}


def test_acp_agent_config_env_default_is_empty():
    cfg = ACPAgentConfig(command="my-agent", description="desc")
    assert cfg.env == {}


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


def test_app_config_parses_acp_agents():
    config = AppConfig.model_validate(
        {
            "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
            "models": [
                {"name": "test-model", "use": "langchain_openai:ChatOpenAI", "model": "gpt-test"},
            ],
            "acp_agents": {
                "claude_code": {"command": "claude-code-acp", "args": [], "description": "Claude Code"},
                "codex": {
                    "command": "codex-acp",
                    "args": ["--flag"],
                    "description": "Codex CLI",
                    "env": {"OPENAI_API_KEY": "$OPENAI_API_KEY"},
                },
            },
        }
    )
    assert set(config.acp_agents) == {"claude_code", "codex"}
    assert config.acp_agents["claude_code"].command == "claude-code-acp"
    assert config.acp_agents["codex"].args == ["--flag"]
    assert config.acp_agents["codex"].env == {"OPENAI_API_KEY": "$OPENAI_API_KEY"}


def test_app_config_acp_agents_default_empty():
    config = AppConfig.model_validate(
        {
            "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
            "models": [
                {"name": "test-model", "use": "langchain_openai:ChatOpenAI", "model": "gpt-test"},
            ],
        }
    )
    assert config.acp_agents == {}


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
    cfg1 = AppConfig.from_file(str(config_path))
    assert set(cfg1.acp_agents) == {"codex"}

    config_path.write_text(yaml.safe_dump(config_without_acp), encoding="utf-8")
    cfg2 = AppConfig.from_file(str(config_path))
    assert cfg2.acp_agents == {}
