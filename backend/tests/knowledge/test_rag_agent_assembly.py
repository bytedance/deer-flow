"""Tests for the built-in ``rag`` custom agent assembly (spec §5.1 / §4.7).

The rag agent ships as read-only built-in assets (``deerflow/agents/assets/rag/``)
that ``load_agent_config`` / ``load_agent_soul`` fall back to when the user has
no per-user copy — a user edit writes the per-user directory and shadows the
built-in. Its tools are restricted to the ``rag`` group, which is ``opt_in``:
the default lead agent (no agent_name) never sees them. Deep-research mode is
a middleware-level dynamic injection: ``context.deep_research=true`` adds the
mandatory three-path instruction per run while SOUL.md stays static.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import yaml
from langchain_core.messages import HumanMessage, ToolMessage

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
    assert "不向用户解释检索过程与路由行为" in soul, "meta-commentary about retrieval routing/source quality must be banned (mainstream products stay silent)"
    assert "知识库中没有找到相关内容" in soul, "refusal policy missing"
    assert "hybrid_search" in soul and "wiki_search" in soul and "graph_search" in soul
    assert "深度检索" in soul, "static dual-mode guidance missing"
    # Vector-floor discipline: enumerated discretion, not open-ended "upgrade as
    # needed" — every factual question must hit hybrid_search at least once;
    # the ONLY skip case is a pure concept-definition question, and a wiki
    # miss must fall back to hybrid_search.
    assert "任何事实性问题必须至少调用一次" in soul, "vector-floor rule missing"
    assert "纯概念定义题" in soul, "the sole wiki-only exception must be enumerated"
    assert "回补" in soul, "wiki-miss fallback to hybrid_search missing"


def test_rag_group_tools_are_exactly_the_three_retrieval_tools(app_config):
    tools = get_available_tools(groups=["rag"], include_mcp=False, app_config=app_config)
    names = {tool.name for tool in tools}

    assert {"hybrid_search", "wiki_search", "graph_search"} <= names
    assert not {"web_search", "bash", "ls", "read_file", "write_file"} & names


def test_default_tool_resolution_excludes_opt_in_rag_tools(app_config):
    """The default lead agent (groups=None) must NOT pick up the rag group."""
    tools = get_available_tools(groups=None, include_mcp=False, app_config=app_config)
    names = {tool.name for tool in tools}

    assert not {"hybrid_search", "wiki_search", "graph_search"} & names


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


# ── deep-research middleware (spec §4.7 soft enforcement) ────────────────

from langchain.agents.middleware.types import ModelRequest  # noqa: E402


def _request(messages, **context) -> ModelRequest:
    return ModelRequest(model=object(), messages=list(messages), state={"messages": list(messages)}, runtime=SimpleNamespace(context=context))


def _call(middleware, request) -> ModelRequest:
    captured: dict[str, ModelRequest] = {}

    def handler(req):
        captured["request"] = req
        return []

    middleware.wrap_model_call(request, handler)
    return captured["request"]


def test_deep_research_middleware_injects_three_path_instruction_when_enabled():
    from deerflow.agents.middlewares.deep_research_middleware import DeepResearchMiddleware

    request = _request([HumanMessage(content="DeerFlow 的检索架构是怎样的？")], deep_research=True)
    forwarded = _call(DeepResearchMiddleware(), request)

    assert forwarded is not request, "deep_research=true must override the request with the injected instruction"
    injected = forwarded.messages[-1]
    assert "wiki_search" in injected.content
    assert "graph_search" in injected.content
    assert "必须" in injected.content
    # The injected instruction is model-facing plumbing: without hide_from_ui
    # the run journal mistakes it for the user's input (first_human_message)
    # and the frontend renders it as a user bubble.
    assert injected.additional_kwargs.get("hide_from_ui") is True, "injected instruction must be hidden from UI surfaces"


def test_deep_research_middleware_noop_without_flag():
    from deerflow.agents.middlewares.deep_research_middleware import DeepResearchMiddleware

    middleware = DeepResearchMiddleware()
    assert _call(middleware, _request([HumanMessage(content="q")])).messages[-1].content == "q"
    assert _call(middleware, _request([HumanMessage(content="q")], deep_research=False)).messages[-1].content == "q"


def test_deep_research_middleware_does_not_double_inject_mid_tool_loop():
    """Only the first model call after a user turn gets the instruction — tool-loop iterations skip it."""
    from deerflow.agents.middlewares.deep_research_middleware import DeepResearchMiddleware

    request = _request(
        [HumanMessage(content="q"), ToolMessage(content="tool result", tool_call_id="call-1")],
        deep_research=True,
    )
    forwarded = _call(DeepResearchMiddleware(), request)

    assert forwarded is request, "mid-tool-loop calls must not be re-injected"


def test_rag_agent_mounts_deep_research_middleware():
    """The middleware must be in the rag agent's chain, not the default agent's."""
    from deerflow.agents.lead_agent.agent import _extra_agent_middlewares
    from deerflow.agents.middlewares.deep_research_middleware import DeepResearchMiddleware

    assert any(isinstance(m, DeepResearchMiddleware) for m in _extra_agent_middlewares("rag"))
    assert not any(isinstance(m, DeepResearchMiddleware) for m in _extra_agent_middlewares(None))
    assert not any(isinstance(m, DeepResearchMiddleware) for m in _extra_agent_middlewares("other-agent"))
