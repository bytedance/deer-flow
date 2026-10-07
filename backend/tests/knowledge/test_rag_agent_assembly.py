"""Tests for the built-in ``rag`` custom agent assembly (spec §5.1 / §4.7).

The rag agent ships as read-only built-in assets (``deerflow/agents/assets/rag/``)
that ``load_agent_config`` / ``load_agent_soul`` fall back to when the user has
no per-user copy — a user edit writes the per-user directory and shadows the
built-in. Its tools are restricted to the ``rag`` group, which is ``opt_in``:
the default lead agent (no agent_name) never sees them.
"""

from __future__ import annotations

import pytest
import yaml

from deerflow.config.agents_config import load_agent_config, load_agent_soul
from deerflow.config.app_config import AppConfig
from deerflow.tools.tools import get_available_tools

FRESH_USER = "assembly-test-user-that-never-exists"


@pytest.fixture
def app_config() -> AppConfig:
    """AppConfig built from config.example.yaml (carries the rag tool registrations)."""
    from pathlib import Path

    data = yaml.safe_load((Path(__file__).parents[3] / "config.example.yaml").read_text(encoding="utf-8"))
    return AppConfig(**{key: value for key, value in data.items() if key in AppConfig.model_fields})


def test_builtin_rag_config_loads_with_rag_tool_group():
    config = load_agent_config("rag", user_id=FRESH_USER)

    assert config is not None
    assert config.name == "rag"
    assert config.tool_groups == ["rag"]
    assert config.skills == []
    assert config.model_settings is not None
    assert config.model_settings.temperature == 0.1


def test_builtin_rag_soul_contains_citation_and_refusal_rules():
    soul = load_agent_soul("rag", user_id=FRESH_USER)

    assert soul is not None
    assert "[n]" in soul, "citation format rule missing"
    assert "禁止一句多标" in soul, "citation overload discipline missing (phase-2 batch-1 P2)"
    assert "citation_no" in soul, "marks must copy the evidence's citation_no (shared numbering space)"
    assert "不要在回答末尾输出引用清单" in soul, "the redundant trailing reference list must be banned (the structured sources strip covers it)"
    assert "不向用户解释检索过程" in soul, "meta-commentary about retrieval quality must be banned (mainstream products stay silent)"
    assert "知识库中没有找到相关内容" in soul, "refusal policy missing"
    assert "hybrid_search" in soul
    # Vector-floor discipline: enumerated discretion, not open-ended "upgrade as
    # needed" — every factual question must hit hybrid_search at least once.
    assert "任何事实性问题必须至少调用一次" in soul, "vector-floor rule missing"


def test_rag_group_tools_are_exactly_the_retrieval_tool(app_config):
    tools = get_available_tools(groups=["rag"], include_mcp=False, app_config=app_config)
    names = {tool.name for tool in tools}

    assert "hybrid_search" in names
    assert not {"web_search", "bash", "ls", "read_file", "write_file"} & names


def test_default_tool_resolution_excludes_opt_in_rag_tools(app_config):
    """The default lead agent (groups=None) must NOT pick up the rag group."""
    tools = get_available_tools(groups=None, include_mcp=False, app_config=app_config)
    names = {tool.name for tool in tools}

    assert "hybrid_search" not in names


def test_user_shadow_config_overrides_builtin(tmp_path, monkeypatch):
    """A per-user rag/config.yaml wins over the built-in assets (shadow semantics)."""
    from deerflow.config.paths import Paths

    paths = Paths(base_dir=tmp_path)
    agent_dir = paths.user_agent_dir(FRESH_USER, "rag")
    agent_dir.mkdir(parents=True)
    (agent_dir / "config.yaml").write_text("name: rag\ndescription: 用户自定义版\ntool_groups:\n  - web\n", encoding="utf-8")
    (agent_dir / "SOUL.md").write_text("用户自定义灵魂", encoding="utf-8")
    monkeypatch.setattr("deerflow.config.agents_config.get_paths", lambda: paths)

    config = load_agent_config("rag", user_id=FRESH_USER)
    assert config is not None
    assert config.description == "用户自定义版"
    assert config.tool_groups == ["web"]
    assert load_agent_soul("rag", user_id=FRESH_USER) == "用户自定义灵魂"
