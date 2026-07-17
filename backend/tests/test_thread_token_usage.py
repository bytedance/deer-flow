"""Tests for thread-level token usage aggregation API."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient
from langchain_core.messages import HumanMessage, SystemMessage

from app.gateway import context_usage
from app.gateway.context_usage import build_context_usage_payload
from app.gateway.routers import thread_runs


def _aggregate_result() -> dict:
    return {
        "total_tokens": 150,
        "total_input_tokens": 90,
        "total_output_tokens": 60,
        "total_runs": 2,
        "by_model": {"unknown": {"tokens": 150, "runs": 2}},
        "by_caller": {
            "lead_agent": 120,
            "subagent": 25,
            "middleware": 5,
        },
    }


def _make_run_store(*, model_name: str | None = None) -> MagicMock:
    run_store = MagicMock()
    run_store.aggregate_tokens_by_thread = AsyncMock(return_value=_aggregate_result())
    run_store.list_by_thread = AsyncMock(
        return_value=[{"model_name": model_name}] if model_name is not None else [],
    )
    return run_store


def _make_app(run_store: MagicMock):
    app = make_authed_test_app()
    app.include_router(thread_runs.router)
    app.state.run_store = run_store
    return app


# ---------------------------------------------------------------------------
# Endpoint smoke tests — verify the response shape and that `build_context_usage`
# is exercised. The detailed breakdown logic lives in
# ``app.gateway.context_usage`` and is tested in isolation below.
# ---------------------------------------------------------------------------


def test_thread_token_usage_returns_stable_shape(monkeypatch):
    """Baseline shape — ``context_usage`` block is included (possibly null)."""

    async def _stub(_request, _thread_id, _run_store):
        return None

    monkeypatch.setattr(thread_runs, "build_context_usage", _stub)

    run_store = MagicMock()
    run_store.aggregate_tokens_by_thread = AsyncMock(return_value=_aggregate_result())
    app = _make_app(run_store)

    with TestClient(app) as client:
        response = client.get("/api/threads/thread-1/token-usage")

    assert response.status_code == 200
    payload = response.json()
    assert payload["context_usage"] is None
    assert payload["total_tokens"] == 150
    run_store.aggregate_tokens_by_thread.assert_awaited_once_with("thread-1")


def test_thread_token_usage_can_include_active_runs(monkeypatch):
    async def _stub(_request, _thread_id, _run_store):
        return None

    monkeypatch.setattr(thread_runs, "build_context_usage", _stub)

    run_store = MagicMock()
    run_store.aggregate_tokens_by_thread = AsyncMock(
        return_value={
            "total_tokens": 175,
            "total_input_tokens": 120,
            "total_output_tokens": 55,
            "total_runs": 3,
            "by_model": {"unknown": {"tokens": 175, "runs": 3}},
            "by_caller": {
                "lead_agent": 145,
                "subagent": 25,
                "middleware": 5,
            },
        },
    )
    app = _make_app(run_store)

    with TestClient(app) as client:
        response = client.get("/api/threads/thread-1/token-usage?include_active=true")

    assert response.status_code == 200
    assert response.json()["total_tokens"] == 175
    run_store.aggregate_tokens_by_thread.assert_awaited_once_with("thread-1", include_active=True)


def test_thread_token_usage_serialises_breakdown(monkeypatch):
    """End-to-end: a populated breakdown round-trips through Pydantic."""

    async def _stub(_request, _thread_id, _run_store):
        return {
            "max_context_tokens": 1000,
            "used_tokens": 300,
            "percentage": 30.0,
            "breakdown": [
                {"key": "messages", "tokens": 200, "active": True},
                {"key": "system_prompt", "tokens": 100, "active": True},
                {"key": "free_space", "tokens": 700, "active": False},
            ],
        }

    monkeypatch.setattr(thread_runs, "build_context_usage", _stub)

    run_store = _make_run_store(model_name=None)
    app = _make_app(run_store)

    with TestClient(app) as client:
        response = client.get("/api/threads/thread-1/token-usage")

    payload = response.json()["context_usage"]
    assert payload["max_context_tokens"] == 1000
    assert payload["used_tokens"] == 300
    assert payload["percentage"] == 30.0
    assert [row["key"] for row in payload["breakdown"]] == [
        "messages",
        "system_prompt",
        "free_space",
    ]


# ---------------------------------------------------------------------------
# Unit tests for the payload builder — pure-data, no FastAPI plumbing.
# ---------------------------------------------------------------------------


def _kwargs(**overrides) -> dict:
    defaults = dict(
        max_context_tokens=None,
        messages_tokens=0,
        system_prompt_tokens=0,
        skills_tokens=0,
        custom_agents_tokens=0,
        memory_tokens=0,
        system_tools_active=0,
        mcp_tools_active=0,
        mcp_tools_deferred=0,
        summarization_trigger=None,
    )
    defaults.update(overrides)
    return defaults


def test_payload_omits_zero_categories():
    payload = build_context_usage_payload(**_kwargs(messages_tokens=120))
    keys = [row["key"] for row in payload["breakdown"]]
    assert keys == ["messages"]
    assert payload["used_tokens"] == 120
    assert payload["max_context_tokens"] is None
    assert payload["percentage"] is None


def test_payload_percentage_and_free_space_with_window():
    payload = build_context_usage_payload(
        **_kwargs(
            max_context_tokens=1000,
            messages_tokens=200,
            system_prompt_tokens=80,
            skills_tokens=20,
        )
    )
    rows = {row["key"]: row for row in payload["breakdown"]}
    assert payload["used_tokens"] == 300
    assert payload["percentage"] == 30.0
    assert rows["free_space"]["tokens"] == 700
    assert rows["free_space"]["active"] is False
    # Active rows feed the percentage; free_space does not.
    assert rows["messages"]["active"] is True
    assert rows["system_prompt"]["active"] is True


def test_payload_orders_rows_canonically():
    payload = build_context_usage_payload(
        **_kwargs(
            max_context_tokens=10000,
            messages_tokens=1000,
            system_tools_active=500,
            system_prompt_tokens=400,
            skills_tokens=300,
            mcp_tools_active=200,
            custom_agents_tokens=100,
            memory_tokens=50,
            mcp_tools_deferred=80,
            summarization_trigger=8000,
        )
    )
    keys = [row["key"] for row in payload["breakdown"]]
    assert keys == [
        "messages",
        "system_tools",
        "system_prompt",
        "skills",
        "mcp_tools",
        "custom_agents",
        "memory_files",
        "mcp_tools_deferred",
        "autocompact_buffer",
        "free_space",
    ]


def test_payload_autocompact_buffer_uses_window_minus_trigger():
    payload = build_context_usage_payload(
        **_kwargs(
            max_context_tokens=20000,
            messages_tokens=100,
            summarization_trigger=15000,
        )
    )
    rows = {row["key"]: row for row in payload["breakdown"]}
    assert rows["autocompact_buffer"]["tokens"] == 5000
    assert rows["autocompact_buffer"]["active"] is False


def test_payload_drops_autocompact_when_trigger_missing():
    payload = build_context_usage_payload(**_kwargs(max_context_tokens=20000, messages_tokens=100))
    keys = [row["key"] for row in payload["breakdown"]]
    assert "autocompact_buffer" not in keys


def test_payload_drops_autocompact_when_trigger_exceeds_window():
    """Misconfigured trigger > window must not produce a negative buffer."""
    payload = build_context_usage_payload(
        **_kwargs(
            max_context_tokens=10000,
            messages_tokens=100,
            summarization_trigger=15000,
        )
    )
    keys = [row["key"] for row in payload["breakdown"]]
    assert "autocompact_buffer" not in keys


def test_payload_drops_free_space_when_window_missing():
    payload = build_context_usage_payload(**_kwargs(messages_tokens=500, skills_tokens=100))
    keys = [row["key"] for row in payload["breakdown"]]
    assert "free_space" not in keys


def test_payload_clamps_free_space_to_zero_when_over_budget():
    """If active items already exceed the window, free_space is 0 (not negative)."""
    payload = build_context_usage_payload(
        **_kwargs(
            max_context_tokens=100,
            messages_tokens=200,
        )
    )
    keys = [row["key"] for row in payload["breakdown"]]
    assert "free_space" not in keys  # zero rows are filtered out
    # Percentage can exceed 100 — that is the honest signal of over-budget.
    assert payload["percentage"] == 200.0


def test_payload_marks_deferred_rows_inactive():
    payload = build_context_usage_payload(
        **_kwargs(
            max_context_tokens=10000,
            messages_tokens=100,
            mcp_tools_deferred=500,
        )
    )
    rows = {row["key"]: row for row in payload["breakdown"]}
    assert rows["mcp_tools_deferred"]["active"] is False
    # Deferred items must not feed the percentage.
    assert payload["used_tokens"] == 100
    assert payload["percentage"] == 1.0


# ---------------------------------------------------------------------------
# Tests for the internal helpers (model resolution + summarization trigger).
# ---------------------------------------------------------------------------


def test_summarization_trigger_picks_tokens_type():
    config = SimpleNamespace(
        summarization=SimpleNamespace(
            enabled=True,
            trigger=[
                {"type": "messages", "value": 10},
                {"type": "tokens", "value": 12345},
            ],
        ),
    )
    assert context_usage._summarization_trigger_tokens(config) == 12345


def test_summarization_trigger_accepts_single_context_size():
    from deerflow.config.summarization_config import ContextSize

    config = SimpleNamespace(
        summarization=SimpleNamespace(
            enabled=True,
            trigger=ContextSize(type="tokens", value=4000),
        ),
    )

    assert context_usage._summarization_trigger_tokens(config) == 4000


def test_summarization_trigger_returns_none_when_disabled():
    config = SimpleNamespace(
        summarization=SimpleNamespace(
            enabled=False,
            trigger=[{"type": "tokens", "value": 12345}],
        ),
    )
    assert context_usage._summarization_trigger_tokens(config) is None


# ---------------------------------------------------------------------------
# Tests for deferred-tool derivation + tool/prompt helpers.
#
# These exercise the code paths the original PR left untested: the lazy imports
# inside `_split_tools` / `_count_system_prompt` previously raised
# (ImportError / TypeError) and were swallowed by the surrounding try/except,
# silently zeroing whole breakdown rows.
# ---------------------------------------------------------------------------


def _make_tool(name: str, *, mcp: bool = False) -> SimpleNamespace:
    tool = SimpleNamespace(name=name, description=f"tool {name}")
    tool.metadata = {"deerflow_mcp": True} if mcp else {}
    # A short, deterministic schema-ish body so _approx_tool_schema_tokens
    # falls into its except branch and counts name + description.
    return tool


def test_context_usage_import_targets_follow_current_harness_layout():
    """Regression: harness refactors must fail CI instead of zeroing rows silently."""
    from deerflow.agents.memory.backends.deermem.deermem.core.prompt import _count_tokens
    from deerflow.skills.tool_policy import ALWAYS_AVAILABLE_BUILTIN_TOOL_NAMES

    assert callable(_count_tokens)
    assert "read_file" in ALWAYS_AVAILABLE_BUILTIN_TOOL_NAMES


def test_compute_deferred_tool_names_empty_when_disabled(monkeypatch):
    """tool_search disabled -> no deferred tools, regardless of MCP cache."""
    import deerflow.tools.mcp_metadata as mcp_meta  # noqa: F401

    monkeypatch.setattr(
        "deerflow.mcp.cache.get_cached_mcp_tools",
        lambda: [_make_tool("mcp_a", mcp=True), _make_tool("mcp_b", mcp=True)],
    )
    config = SimpleNamespace(tool_search=SimpleNamespace(enabled=False))
    assert context_usage._compute_deferred_tool_names(config) == frozenset()


def test_compute_deferred_tool_names_picks_mcp_when_enabled(monkeypatch):
    monkeypatch.setattr(
        "deerflow.mcp.cache.get_cached_mcp_tools",
        lambda: [_make_tool("mcp_a", mcp=True), _make_tool("mcp_b", mcp=True)],
    )
    config = SimpleNamespace(tool_search=SimpleNamespace(enabled=True))
    assert context_usage._compute_deferred_tool_names(config) == frozenset({"mcp_a", "mcp_b"})


def test_split_tools_classifies_deferred_mcp_when_enabled(monkeypatch):
    """With tool_search on, MCP tools go to *_deferred; system tools to system_tools."""
    monkeypatch.setattr(
        "deerflow.tools.tools.get_available_tools",
        lambda **_: [_make_tool("bash", mcp=False), _make_tool("mcp_a", mcp=True)],
    )
    config = SimpleNamespace(
        subagents=SimpleNamespace(enabled=False),
        tool_search=SimpleNamespace(enabled=True),
    )
    system_active, mcp_active, mcp_deferred = context_usage._split_tools(config, None)
    assert system_active > 0  # bash counted as active system tool
    assert mcp_active == 0  # no MCP tool is active — all are deferred
    assert mcp_deferred > 0  # mcp_a counted as deferred MCP tool


def test_split_tools_classifies_mcp_active_when_disabled(monkeypatch):
    """With tool_search off, MCP tools are NOT deferred — they bind as active."""
    monkeypatch.setattr(
        "deerflow.tools.tools.get_available_tools",
        lambda **_: [_make_tool("mcp_a", mcp=True)],
    )
    config = SimpleNamespace(
        subagents=SimpleNamespace(enabled=False),
        tool_search=SimpleNamespace(enabled=False),
    )
    system_active, mcp_active, mcp_deferred = context_usage._split_tools(config, None)
    assert mcp_active > 0
    assert mcp_deferred == 0


def test_split_tools_counts_promoted_mcp_as_active(monkeypatch):
    """A thread-promoted MCP tool has its schema bound -> counts as active, not deferred.

    Hash scoping is exercised separately (``_effective_promoted_names``); here we
    stub it so the classification logic is tested in isolation from the catalog
    hashing that needs real ``BaseTool`` objects.
    """
    monkeypatch.setattr(
        "deerflow.tools.tools.get_available_tools",
        lambda **_: [_make_tool("mcp_a", mcp=True), _make_tool("mcp_b", mcp=True)],
    )
    monkeypatch.setattr(context_usage, "_effective_promoted_names", lambda _promoted, _mcp: frozenset({"mcp_a"}))
    config = SimpleNamespace(
        subagents=SimpleNamespace(enabled=False),
        tool_search=SimpleNamespace(enabled=True),
    )
    # mcp_a was promoted in this thread; mcp_b is still deferred.
    system_active, mcp_active, mcp_deferred = context_usage._split_tools(
        config,
        None,
        promoted={"catalog_hash": "x", "names": ["mcp_a"]},
    )
    assert mcp_active > 0  # mcp_a now active
    assert mcp_deferred > 0  # mcp_b still deferred
    assert system_active == 0


def test_effective_promoted_names_scoped_by_catalog_hash(monkeypatch):
    """Names apply only when the persisted hash matches the current catalog hash."""

    class _FakeCatalog:
        def __init__(self, tools):
            pass

        @property
        def hash(self):
            return "current_hash"

    monkeypatch.setattr("deerflow.tools.builtins.tool_search.DeferredToolCatalog", _FakeCatalog)
    promoted = {"catalog_hash": "current_hash", "names": ["mcp_a", "mcp_b", "mcp_a", ""]}
    # deduped; empty/non-string entries dropped.
    assert context_usage._effective_promoted_names(promoted, [object()]) == frozenset({"mcp_a", "mcp_b"})


def test_effective_promoted_names_empty_on_catalog_drift(monkeypatch):
    """Hash mismatch (MCP config changed) -> promotion invalidated, nothing active."""

    class _FakeCatalog:
        def __init__(self, tools):
            pass

        @property
        def hash(self):
            return "new_hash"

    monkeypatch.setattr("deerflow.tools.builtins.tool_search.DeferredToolCatalog", _FakeCatalog)
    promoted = {"catalog_hash": "stale_hash", "names": ["mcp_a"]}
    assert context_usage._effective_promoted_names(promoted, [object()]) == frozenset()


def test_effective_promoted_names_conservative_on_hash_failure(monkeypatch):
    """If the current hash cannot be recomputed, treat nothing as promoted."""

    def _boom(_tools):
        raise RuntimeError("nope")

    monkeypatch.setattr("deerflow.tools.builtins.tool_search.DeferredToolCatalog", _boom)
    promoted = {"catalog_hash": "h", "names": ["mcp_a"]}
    assert context_usage._effective_promoted_names(promoted, [object()]) == frozenset()


def test_effective_promoted_names_handles_missing_or_malformed():
    assert context_usage._effective_promoted_names(None, []) == frozenset()
    assert context_usage._effective_promoted_names({}, []) == frozenset()
    assert context_usage._effective_promoted_names({"names": ["x"]}, []) == frozenset()  # no hash
    assert context_usage._effective_promoted_names({"catalog_hash": "h"}, []) == frozenset()  # no names
    assert context_usage._effective_promoted_names({"catalog_hash": "h", "names": []}, []) == frozenset()


@pytest.mark.asyncio
async def test_load_checkpoint_messages_returns_raw_promoted_entry():
    """The raw promoted dict (with catalog_hash) is returned for later hash scoping."""
    from langchain_core.messages import HumanMessage

    msg = HumanMessage(content="hi")
    promoted = {"catalog_hash": "abc", "names": ["mcp_a", "mcp_b", "mcp_a"]}

    class _Tuple:
        checkpoint = {"channel_values": {"messages": [msg], "promoted": promoted}}

    class _Chk:
        async def aget_tuple(self, _config):
            return _Tuple()

    messages, result, checkpoint_id = await context_usage._load_checkpoint_messages(_Chk(), "t1")
    assert messages == [msg]
    assert result == promoted  # raw, untouched; dedup happens in _effective_promoted_names
    assert checkpoint_id.startswith("snapshot:")


@pytest.mark.asyncio
async def test_load_checkpoint_messages_returns_none_when_missing():
    """No promoted channel (or non-dict) -> None."""

    class _Tuple:
        checkpoint = {"channel_values": {"messages": []}}

    class _Chk:
        async def aget_tuple(self, _config):
            return _Tuple()

    _messages, promoted, checkpoint_id = await context_usage._load_checkpoint_messages(_Chk(), "t1")
    assert promoted is None
    assert checkpoint_id.startswith("snapshot:")


@pytest.mark.asyncio
async def test_load_checkpoint_messages_uses_checkpoint_id():
    class _Tuple:
        checkpoint = {"id": "checkpoint-7", "channel_values": {"messages": []}}

    class _Chk:
        async def aget_tuple(self, _config):
            return _Tuple()

    _messages, _promoted, checkpoint_id = await context_usage._load_checkpoint_messages(_Chk(), "t1")

    assert checkpoint_id == "checkpoint-7"


def test_count_system_prompt_returns_nonzero(monkeypatch):
    """Regression: the broken kwarg raised TypeError, swallowed to 0.

    With the fix, ``apply_prompt_template`` is called with the correct
    ``deferred_names`` argument and the row is non-zero for any non-empty
    prompt.
    """

    def _fake_apply(**kwargs):
        # Ensure deferred_names is accepted (was the regression trigger).
        assert "deferred_names" in kwargs
        return "x" * 400  # 400 chars -> 100 tokens

    monkeypatch.setattr(
        "deerflow.agents.lead_agent.prompt.apply_prompt_template",
        _fake_apply,
    )
    monkeypatch.setattr(
        "deerflow.agents.lead_agent.prompt.get_skills_prompt_section",
        lambda **_: "",
    )
    config = SimpleNamespace(
        subagents=None,
        tool_search=SimpleNamespace(enabled=False),
    )
    tokens = context_usage._count_system_prompt(config)
    assert tokens == 100  # would be 0 if the TypeError were still swallowed


def test_count_system_prompt_reuses_precomputed_section_counts(monkeypatch):
    monkeypatch.setattr(
        "deerflow.agents.lead_agent.prompt.apply_prompt_template",
        lambda **_: "x" * 400,
    )
    monkeypatch.setattr(
        "deerflow.agents.lead_agent.prompt.get_skills_prompt_section",
        MagicMock(side_effect=AssertionError("skills rendered twice")),
    )
    monkeypatch.setattr(
        context_usage,
        "_count_subagent_section",
        MagicMock(side_effect=AssertionError("subagents rendered twice")),
    )
    config = SimpleNamespace(
        subagents=None,
        tool_search=SimpleNamespace(enabled=False),
    )

    tokens = context_usage._count_system_prompt(
        config,
        skills_tokens=10,
        subagent_tokens=20,
    )

    assert tokens == 70


def test_count_skills_section_forwards_deferred_skill_names(monkeypatch):
    render = MagicMock(return_value="skill-index")
    monkeypatch.setattr(
        "deerflow.agents.lead_agent.prompt.get_skills_prompt_section",
        render,
    )
    config = _config_with_counting("approximate")
    skill_names = frozenset({"review", "research"})

    assert (
        context_usage._count_skills_section(
            config,
            {"review", "research"},
            "user-1",
            skill_names=skill_names,
        )
        > 0
    )
    render.assert_called_once_with(
        available_skills={"review", "research"},
        app_config=config,
        user_id="user-1",
        skill_names=skill_names,
    )


def test_count_subagent_section_uses_configured_total_limit(monkeypatch):
    render = MagicMock(return_value="subagents")
    monkeypatch.setattr(
        "deerflow.agents.lead_agent.prompt._build_subagent_section",
        render,
    )
    config = SimpleNamespace(
        subagents=SimpleNamespace(
            enabled=True,
            max_concurrent_subagents=3,
            max_total_per_run=11,
        ),
        token_usage=None,
    )

    assert context_usage._count_subagent_section(config) > 0
    render.assert_called_once_with(3, 11, app_config=config)


def test_count_system_prompt_forwards_current_agent_build_inputs(monkeypatch):
    render = MagicMock(return_value="x" * 400)
    monkeypatch.setattr(
        "deerflow.agents.lead_agent.prompt.apply_prompt_template",
        render,
    )
    config = _config_with_counting("approximate")
    config.subagents = SimpleNamespace(enabled=True, max_concurrent_subagents=3, max_total_per_run=6)
    config.tool_search = SimpleNamespace(enabled=True)
    skill_names = frozenset({"review"})
    deferred_names = frozenset({"mcp_search"})

    assert (
        context_usage._count_system_prompt(
            config,
            subagent_enabled=True,
            max_concurrent_subagents=4,
            max_total_subagents=9,
            skills_tokens=10,
            subagent_tokens=20,
            skill_names=skill_names,
            deferred_names=deferred_names,
            mcp_routing_hints_section="routing hints",
        )
        == 70
    )
    assert render.call_args.kwargs["max_total_subagents"] == 9
    assert render.call_args.kwargs["skill_names"] == skill_names
    assert render.call_args.kwargs["deferred_names"] == deferred_names
    assert render.call_args.kwargs["mcp_routing_hints_section"] == "routing hints"


def test_build_context_skill_setup_filters_custom_agent_allowlist(monkeypatch):
    enabled_skills = [SimpleNamespace(name="review"), SimpleNamespace(name="research")]
    monkeypatch.setattr(
        "deerflow.agents.lead_agent.prompt.get_enabled_skills_for_config",
        lambda _config, user_id=None: enabled_skills,
    )
    describe_tool = object()
    build_setup = MagicMock(
        return_value=SimpleNamespace(
            skill_names=frozenset({"review"}),
            describe_skill_tool=describe_tool,
        )
    )
    monkeypatch.setattr(
        "deerflow.skills.describe.build_skill_search_setup",
        build_setup,
    )
    config = SimpleNamespace(
        skills=SimpleNamespace(
            deferred_discovery=True,
            container_path="/mnt/skills",
        )
    )

    skill_names, resolved_tool = context_usage._build_context_skill_setup(
        config,
        {"review"},
        "user-1",
    )

    assert skill_names == frozenset({"review"})
    assert resolved_tool is describe_tool
    build_setup.assert_called_once_with(
        [enabled_skills[0]],
        enabled=True,
        container_base_path="/mnt/skills",
    )


def test_build_context_tool_setup_mirrors_lead_agent_static_tools(monkeypatch):
    bash_tool = _make_tool("bash")
    mcp_tool = _make_tool("mcp_search", mcp=True)
    update_tool = _make_tool("update_agent")
    tool_search = _make_tool("tool_search")
    describe_tool = _make_tool("describe_skill")
    memory_tool = _make_tool("memory_search")
    get_tools = MagicMock(return_value=[bash_tool, mcp_tool])
    monkeypatch.setattr("deerflow.tools.tools.get_available_tools", get_tools)
    monkeypatch.setattr("deerflow.tools.builtins.update_agent", update_tool)
    assemble = MagicMock(
        return_value=(
            [bash_tool, mcp_tool, update_tool, tool_search],
            SimpleNamespace(deferred_names=frozenset({"mcp_search"})),
        )
    )
    monkeypatch.setattr(
        "deerflow.tools.builtins.tool_search.assemble_deferred_tools",
        assemble,
    )
    routing_hints = MagicMock(return_value="routing hints")
    monkeypatch.setattr(
        "deerflow.tools.builtins.tool_search.get_mcp_routing_hints_prompt_section",
        routing_hints,
    )
    monkeypatch.setattr(
        "deerflow.config.memory_config.should_use_memory_tools",
        lambda _config: True,
    )
    monkeypatch.setattr(
        "deerflow.agents.memory.tools.get_memory_tools",
        lambda: [memory_tool],
    )
    config = SimpleNamespace(
        tool_search=SimpleNamespace(enabled=True),
        memory=SimpleNamespace(),
    )

    tools, deferred_names, hints = context_usage._build_context_tool_setup(
        config,
        "model",
        tool_groups=["web"],
        subagent_enabled=True,
        agent_name="reviewer",
        runtime={"channel_name": "web", "non_interactive": False},
        describe_skill_tool=describe_tool,
    )

    assert tools == [
        bash_tool,
        mcp_tool,
        update_tool,
        tool_search,
        describe_tool,
        memory_tool,
    ]
    assert deferred_names == frozenset({"mcp_search"})
    assert hints == "routing hints"
    get_tools.assert_called_once_with(
        model_name="model",
        groups=["web"],
        subagent_enabled=True,
        app_config=config,
    )
    assemble.assert_called_once_with(
        [bash_tool, mcp_tool, update_tool],
        enabled=True,
    )
    routing_hints.assert_called_once_with(
        [bash_tool, mcp_tool, update_tool],
        deferred_names=frozenset({"mcp_search"}),
    )


def test_build_context_tool_setup_applies_noninteractive_webhook_filters(monkeypatch):
    ask_tool = _make_tool("ask_clarification")
    bash_tool = _make_tool("bash")
    update_tool = _make_tool("update_agent")
    monkeypatch.setattr(
        "deerflow.tools.tools.get_available_tools",
        lambda **_: [ask_tool, bash_tool],
    )
    monkeypatch.setattr("deerflow.tools.builtins.update_agent", update_tool)
    assemble = MagicMock(
        return_value=(
            [bash_tool],
            SimpleNamespace(deferred_names=frozenset()),
        )
    )
    monkeypatch.setattr(
        "deerflow.tools.builtins.tool_search.assemble_deferred_tools",
        assemble,
    )
    monkeypatch.setattr(
        "deerflow.tools.builtins.tool_search.get_mcp_routing_hints_prompt_section",
        lambda *_args, **_kwargs: "",
    )
    monkeypatch.setattr(
        "deerflow.config.memory_config.should_use_memory_tools",
        lambda _config: False,
    )
    config = SimpleNamespace(
        tool_search=SimpleNamespace(enabled=False),
        memory=SimpleNamespace(),
    )

    tools, _deferred_names, _hints = context_usage._build_context_tool_setup(
        config,
        "model",
        tool_groups=None,
        subagent_enabled=False,
        agent_name="reviewer",
        runtime={"channel_name": "github", "non_interactive": True},
        describe_skill_tool=None,
    )

    assert tools == [bash_tool]
    assemble.assert_called_once_with([bash_tool], enabled=False)


def test_build_context_tool_setup_uses_bootstrap_branch_without_routing_hints(monkeypatch):
    bash_tool = _make_tool("bash")
    setup_tool = _make_tool("setup_agent")
    describe_tool = _make_tool("describe_skill")
    monkeypatch.setattr(
        "deerflow.tools.tools.get_available_tools",
        lambda **_: [bash_tool],
    )
    monkeypatch.setattr("deerflow.tools.builtins.setup_agent", setup_tool)
    assemble = MagicMock(
        return_value=(
            [bash_tool, setup_tool],
            SimpleNamespace(deferred_names=frozenset()),
        )
    )
    monkeypatch.setattr(
        "deerflow.tools.builtins.tool_search.assemble_deferred_tools",
        assemble,
    )
    routing_hints = MagicMock(return_value="must not be rendered")
    monkeypatch.setattr(
        "deerflow.tools.builtins.tool_search.get_mcp_routing_hints_prompt_section",
        routing_hints,
    )
    monkeypatch.setattr(
        "deerflow.config.memory_config.should_use_memory_tools",
        lambda _config: False,
    )
    config = SimpleNamespace(
        tool_search=SimpleNamespace(enabled=False),
        memory=SimpleNamespace(),
    )

    tools, deferred_names, hints = context_usage._build_context_tool_setup(
        config,
        "model",
        tool_groups=["must-not-be-used"],
        subagent_enabled=False,
        agent_name="must-not-be-used",
        runtime={"is_bootstrap": True},
        describe_skill_tool=describe_tool,
    )

    assert tools == [bash_tool, setup_tool, describe_tool]
    assert deferred_names == frozenset()
    assert hints == ""
    assemble.assert_called_once_with([bash_tool, setup_tool], enabled=False)
    routing_hints.assert_not_called()


# ---------------------------------------------------------------------------
# Token-counting strategy dispatch (approximate vs exact / model tokenizer).
# ---------------------------------------------------------------------------


def _config_with_counting(counting: str | None) -> SimpleNamespace:
    from deerflow.config.token_usage_config import TokenUsageConfig

    return SimpleNamespace(token_usage=TokenUsageConfig(counting=counting) if counting is not None else None)


def test_is_exact_counting_reads_config():
    assert context_usage._is_exact_counting(_config_with_counting("exact")) is True
    assert context_usage._is_exact_counting(_config_with_counting("approximate")) is False
    # Missing token_usage block -> approximate (safe default).
    assert context_usage._is_exact_counting(SimpleNamespace()) is False
    # None app_config -> approximate.
    assert context_usage._is_exact_counting(None) is False


def test_count_text_approximate_uses_chars_div_4():
    config = _config_with_counting("approximate")
    # 12 chars -> 3 tokens.
    assert context_usage._count_text("hello world!", config) == 3
    assert context_usage._count_text("", config) == 0
    assert context_usage._count_text(None, config) == 0


def test_count_text_exact_delegates_to_model_tokenizer(monkeypatch):
    """In exact mode ``_count_text`` routes through the tiktoken-backed counter."""
    calls: list[str] = []

    def _fake_count(text, encoding_name="cl100k_base", *, use_tiktoken=True):
        calls.append(text)
        return 42  # deterministic sentinel

    monkeypatch.setattr(
        "deerflow.agents.memory.backends.deermem.deermem.core.prompt._count_tokens",
        _fake_count,
    )
    config = _config_with_counting("exact")

    assert context_usage._count_text("你好世界", config) == 42
    assert calls == ["你好世界"]


def test_count_text_exact_falls_back_when_tokenizer_unavailable(monkeypatch):
    """A tokenizer failure must degrade to the heuristic, not zero."""

    def _boom(*args, **kwargs):
        raise RuntimeError("tiktoken exploded")

    monkeypatch.setattr(
        "deerflow.agents.memory.backends.deermem.deermem.core.prompt._count_tokens",
        _boom,
    )
    config = _config_with_counting("exact")
    # 8 chars -> 2 tokens (heuristic fallback), NOT 0.
    assert context_usage._count_text("abcdefgh", config) == 2


def test_count_messages_approximate_uses_langchain_heuristic(monkeypatch):
    config = _config_with_counting("approximate")
    captured: list = []

    def _fake_approx(messages):
        captured.append(messages)
        return 7

    monkeypatch.setattr("langchain_core.messages.utils.count_tokens_approximately", _fake_approx)
    msgs = [SimpleNamespace(content="hi")]
    assert context_usage._count_messages(msgs, config) == 7
    assert captured == [msgs]


def test_count_messages_exact_tokenizes_text(monkeypatch):
    monkeypatch.setattr(
        "deerflow.agents.memory.backends.deermem.deermem.core.prompt._count_tokens",
        lambda text, **_: len(text),
    )
    config = _config_with_counting("exact")
    # Each message contributes its text length + 4 framing tokens.
    from langchain_core.messages import HumanMessage, SystemMessage

    msgs = [SystemMessage(content="sys"), HumanMessage(content="hello")]
    # "sys" (3) + 4 + "hello" (5) + 4 = 16
    assert context_usage._count_messages(msgs, config) == 16


def test_count_messages_exact_counts_tool_payloads_and_tool_call_ids(monkeypatch):
    tokenized: list[str] = []

    def _count(text: str, **_):
        tokenized.append(text)
        return len(text)

    monkeypatch.setattr(
        "deerflow.agents.memory.backends.deermem.deermem.core.prompt._count_tokens",
        _count,
    )
    config = _config_with_counting("exact")
    from langchain_core.messages import AIMessage, ToolMessage

    def _tool_exchange(command: str, tool_call_id: str):
        return [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "bash",
                        "args": {"command": command},
                        "id": tool_call_id,
                        "type": "tool_call",
                    }
                ],
            ),
            ToolMessage(content="ok", tool_call_id=tool_call_id),
        ]

    small = context_usage._count_messages(_tool_exchange("pwd", "call-1"), config)
    large = context_usage._count_messages(
        _tool_exchange("x" * 2000, "call-" + "y" * 100),
        config,
    )

    # Both the serialized tool arguments and the matching ToolMessage id must
    # contribute to the exact count; the old text-only loop returned the same
    # value for both exchanges.
    assert large > small + 2000
    assert any('"name":"bash"' in text and "command" in text and "pwd" in text for text in tokenized)

    short_id = context_usage._count_messages([ToolMessage(content="ok", tool_call_id="a")], config)
    long_id = context_usage._count_messages([ToolMessage(content="ok", tool_call_id="a" * 100)], config)
    assert long_id - short_id == 99


def test_count_messages_exact_counts_tool_calls_beside_non_tool_list_content(monkeypatch):
    monkeypatch.setattr(
        "deerflow.agents.memory.backends.deermem.deermem.core.prompt._count_tokens",
        lambda text, **_: len(text),
    )
    config = _config_with_counting("exact")
    from langchain_core.messages import AIMessage

    content = [{"type": "text", "text": "thinking"}]
    without_tool_call = AIMessage(content=content)
    with_tool_call = AIMessage(
        content=content,
        tool_calls=[
            {
                "name": "bash",
                "args": {"command": "x" * 1000},
                "id": "call-1",
                "type": "tool_call",
            }
        ],
    )

    base = context_usage._count_messages([without_tool_call], config)
    counted = context_usage._count_messages([with_tool_call], config)
    assert counted > base + 1000


def test_count_messages_exact_counts_responses_text_block_metadata(monkeypatch):
    monkeypatch.setattr(
        "deerflow.agents.memory.backends.deermem.deermem.core.prompt._count_tokens",
        lambda text, **_: len(text),
    )
    config = _config_with_counting("exact")
    from langchain_core.messages import AIMessage

    plain = AIMessage(content=[{"type": "text", "text": "answer"}])
    annotated = AIMessage(
        content=[
            {
                "type": "text",
                "text": "answer",
                "id": "msg-1",
                "phase": "final_answer",
                "annotations": [
                    {
                        "type": "url_citation",
                        "url": "https://example.com/" + "u" * 1000,
                        "title": "source",
                    }
                ],
            }
        ]
    )

    assert context_usage._count_messages([annotated], config) > context_usage._count_messages([plain], config) + 1000


def test_count_messages_exact_counts_replayed_reasoning_without_duplicates(monkeypatch):
    monkeypatch.setattr(
        "deerflow.agents.memory.backends.deermem.deermem.core.prompt._count_tokens",
        lambda text, **_: len(text),
    )
    config = _config_with_counting("exact")
    from langchain_core.messages import AIMessage

    plain = AIMessage(content="answer")
    replayed = AIMessage(
        content="answer",
        additional_kwargs={
            "reasoning": "r" * 1000,
            # vLLM stores a readable duplicate alongside the raw field.
            "reasoning_content": "r" * 1000,
        },
    )
    content_block = AIMessage(content=[{"type": "reasoning", "summary": [{"type": "summary_text", "text": "r" * 1000}]}])
    content_block_with_duplicate = AIMessage(
        content=content_block.content,
        additional_kwargs={"reasoning_content": "r" * 1000},
    )

    assert context_usage._count_messages([replayed], config) > context_usage._count_messages([plain], config) + 1000
    assert context_usage._count_messages([content_block_with_duplicate], config) == context_usage._count_messages([content_block], config)


def test_count_messages_exact_only_counts_reasoning_for_replaying_models(monkeypatch):
    monkeypatch.setattr(
        "deerflow.agents.memory.backends.deermem.deermem.core.prompt._count_tokens",
        lambda text, **_: len(text),
    )
    from langchain_core.messages import AIMessage

    model_configs = {
        "minimax": SimpleNamespace(
            use="deerflow.models.patched_minimax:PatchedChatMiniMax",
            use_responses_api=False,
        ),
        "deepseek": SimpleNamespace(
            use="deerflow.models.patched_deepseek:PatchedChatDeepSeek",
            use_responses_api=False,
        ),
        "responses": SimpleNamespace(
            use="langchain_openai.ChatOpenAI",
            use_responses_api=True,
        ),
    }
    config = _config_with_counting("exact")
    config.get_model_config = model_configs.get
    plain = AIMessage(content="answer")
    with_reasoning = AIMessage(
        content="answer",
        additional_kwargs={"reasoning_content": "r" * 1000},
    )

    plain_count = context_usage._count_messages([plain], config, model_name="minimax")
    assert context_usage._count_messages([with_reasoning], config, model_name="minimax") == plain_count
    assert context_usage._count_messages([with_reasoning], config, model_name="deepseek") > plain_count + 1000
    assert context_usage._count_messages([with_reasoning], config, model_name="responses") > plain_count + 1000


def test_count_messages_exact_counts_provider_fields_on_normalized_tool_calls(monkeypatch):
    monkeypatch.setattr(
        "deerflow.agents.memory.backends.deermem.deermem.core.prompt._count_tokens",
        lambda text, **_: len(text),
    )
    config = _config_with_counting("exact")
    from langchain_core.messages import AIMessage

    normalized = {
        "name": "bash",
        "args": {"command": "pwd"},
        "id": "call-1",
        "type": "tool_call",
    }
    raw = {
        "id": "call-1",
        "type": "function",
        "function": {"name": "bash", "arguments": '{"command":"pwd"}'},
    }
    unsigned = AIMessage(
        content="",
        tool_calls=[normalized],
        additional_kwargs={"tool_calls": [raw]},
    )
    signed = AIMessage(
        content="",
        tool_calls=[normalized],
        additional_kwargs={
            "tool_calls": [{**raw, "thought_signature": "s" * 1000}],
        },
    )

    assert context_usage._count_messages([signed], config) > context_usage._count_messages([unsigned], config) + 1000


def test_count_messages_exact_only_counts_signatures_for_replaying_models(monkeypatch):
    monkeypatch.setattr(
        "deerflow.agents.memory.backends.deermem.deermem.core.prompt._count_tokens",
        lambda text, **_: len(text),
    )
    from langchain_core.messages import AIMessage

    model_configs = {
        "standard": SimpleNamespace(use="langchain_openai.ChatOpenAI"),
        "patched": SimpleNamespace(use="deerflow.models.patched_openai:PatchedChatOpenAI"),
    }
    config = _config_with_counting("exact")
    config.get_model_config = model_configs.get
    normalized = {
        "name": "bash",
        "args": {"command": "pwd"},
        "id": "call-1",
        "type": "tool_call",
    }
    raw = {
        "id": "call-1",
        "type": "function",
        "function": {"name": "bash", "arguments": '{"command":"pwd"}'},
    }
    unsigned = AIMessage(content="", tool_calls=[normalized], additional_kwargs={"tool_calls": [raw]})
    signed = AIMessage(
        content="",
        tool_calls=[normalized],
        additional_kwargs={"tool_calls": [{**raw, "thought_signature": "s" * 1000}]},
    )

    standard_count = context_usage._count_messages([unsigned], config, model_name="standard")
    assert context_usage._count_messages([signed], config, model_name="standard") == standard_count
    assert context_usage._count_messages([signed], config, model_name="patched") > standard_count + 1000


def test_count_messages_exact_ignores_unmatched_raw_tool_call_extensions(monkeypatch):
    monkeypatch.setattr(
        "deerflow.agents.memory.backends.deermem.deermem.core.prompt._count_tokens",
        lambda text, **_: len(text),
    )
    config = _config_with_counting("exact")
    from langchain_core.messages import AIMessage

    normalized = {
        "name": "bash",
        "args": {"command": "pwd"},
        "id": "call-1",
        "type": "tool_call",
    }
    raw = {
        "id": "call-1",
        "type": "function",
        "function": {"name": "bash", "arguments": '{"command":"pwd"}'},
    }
    matched_only = AIMessage(
        content="",
        tool_calls=[normalized],
        additional_kwargs={"tool_calls": [raw]},
    )
    with_unmatched_signature = AIMessage(
        content="",
        tool_calls=[normalized],
        additional_kwargs={
            "tool_calls": [raw, {**raw, "id": "not-sent", "thought_signature": "s" * 1000}],
        },
    )

    assert context_usage._count_messages([with_unmatched_signature], config) == context_usage._count_messages([matched_only], config)


def test_count_messages_exact_counts_responses_v03_replayed_fields(monkeypatch):
    monkeypatch.setattr(
        "deerflow.agents.memory.backends.deermem.deermem.core.prompt._count_tokens",
        lambda text, **_: len(text),
    )
    config = _config_with_counting("exact")
    from langchain_core.messages import AIMessage

    tool_call = {
        "name": "bash",
        "args": {"command": "pwd"},
        "id": "call-1",
        "type": "tool_call",
    }
    base = AIMessage(content=[{"type": "text", "text": "answer"}], tool_calls=[tool_call])
    replayed = AIMessage(
        content=base.content,
        tool_calls=[tool_call],
        additional_kwargs={
            "refusal": "cannot comply " + "r" * 1000,
            "tool_outputs": [
                {
                    "type": "mcp_call",
                    "id": "mcp-1",
                    "status": "completed",
                    "output": "o" * 1000,
                }
            ],
            "__openai_function_call_ids__": {"call-1": "fc_" + "i" * 1000},
        },
    )

    assert context_usage._count_messages([replayed], config) > context_usage._count_messages([base], config) + 3000


def test_count_messages_exact_ignores_v03_fields_when_adapter_will_not_replay_them(monkeypatch):
    monkeypatch.setattr(
        "deerflow.agents.memory.backends.deermem.deermem.core.prompt._count_tokens",
        lambda text, **_: len(text),
    )
    config = _config_with_counting("exact")
    from langchain_core.messages import AIMessage

    tool_call = {
        "name": "bash",
        "args": {"command": "pwd"},
        "id": "call-1",
        "type": "tool_call",
    }
    base = AIMessage(content="answer", tool_calls=[tool_call])
    not_replayed = AIMessage(
        content="answer",
        tool_calls=[tool_call],
        additional_kwargs={
            "refusal": "r" * 1000,
            "tool_outputs": [{"type": "mcp_call", "id": "mcp-1", "output": "o" * 1000}],
            "__openai_function_call_ids__": {"call-1": "fc_" + "i" * 1000},
        },
    )

    assert context_usage._count_messages([not_replayed], config) == context_usage._count_messages([base], config)


def test_count_messages_exact_frames_legacy_function_messages(monkeypatch):
    monkeypatch.setattr(
        "deerflow.agents.memory.backends.deermem.deermem.core.prompt._count_tokens",
        lambda text, **_: len(text),
    )
    config = _config_with_counting("exact")
    from langchain_core.messages import FunctionMessage

    message = FunctionMessage(content="result", name="legacy_tool")

    assert context_usage._count_messages([message], config) == len("result") + len("legacy_tool") + 4


def test_count_messages_exact_counts_invalid_and_raw_tool_calls(monkeypatch):
    monkeypatch.setattr(
        "deerflow.agents.memory.backends.deermem.deermem.core.prompt._count_tokens",
        lambda text, **_: len(text),
    )
    config = _config_with_counting("exact")
    from langchain_core.messages import AIMessage

    base = context_usage._count_messages([AIMessage(content="")], config)
    invalid = AIMessage(
        content="",
        invalid_tool_calls=[
            {
                "name": "bash",
                "args": "x" * 1000,
                "id": "bad-1",
                "error": "parse error",
                "type": "invalid_tool_call",
            }
        ],
    )
    raw = AIMessage(
        content="",
        additional_kwargs={
            "tool_calls": [
                {
                    "id": "raw-1",
                    "type": "function",
                    "function": {
                        "name": "bash",
                        "arguments": "x" * 1000,
                    },
                }
            ]
        },
    )

    assert context_usage._count_messages([invalid], config) > base + 1000
    assert context_usage._count_messages([raw], config) > base + 1000

    short_error = invalid.model_copy(
        update={
            "invalid_tool_calls": [
                {
                    **invalid.invalid_tool_calls[0],
                    "error": "short",
                }
            ]
        }
    )
    long_error = invalid.model_copy(
        update={
            "invalid_tool_calls": [
                {
                    **invalid.invalid_tool_calls[0],
                    "error": "e" * 5000,
                }
            ]
        }
    )
    assert context_usage._count_messages([long_error], config) == context_usage._count_messages([short_error], config)


def test_count_messages_exact_counts_structured_blocks_and_bounds_images(monkeypatch):
    monkeypatch.setattr(
        "deerflow.agents.memory.backends.deermem.deermem.core.prompt._count_tokens",
        lambda text, **_: len(text),
    )
    config = _config_with_counting("exact")
    from langchain_core.messages import AIMessage, HumanMessage

    structured = HumanMessage(
        content=[
            {"type": "text", "text": "hello"},
            {"type": "input_audio", "data": "abc"},
        ]
    )
    assert context_usage._count_messages([structured], config) > len("hello") + 4

    short_image = HumanMessage(
        content=[
            {
                "type": "image_url",
                "image_url": {"url": "data:image/png;base64,a"},
            }
        ]
    )
    large_image = HumanMessage(
        content=[
            {
                "type": "image_url",
                "image_url": {"url": "data:image/png;base64," + "a" * 20_000},
            }
        ]
    )
    short_count = context_usage._count_messages([short_image], config)
    large_count = context_usage._count_messages([large_image], config)

    assert short_count >= 85
    assert large_count == short_count

    short_input_image = HumanMessage(
        content=[
            {
                "type": "input_image",
                "image_url": "data:image/png;base64,a",
            }
        ]
    )
    large_input_image = HumanMessage(
        content=[
            {
                "type": "input_image",
                "image_url": "data:image/png;base64," + "a" * 20_000,
            }
        ]
    )
    short_input_count = context_usage._count_messages([short_input_image], config)
    large_input_count = context_usage._count_messages([large_input_image], config)

    assert short_input_count >= 85
    assert large_input_count == short_input_count

    short_generated_image = AIMessage(
        content=[
            {
                "type": "image_generation_call",
                "id": "image-1",
                "status": "completed",
                "result": "a",
            }
        ]
    )
    large_generated_image = AIMessage(
        content=[
            {
                "type": "image_generation_call",
                "id": "image-1",
                "status": "completed",
                "result": "a" * 20_000,
            }
        ]
    )
    short_generated_count = context_usage._count_messages([short_generated_image], config)
    large_generated_count = context_usage._count_messages([large_generated_image], config)

    assert short_generated_count >= 85
    assert large_generated_count == short_generated_count


def test_count_messages_exact_does_not_double_count_tool_use_blocks(monkeypatch):
    monkeypatch.setattr(
        "deerflow.agents.memory.backends.deermem.deermem.core.prompt._count_tokens",
        lambda text, **_: len(text),
    )
    config = _config_with_counting("exact")
    from langchain_core.messages import AIMessage

    block = {
        "type": "tool_use",
        "name": "bash",
        "input": {"command": "pwd"},
        "id": "call-1",
    }
    with_normalized_tool_calls = AIMessage(
        content=[block],
        tool_calls=[
            {
                "name": "bash",
                "args": {"command": "pwd"},
                "id": "call-1",
                "type": "tool_call",
            }
        ],
    )
    content_only = AIMessage(content=[block])

    counted = context_usage._count_messages([with_normalized_tool_calls], config)
    assert counted > 4
    assert counted == context_usage._count_messages([content_only], config)

    with_an_additional_call = AIMessage(
        content=[block],
        tool_calls=[
            {
                "name": "bash",
                "args": {"command": "pwd"},
                "id": "call-1",
                "type": "tool_call",
            },
            {
                "name": "write_file",
                "args": {"path": "result.txt", "content": "x" * 1000},
                "id": "call-2",
                "type": "tool_call",
            },
        ],
    )
    assert context_usage._count_messages([with_an_additional_call], config) > counted + 1000


def test_count_messages_exact_tool_payload_falls_back_when_tokenizer_fails(monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("tiktoken exploded")

    monkeypatch.setattr(
        "deerflow.agents.memory.backends.deermem.deermem.core.prompt._count_tokens",
        _boom,
    )
    config = _config_with_counting("exact")
    from langchain_core.messages import AIMessage

    message = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "bash",
                "args": {"command": "x" * 400},
                "id": "call-1",
                "type": "tool_call",
            }
        ],
    )

    assert context_usage._count_messages([message], config) > 4


def test_checkpoint_memory_is_reported_separately_from_messages():
    messages = [
        SystemMessage(content="Today is Tuesday", id="turn-1__date", additional_kwargs={"dynamic_context_reminder": True}),
        HumanMessage(content="Remember that my name is Ada", id="turn-1__memory", additional_kwargs={"dynamic_context_reminder": True}),
        HumanMessage(content="Hello", id="turn-1__user"),
    ]
    config = _config_with_counting("approximate")

    conversation_tokens, memory_tokens = context_usage._count_checkpoint_tokens(messages, config)

    assert conversation_tokens > 0
    assert memory_tokens > 0
    without_memory, _ = context_usage._count_checkpoint_tokens([messages[0], messages[2]], config)
    assert conversation_tokens == without_memory


def test_checkpoint_cache_token_covers_all_counted_message_fields():
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    def _token(message):
        return context_usage._checkpoint_cache_token({}, [message], None)

    tool_call_a = {
        "name": "bash",
        "args": {"command": "pwd"},
        "id": "call-1",
        "type": "tool_call",
    }
    tool_call_b = {**tool_call_a, "args": {"command": "ls"}}
    assert _token(AIMessage(content="", tool_calls=[tool_call_a])) != _token(AIMessage(content="", tool_calls=[tool_call_b]))

    invalid_a = {
        "name": "bash",
        "args": "bad-a",
        "id": "bad-1",
        "error": "parse error",
        "type": "invalid_tool_call",
    }
    invalid_b = {**invalid_a, "args": "bad-b"}
    assert _token(AIMessage(content="", invalid_tool_calls=[invalid_a])) != _token(AIMessage(content="", invalid_tool_calls=[invalid_b]))

    assert _token(ToolMessage(content="ok", tool_call_id="call-1")) != _token(ToolMessage(content="ok", tool_call_id="call-2"))
    assert _token(HumanMessage(content="hello", name="alice")) != _token(HumanMessage(content="hello", name="bob"))


@pytest.mark.asyncio
async def test_thread_runtime_reads_latest_persisted_options():
    run_store = MagicMock()
    run_store.list_by_thread = AsyncMock(
        return_value=[
            {
                "model_name": "large-model",
                "kwargs": {
                    "config": {
                        "configurable": {"subagent_enabled": False},
                        "context": {"subagent_enabled": True, "max_concurrent_subagents": 7},
                    }
                },
            }
        ]
    )

    model_name, runtime = await context_usage._resolve_thread_runtime(
        run_store,
        "thread-1",
        SimpleNamespace(models=[]),
    )

    assert model_name == "large-model"
    assert runtime["subagent_enabled"] is True
    assert runtime["max_concurrent_subagents"] == 7


@pytest.mark.asyncio
async def test_thread_agent_name_comes_from_metadata(monkeypatch):
    thread_store = MagicMock()
    thread_store.get = AsyncMock(return_value={"metadata": {"agent_name": "reviewer"}})
    monkeypatch.setattr(context_usage, "get_thread_store", lambda _request: thread_store)

    agent_name = await context_usage._resolve_thread_agent_name(MagicMock(), "thread-1")

    assert agent_name == "reviewer"
    thread_store.get.assert_awaited_once_with("thread-1")


def test_custom_agent_settings_flow_into_prompt_and_tools(monkeypatch):
    from deerflow.config import agents_config as agents_config_module

    monkeypatch.setattr(
        agents_config_module,
        "load_agent_config",
        lambda name, user_id=None: SimpleNamespace(skills=["code-review"], tool_groups=["web"]),
    )
    checkpoint_counter = MagicMock(return_value=(11, 3))
    monkeypatch.setattr(context_usage, "_count_checkpoint_tokens", checkpoint_counter)
    skills_counter = MagicMock(return_value=5)
    subagent_counter = MagicMock(return_value=7)
    prompt_counter = MagicMock(return_value=13)
    tools_counter = MagicMock(return_value=(17, 19, 29))
    describe_skill_tool = object()
    skill_setup = MagicMock(return_value=(frozenset({"code-review"}), describe_skill_tool))
    assembled_tools = [object()]
    tool_setup = MagicMock(
        return_value=(
            assembled_tools,
            frozenset({"mcp_search"}),
            "routing hints",
        )
    )
    monkeypatch.setattr(context_usage, "_build_context_skill_setup", skill_setup)
    monkeypatch.setattr(context_usage, "_build_context_tool_setup", tool_setup)
    monkeypatch.setattr(context_usage, "_count_skills_section", skills_counter)
    monkeypatch.setattr(context_usage, "_count_subagent_section", subagent_counter)
    monkeypatch.setattr(context_usage, "_count_system_prompt", prompt_counter)
    monkeypatch.setattr(context_usage, "_split_tools", tools_counter)

    app_config = SimpleNamespace(
        subagents=SimpleNamespace(enabled=False, max_concurrent_subagents=3, max_total_per_run=6),
        skills=SimpleNamespace(deferred_discovery=True, container_path="/mnt/skills"),
        get_model_config=lambda _name: SimpleNamespace(context_window=100_000),
        summarization=SimpleNamespace(enabled=False),
    )
    counts = context_usage._compute_context_counts(
        [],
        app_config,
        "large-model",
        {"subagent_enabled": True, "max_concurrent_subagents": 6, "max_total_subagents": 9},
        "reviewer",
    )

    assert counts["memory_tokens"] == 3
    assert counts["max_context_tokens"] == 100_000
    checkpoint_counter.assert_called_once_with([], app_config, model_name="large-model")
    scoped_user_id = skills_counter.call_args.args[2]
    assert skills_counter.call_args.args[:2] == (app_config, {"code-review"})
    assert skills_counter.call_args.kwargs == {"skill_names": frozenset({"code-review"})}
    assert isinstance(scoped_user_id, str)
    skill_setup.assert_called_once_with(app_config, {"code-review"}, scoped_user_id)
    subagent_counter.assert_called_once_with(
        app_config,
        enabled=True,
        max_concurrent=6,
        max_total=9,
    )
    assert prompt_counter.call_args.kwargs == {
        "agent_name": "reviewer",
        "available_skills": {"code-review"},
        "user_id": scoped_user_id,
        "subagent_enabled": True,
        "max_concurrent_subagents": 6,
        "max_total_subagents": 9,
        "skills_tokens": 5,
        "subagent_tokens": 7,
        "skill_names": frozenset({"code-review"}),
        "deferred_names": frozenset({"mcp_search"}),
        "mcp_routing_hints_section": "routing hints",
    }
    tool_setup.assert_called_once_with(
        app_config,
        "large-model",
        tool_groups=["web"],
        subagent_enabled=True,
        agent_name="reviewer",
        runtime={"subagent_enabled": True, "max_concurrent_subagents": 6, "max_total_subagents": 9},
        describe_skill_tool=describe_skill_tool,
    )
    assert tools_counter.call_args.kwargs == {
        "tool_groups": ["web"],
        "subagent_enabled": True,
        "promoted": None,
        "available_tools": assembled_tools,
    }


def test_bootstrap_context_ignores_custom_agent_metadata_and_uses_runtime_defaults(monkeypatch):
    from deerflow.config import agents_config as agents_config_module

    load_agent_config = MagicMock(side_effect=AssertionError("bootstrap must not load a custom agent"))
    monkeypatch.setattr(agents_config_module, "load_agent_config", load_agent_config)
    monkeypatch.setattr(context_usage, "_count_checkpoint_tokens", MagicMock(return_value=(11, 3)))
    skill_setup = MagicMock(return_value=(frozenset({"bootstrap"}), None))
    tool_setup = MagicMock(return_value=([object()], frozenset(), ""))
    skills_counter = MagicMock(return_value=5)
    subagent_counter = MagicMock(return_value=0)
    prompt_counter = MagicMock(return_value=13)
    tools_counter = MagicMock(return_value=(17, 0, 0))
    monkeypatch.setattr(context_usage, "_build_context_skill_setup", skill_setup)
    monkeypatch.setattr(context_usage, "_build_context_tool_setup", tool_setup)
    monkeypatch.setattr(context_usage, "_count_skills_section", skills_counter)
    monkeypatch.setattr(context_usage, "_count_subagent_section", subagent_counter)
    monkeypatch.setattr(context_usage, "_count_system_prompt", prompt_counter)
    monkeypatch.setattr(context_usage, "_split_tools", tools_counter)

    app_config = SimpleNamespace(
        # These non-runtime values deliberately differ from the lead-agent
        # factory defaults. Bootstrap must still use disabled / 3 here.
        subagents=SimpleNamespace(enabled=True, max_concurrent_subagents=8, max_total_per_run=11),
        get_model_config=lambda _name: SimpleNamespace(context_window=100_000),
        summarization=SimpleNamespace(enabled=False),
    )
    runtime = {"is_bootstrap": True}

    counts = context_usage._compute_context_counts(
        [],
        app_config,
        "large-model",
        runtime,
        "stale-custom-agent-metadata",
    )

    assert counts["max_context_tokens"] == 100_000
    load_agent_config.assert_not_called()
    skill_setup.assert_called_once_with(app_config, {"bootstrap"}, ANY)
    tool_setup.assert_called_once_with(
        app_config,
        "large-model",
        tool_groups=None,
        subagent_enabled=False,
        agent_name=None,
        runtime=runtime,
        describe_skill_tool=None,
    )
    subagent_counter.assert_called_once_with(
        app_config,
        enabled=False,
        max_concurrent=3,
        max_total=11,
    )
    assert prompt_counter.call_args.kwargs["agent_name"] is None
    assert prompt_counter.call_args.kwargs["available_skills"] == {"bootstrap"}
    assert prompt_counter.call_args.kwargs["subagent_enabled"] is False
    assert prompt_counter.call_args.kwargs["max_concurrent_subagents"] == 3
    assert prompt_counter.call_args.kwargs["max_total_subagents"] == 11


@pytest.mark.asyncio
async def test_context_rendering_is_offloaded_from_event_loop(monkeypatch):
    checkpointer = MagicMock()
    messages = [HumanMessage(content="hello")]
    counts = _kwargs(max_context_tokens=10_000, messages_tokens=4)
    monkeypatch.setattr(context_usage, "get_checkpointer", lambda _request: checkpointer)
    monkeypatch.setattr(context_usage, "get_config", lambda: SimpleNamespace())
    monkeypatch.setattr(
        context_usage,
        "_load_checkpoint_messages",
        AsyncMock(return_value=(messages, None, "checkpoint-1")),
    )
    monkeypatch.setattr(
        context_usage,
        "_resolve_thread_runtime",
        AsyncMock(return_value=("model", {"subagent_enabled": False})),
    )
    monkeypatch.setattr(context_usage, "_resolve_thread_agent_name", AsyncMock(return_value=None))
    get_counts = AsyncMock(return_value=counts)
    monkeypatch.setattr(context_usage, "_get_context_counts", get_counts)

    payload = await context_usage.build_context_usage(MagicMock(), "thread-1", MagicMock())

    assert payload is not None
    assert payload["used_tokens"] == 4
    get_counts.assert_awaited_once_with(
        ANY,
        messages,
        ANY,
        "model",
        {"subagent_enabled": False},
        None,
        None,
    )


@pytest.mark.asyncio
async def test_context_rendering_overload_returns_unknown_usage(monkeypatch):
    checkpointer = MagicMock()
    messages = [HumanMessage(content="hello")]
    monkeypatch.setattr(context_usage, "get_checkpointer", lambda _request: checkpointer)
    monkeypatch.setattr(context_usage, "get_config", lambda: SimpleNamespace())
    monkeypatch.setattr(
        context_usage,
        "_load_checkpoint_messages",
        AsyncMock(return_value=(messages, None, "checkpoint-1")),
    )
    monkeypatch.setattr(
        context_usage,
        "_resolve_thread_runtime",
        AsyncMock(return_value=("model", {"subagent_enabled": False})),
    )
    monkeypatch.setattr(context_usage, "_resolve_thread_agent_name", AsyncMock(return_value=None))
    get_counts = AsyncMock(side_effect=context_usage._ContextCountOverloadedError)
    monkeypatch.setattr(context_usage, "_get_context_counts", get_counts)

    assert await context_usage.build_context_usage(MagicMock(), "thread-1", MagicMock()) is None
    get_counts.assert_awaited_once()


@pytest.mark.asyncio
async def test_context_count_timeout_reuses_inflight_task(monkeypatch):
    context_usage._CONTEXT_COUNT_CACHE.clear()
    context_usage._CONTEXT_COUNT_INFLIGHT.clear()
    started = 0
    release = asyncio.Event()
    counts = _kwargs(max_context_tokens=10_000, messages_tokens=4)

    async def _slow_count(*_args):
        nonlocal started
        started += 1
        await release.wait()
        return counts

    monkeypatch.setattr(context_usage, "_run_context_count", _slow_count)
    key = ("thread-1", "checkpoint-1", "config", "model", "agent", "user", "{}", "null")
    args = ([], SimpleNamespace(), "model", {}, None, None)

    with pytest.raises(TimeoutError):
        await context_usage._get_context_counts(key, *args, timeout_seconds=0.001)
    with pytest.raises(TimeoutError):
        await context_usage._get_context_counts(key, *args, timeout_seconds=0.001)
    assert started == 1

    release.set()
    result = await context_usage._get_context_counts(key, *args, timeout_seconds=1)
    assert result == counts
    await asyncio.sleep(0)
    assert await context_usage._get_context_counts(key, *args, timeout_seconds=1) == counts
    assert started == 1
    context_usage._CONTEXT_COUNT_CACHE.clear()
    context_usage._CONTEXT_COUNT_INFLIGHT.clear()


@pytest.mark.asyncio
async def test_context_count_inflight_is_bounded_across_distinct_keys(monkeypatch):
    context_usage._CONTEXT_COUNT_CACHE.clear()
    context_usage._CONTEXT_COUNT_INFLIGHT.clear()
    assert context_usage._CONTEXT_COUNT_INFLIGHT_LIMIT == context_usage._CONTEXT_COUNT_EXECUTOR_WORKERS
    release = asyncio.Event()
    all_started = asyncio.Event()
    started = 0
    counts = _kwargs(max_context_tokens=10_000, messages_tokens=4)

    async def _blocked_count(*_args):
        nonlocal started
        started += 1
        if started == context_usage._CONTEXT_COUNT_INFLIGHT_LIMIT:
            all_started.set()
        await release.wait()
        return counts

    monkeypatch.setattr(context_usage, "_run_context_count", _blocked_count)
    args = ([], SimpleNamespace(), "model", {}, None, None)

    def _key(index: int):
        return (f"thread-{index}", f"checkpoint-{index}", "config", "model", "agent", "user", "{}", "null")

    tasks = [asyncio.create_task(context_usage._get_context_counts(_key(index), *args, timeout_seconds=1)) for index in range(context_usage._CONTEXT_COUNT_INFLIGHT_LIMIT)]
    results = []
    try:
        await asyncio.wait_for(all_started.wait(), timeout=1)
        assert len(context_usage._CONTEXT_COUNT_INFLIGHT) == context_usage._CONTEXT_COUNT_INFLIGHT_LIMIT

        with pytest.raises(context_usage._ContextCountOverloadedError):
            await context_usage._get_context_counts(
                _key(context_usage._CONTEXT_COUNT_INFLIGHT_LIMIT),
                *args,
                timeout_seconds=1,
            )
        assert len(context_usage._CONTEXT_COUNT_INFLIGHT) == context_usage._CONTEXT_COUNT_INFLIGHT_LIMIT
        assert started == context_usage._CONTEXT_COUNT_INFLIGHT_LIMIT
    finally:
        release.set()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.sleep(0)

    assert results == [counts] * context_usage._CONTEXT_COUNT_INFLIGHT_LIMIT
    assert context_usage._CONTEXT_COUNT_INFLIGHT == {}
    context_usage._CONTEXT_COUNT_CACHE.clear()


@pytest.mark.asyncio
async def test_context_count_prunes_finished_task_into_cache_before_resubmitting(monkeypatch):
    context_usage._CONTEXT_COUNT_CACHE.clear()
    context_usage._CONTEXT_COUNT_INFLIGHT.clear()
    counts = _kwargs(max_context_tokens=10_000, messages_tokens=4)
    key = ("thread-1", "checkpoint-1", "config", "model", "agent", "user", "{}", "null")
    args = ([], SimpleNamespace(), "model", {}, None, None)
    finished = asyncio.create_task(asyncio.sleep(0, result=counts))
    await finished
    context_usage._CONTEXT_COUNT_INFLIGHT[key] = finished
    run_count = AsyncMock(return_value=counts)
    monkeypatch.setattr(context_usage, "_run_context_count", run_count)

    assert await context_usage._get_context_counts(key, *args, timeout_seconds=1) == counts
    run_count.assert_not_awaited()
    assert context_usage._CONTEXT_COUNT_INFLIGHT == {}
    assert context_usage._CONTEXT_COUNT_CACHE[key] == counts
    context_usage._CONTEXT_COUNT_CACHE.clear()


@pytest.mark.asyncio
async def test_context_count_stale_done_callback_cannot_overwrite_new_owner():
    context_usage._CONTEXT_COUNT_CACHE.clear()
    context_usage._CONTEXT_COUNT_INFLIGHT.clear()
    key = ("thread-1", "checkpoint-1", "config", "model", "agent", "user", "{}", "null")
    stale_counts = _kwargs(max_context_tokens=10_000, messages_tokens=1)
    stale_task = asyncio.create_task(asyncio.sleep(0, result=stale_counts))
    await stale_task
    release = asyncio.Event()
    current_task = asyncio.create_task(release.wait())
    context_usage._CONTEXT_COUNT_INFLIGHT[key] = current_task

    try:
        context_usage._finish_context_count(key, stale_task)
        assert context_usage._CONTEXT_COUNT_INFLIGHT[key] is current_task
        assert key not in context_usage._CONTEXT_COUNT_CACHE
    finally:
        release.set()
        await current_task
        context_usage._CONTEXT_COUNT_INFLIGHT.clear()
        context_usage._CONTEXT_COUNT_CACHE.clear()
