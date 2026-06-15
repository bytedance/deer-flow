"""Tests for StarterConfig and AgentConfig.starters."""

from __future__ import annotations

import yaml

from deerflow.config.agents_config import AgentConfig, StarterConfig, to_agent_info


class TestStarterConfig:
    def test_minimal_starter(self):
        s = StarterConfig(label="Go", prompt="start")
        assert s.label == "Go"
        assert s.prompt == "start"
        assert s.icon is None
        assert s.auto_start is False

    def test_full_starter(self):
        s = StarterConfig(label="日报", prompt="生成日报", icon="📋", auto_start=True)
        assert s.auto_start is True
        assert s.icon == "📋"

    def test_serialization(self):
        s = StarterConfig(label="Go", prompt="start", auto_start=True)
        d = s.model_dump()
        assert d == {"label": "Go", "prompt": "start", "icon": None, "auto_start": True}


class TestAgentConfigStarters:
    def test_no_starters(self):
        cfg = AgentConfig(name="test")
        assert cfg.starters is None

    def test_with_starters(self):
        cfg = AgentConfig(
            name="test",
            starters=[
                StarterConfig(label="Go", prompt="start", auto_start=True),
                StarterConfig(label="Help", prompt="help"),
            ],
        )
        assert len(cfg.starters) == 2
        assert cfg.starters[0].auto_start is True
        assert cfg.starters[1].auto_start is False

    def test_yaml_parsing(self):
        yaml_str = """
name: test-agent
description: A test agent
starters:
  - label: "生成日报"
    prompt: "生成日报"
    auto_start: true
  - label: "查看历史"
    prompt: "列出报告"
"""
        data = yaml.safe_load(yaml_str)
        known_fields = set(AgentConfig.model_fields.keys())
        data = {k: v for k, v in data.items() if k in known_fields}
        cfg = AgentConfig(**data)
        assert cfg.starters is not None
        assert len(cfg.starters) == 2
        assert cfg.starters[0].auto_start is True
        assert cfg.starters[0].label == "生成日报"

    def test_starters_not_filtered_by_whitelist(self):
        data = {
            "name": "test",
            "starters": [{"label": "Go", "prompt": "start"}],
            "unknown_field": "should_be_dropped",
        }
        known_fields = set(AgentConfig.model_fields.keys())
        filtered = {k: v for k, v in data.items() if k in known_fields}
        assert "starters" in filtered
        assert "unknown_field" not in filtered
        cfg = AgentConfig(**filtered)
        assert cfg.starters is not None


class TestAgentInfoStarters:
    def test_to_agent_info_with_starters(self):
        cfg = AgentConfig(
            name="daily",
            starters=[StarterConfig(label="Go", prompt="start", auto_start=True)],
        )
        info = to_agent_info(cfg, source="builtin", editable=False)
        assert info.starters is not None
        assert len(info.starters) == 1
        assert info.starters[0].auto_start is True

    def test_to_agent_info_without_starters(self):
        cfg = AgentConfig(name="plain")
        info = to_agent_info(cfg)
        assert info.starters is None
