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
    monkeypatch.setattr(context_usage, "_count_checkpoint_tokens", lambda _messages, _config: (11, 3))
    skills_counter = MagicMock(return_value=5)
    prompt_counter = MagicMock(return_value=13)
    tools_counter = MagicMock(return_value=(17, 19, 29))
    monkeypatch.setattr(context_usage, "_count_skills_section", skills_counter)
    monkeypatch.setattr(context_usage, "_count_subagent_section", MagicMock(return_value=7))
    monkeypatch.setattr(context_usage, "_count_system_prompt", prompt_counter)
    monkeypatch.setattr(context_usage, "_split_tools", tools_counter)

    app_config = SimpleNamespace(
        subagents=SimpleNamespace(enabled=False, max_concurrent_subagents=3),
        get_model_config=lambda _name: SimpleNamespace(context_window=100_000),
        summarization=SimpleNamespace(enabled=False),
    )
    counts = context_usage._compute_context_counts(
        [],
        app_config,
        "large-model",
        {"subagent_enabled": True, "max_concurrent_subagents": 6},
        "reviewer",
    )

    assert counts["memory_tokens"] == 3
    assert counts["max_context_tokens"] == 100_000
    scoped_user_id = skills_counter.call_args.args[2]
    assert skills_counter.call_args.args[:2] == (app_config, {"code-review"})
    assert isinstance(scoped_user_id, str)
    assert prompt_counter.call_args.kwargs == {
        "agent_name": "reviewer",
        "available_skills": {"code-review"},
        "user_id": scoped_user_id,
        "subagent_enabled": True,
        "max_concurrent_subagents": 6,
        "skills_tokens": 5,
        "subagent_tokens": 7,
    }
    assert tools_counter.call_args.kwargs == {
        "tool_groups": ["web"],
        "subagent_enabled": True,
        "promoted": None,
    }


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
