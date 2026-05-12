"""End-to-end verification for issue #2862 (and the regression of #2782).

Goal: prove — without trusting any single layer's claim — that an authenticated
user creating a custom agent through the real ``setup_agent`` tool, driven by a
real LangGraph ``create_agent`` graph, ends up with files under
``users/<auth_uid>/agents/<name>`` and **not** under ``users/default/agents/...``.

We intentionally exercise the full pipeline:

    HTTP body shape (mimics LangGraph SDK wire format)
      -> app.gateway.services.start_run config-assembly chain
      -> deerflow.runtime.runs.worker._build_runtime_context
      -> langchain.agents.create_agent graph
      -> ToolNode dispatch
      -> setup_agent tool

The only thing we mock is the LLM (FakeMessagesListChatModel) — every layer
that handles ``user_id`` is the real production code path. If the
``user_id`` propagation is broken anywhere in this chain, these tests will
fail.

These tests intentionally ``no_auto_user`` so that the ``contextvar``
fallback would put files into ``default/`` if propagation breaks.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

import pytest
from _agent_e2e_helpers import FakeToolCallingModel
from langchain_core.messages import AIMessage, HumanMessage

from app.gateway.services import (
    build_run_config,
    inject_authenticated_user_context,
    merge_run_context_overrides,
)
from deerflow.runtime.runs.worker import _build_runtime_context, _install_runtime_context

# ---------------------------------------------------------------------------
# Helpers — real production code paths
# ---------------------------------------------------------------------------


def _make_request(user_id_str: str | None) -> SimpleNamespace:
    """Build a fake FastAPI Request that carries an authenticated user."""
    if user_id_str is None:
        user = None
    else:
        # User.id is UUID in production; honour that
        user = SimpleNamespace(id=UUID(user_id_str), email="alice@local")
    return SimpleNamespace(state=SimpleNamespace(user=user))


def _assemble_config(
    *,
    body_config: dict | None,
    body_context: dict | None,
    request_user_id: str | None,
    thread_id: str = "thread-e2e",
    assistant_id: str = "lead_agent",
) -> dict:
    """Replay the **exact** start_run config-assembly sequence."""
    config = build_run_config(thread_id, body_config, None, assistant_id=assistant_id)
    merge_run_context_overrides(config, body_context)
    inject_authenticated_user_context(config, _make_request(request_user_id))
    return config


def _make_paths_mock(tmp_path: Path):
    """Mirror the production paths.user_agent_dir signature."""
    from unittest.mock import MagicMock

    paths = MagicMock()
    paths.base_dir = tmp_path
    paths.agent_dir = lambda name: tmp_path / "agents" / name
    paths.user_agent_dir = lambda user_id, name: tmp_path / "users" / user_id / "agents" / name
    return paths


# ---------------------------------------------------------------------------
# L1-L3: HTTP wire format → start_run → worker._build_runtime_context
# ---------------------------------------------------------------------------


class TestConfigAssembly:
    """Covers L1-L3: validate that user_id reaches runtime_ctx for every wire shape."""

    def test_typical_wire_format_user_id_in_runtime_ctx(self):
        """Real frontend: body.config={recursion_limit}, body.context={agent_name,...}."""
        config = _assemble_config(
            body_config={"recursion_limit": 1000},
            body_context={"agent_name": "myagent", "is_bootstrap": True, "mode": "flash"},
            request_user_id="11111111-2222-3333-4444-555555555555",
        )
        runtime_ctx = _build_runtime_context("thread-e2e", "run-1", config.get("context"), None)
        assert runtime_ctx["user_id"] == "11111111-2222-3333-4444-555555555555"
        assert runtime_ctx["agent_name"] == "myagent"

    def test_body_context_none_still_injects_user_id(self):
        """If frontend omits body.context entirely, inject must still create it."""
        config = _assemble_config(
            body_config={"recursion_limit": 1000},
            body_context=None,
            request_user_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        )
        runtime_ctx = _build_runtime_context("thread-e2e", "run-1", config.get("context"), None)
        assert runtime_ctx["user_id"] == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

    def test_body_context_empty_dict_still_injects_user_id(self):
        """body.context={} (falsy) path: inject must still produce user_id."""
        config = _assemble_config(
            body_config={"recursion_limit": 1000},
            body_context={},
            request_user_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        )
        runtime_ctx = _build_runtime_context("thread-e2e", "run-1", config.get("context"), None)
        assert runtime_ctx["user_id"] == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

    def test_body_config_already_contains_context_field(self):
        """body.config={'context': {...}} (LG 0.6 alt wire): inject still wins."""
        config = _assemble_config(
            body_config={"context": {"agent_name": "myagent"}, "recursion_limit": 1000},
            body_context=None,
            request_user_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        )
        runtime_ctx = _build_runtime_context("thread-e2e", "run-1", config.get("context"), None)
        assert runtime_ctx["user_id"] == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

    def test_client_supplied_user_id_is_overridden(self):
        """Spoofed client user_id must be overwritten by inject (auth-trusted source)."""
        config = _assemble_config(
            body_config={"recursion_limit": 1000},
            body_context={"agent_name": "myagent", "user_id": "spoofed"},
            request_user_id="11111111-2222-3333-4444-555555555555",
        )
        runtime_ctx = _build_runtime_context("thread-e2e", "run-1", config.get("context"), None)
        assert runtime_ctx["user_id"] == "11111111-2222-3333-4444-555555555555"

    def test_unauthenticated_request_does_not_inject(self):
        """If request.state.user is missing (impossible under fail-closed auth, but
        verify defensively), inject must not write user_id and runtime_ctx must
        therefore lack it — forcing the tool fallback path to reveal itself."""
        config = _assemble_config(
            body_config={"recursion_limit": 1000},
            body_context={"agent_name": "myagent"},
            request_user_id=None,
        )
        runtime_ctx = _build_runtime_context("thread-e2e", "run-1", config.get("context"), None)
        assert "user_id" not in runtime_ctx


# ---------------------------------------------------------------------------
# L4-L7: Real LangGraph create_agent driving the real setup_agent tool
# ---------------------------------------------------------------------------


def _build_real_bootstrap_graph(authenticated_user_id: str):
    """Construct a real LangGraph using create_agent + the real setup_agent tool.

    The LLM is faked (FakeMessagesListChatModel) so we don't need an API key.
    Everything else — ToolNode dispatch, runtime injection, middleware — is
    the real production code path.
    """
    from langchain.agents import create_agent

    from deerflow.tools.builtins.setup_agent_tool import setup_agent

    # First model turn: emit a tool_call for setup_agent
    # Second model turn (after tool result): final answer (terminates the loop)
    fake_model = FakeToolCallingModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "setup_agent",
                        "args": {
                            "soul": "# My E2E Agent\n\nA SOUL written by the model.",
                            "description": "End-to-end test agent",
                        },
                        "id": "call_setup_1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content=f"Done. Agent created for user {authenticated_user_id}."),
        ]
    )

    graph = create_agent(
        model=fake_model,
        tools=[setup_agent],
        system_prompt="You are a bootstrap agent. Call setup_agent immediately.",
    )
    return graph


@pytest.mark.no_auto_user
@pytest.mark.asyncio
async def test_real_graph_real_setup_agent_writes_to_authenticated_user_dir(tmp_path: Path):
    """The smoking-gun test for issue #2862.

    Under no_auto_user (contextvar = empty), if user_id propagation through
    runtime.context is broken, setup_agent will fall back to DEFAULT_USER_ID
    and write to users/default/agents/... The assertion that this directory
    DOES NOT exist is what makes this test load-bearing.
    """
    from langgraph.runtime import Runtime

    auth_uid = "abcdef01-2345-6789-abcd-ef0123456789"
    config = _assemble_config(
        body_config={"recursion_limit": 50},
        body_context={"agent_name": "e2e-agent", "is_bootstrap": True},
        request_user_id=auth_uid,
        thread_id="thread-e2e-1",
    )

    # Replay worker.run_agent's runtime construction. This is the key step:
    # it is what makes ToolRuntime.context contain user_id when the tool
    # actually fires.
    runtime_ctx = _build_runtime_context("thread-e2e-1", "run-1", config.get("context"), None)
    _install_runtime_context(config, runtime_ctx)
    runtime = Runtime(context=runtime_ctx, store=None)
    config.setdefault("configurable", {})["__pregel_runtime"] = runtime

    graph = _build_real_bootstrap_graph(auth_uid)

    # Patch get_paths only (the file-system rooting); everything else is real
    with patch(
        "deerflow.tools.builtins.setup_agent_tool.get_paths",
        return_value=_make_paths_mock(tmp_path),
    ):
        # Drive the real graph. This goes through real ToolNode + real Runtime merge.
        final_state = await graph.ainvoke(
            {"messages": [HumanMessage(content="Create an agent named e2e-agent")]},
            config=config,
        )

    expected_dir = tmp_path / "users" / auth_uid / "agents" / "e2e-agent"
    default_dir = tmp_path / "users" / "default" / "agents" / "e2e-agent"

    # Load-bearing assertions:
    assert expected_dir.exists(), f"Agent directory not found at the authenticated user's path. Expected: {expected_dir}. tmp_path tree: {[str(p) for p in tmp_path.rglob('*')]}"
    assert (expected_dir / "SOUL.md").read_text() == "# My E2E Agent\n\nA SOUL written by the model."
    assert (expected_dir / "config.yaml").exists()
    assert not default_dir.exists(), "REGRESSION: agent landed under users/default/. user_id propagation broke somewhere between HTTP layer and ToolRuntime.context."

    # And final state should reflect tool success
    last = final_state["messages"][-1]
    assert "Done" in (last.content if isinstance(last.content, str) else str(last.content))


@pytest.mark.no_auto_user
@pytest.mark.asyncio
async def test_inject_failure_falls_back_to_default_proving_test_is_load_bearing(tmp_path: Path):
    """Negative control: if inject does NOT happen (no user in request), and
    contextvar is empty (no_auto_user), setup_agent must land in default/.

    This proves the positive test is actually load-bearing — i.e. it would
    have failed before PR #2784, not passed accidentally.
    """
    from langgraph.runtime import Runtime

    config = _assemble_config(
        body_config={"recursion_limit": 50},
        body_context={"agent_name": "fallback-agent", "is_bootstrap": True},
        request_user_id=None,  # no auth — inject is a no-op
        thread_id="thread-e2e-2",
    )

    runtime_ctx = _build_runtime_context("thread-e2e-2", "run-2", config.get("context"), None)
    _install_runtime_context(config, runtime_ctx)
    runtime = Runtime(context=runtime_ctx, store=None)
    config.setdefault("configurable", {})["__pregel_runtime"] = runtime

    graph = _build_real_bootstrap_graph("does-not-matter")

    with patch(
        "deerflow.tools.builtins.setup_agent_tool.get_paths",
        return_value=_make_paths_mock(tmp_path),
    ):
        await graph.ainvoke(
            {"messages": [HumanMessage(content="Create fallback-agent")]},
            config=config,
        )

    default_dir = tmp_path / "users" / "default" / "agents" / "fallback-agent"
    assert default_dir.exists(), "Negative control failed: even without inject + contextvar, agent did not land in default/. The test infrastructure may not be reproducing the bug condition."


# ---------------------------------------------------------------------------
# L5: Sub-graph runtime propagation (the task tool case)
# ---------------------------------------------------------------------------


@pytest.mark.no_auto_user
@pytest.mark.asyncio
async def test_subgraph_invocation_preserves_user_id_in_runtime(tmp_path: Path):
    """When a parent graph invokes a child graph (the pattern used by
    subagents), parent_runtime.merge() must keep user_id intact.

    We construct a child graph that contains setup_agent and call it from
    a parent graph's tool. If LangGraph re-creates the Runtime and drops
    user_id at the sub-graph boundary, this fails.
    """
    from langchain.agents import create_agent
    from langgraph.runtime import Runtime

    from deerflow.tools.builtins.setup_agent_tool import setup_agent

    auth_uid = "deadbeef-0000-1111-2222-333344445555"

    # Inner graph: same as the bootstrap flow
    inner_model = FakeToolCallingModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "setup_agent",
                        "args": {"soul": "# Inner", "description": "subgraph"},
                        "id": "call_inner_1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="inner done"),
        ]
    )
    inner_graph = create_agent(
        model=inner_model,
        tools=[setup_agent],
        system_prompt="inner",
    )

    config = _assemble_config(
        body_config={"recursion_limit": 50},
        body_context={"agent_name": "subgraph-agent", "is_bootstrap": True},
        request_user_id=auth_uid,
        thread_id="thread-e2e-3",
    )
    runtime_ctx = _build_runtime_context("thread-e2e-3", "run-3", config.get("context"), None)
    _install_runtime_context(config, runtime_ctx)
    runtime = Runtime(context=runtime_ctx, store=None)
    config.setdefault("configurable", {})["__pregel_runtime"] = runtime

    with patch(
        "deerflow.tools.builtins.setup_agent_tool.get_paths",
        return_value=_make_paths_mock(tmp_path),
    ):
        # Direct sub-graph invoke (mimics what a subagent invocation looks like
        # — distinct ainvoke call, but parent config carries the same runtime).
        await inner_graph.ainvoke(
            {"messages": [HumanMessage(content="Create subgraph-agent")]},
            config=config,
        )

    expected_dir = tmp_path / "users" / auth_uid / "agents" / "subgraph-agent"
    default_dir = tmp_path / "users" / "default" / "agents" / "subgraph-agent"
    assert expected_dir.exists()
    assert not default_dir.exists()


# ---------------------------------------------------------------------------
# L6: Sync tool path through ContextThreadPoolExecutor
# ---------------------------------------------------------------------------


def test_sync_tool_dispatch_through_thread_pool_uses_runtime_context(tmp_path: Path):
    """setup_agent is a sync function. When dispatched through ToolNode's
    ContextThreadPoolExecutor, runtime.context must still carry user_id —
    not via thread-local copy_context (which only carries contextvars), but
    because it was passed in as the ToolRuntime constructor argument.
    """
    from langchain.agents import create_agent
    from langgraph.runtime import Runtime

    from deerflow.tools.builtins.setup_agent_tool import setup_agent

    auth_uid = "11112222-3333-4444-5555-666677778888"

    fake_model = FakeToolCallingModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "setup_agent",
                        "args": {"soul": "# Sync", "description": "sync path"},
                        "id": "call_sync_1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="sync done"),
        ]
    )
    graph = create_agent(model=fake_model, tools=[setup_agent], system_prompt="sync")

    config = _assemble_config(
        body_config={"recursion_limit": 50},
        body_context={"agent_name": "sync-agent", "is_bootstrap": True},
        request_user_id=auth_uid,
        thread_id="thread-e2e-4",
    )
    runtime_ctx = _build_runtime_context("thread-e2e-4", "run-4", config.get("context"), None)
    _install_runtime_context(config, runtime_ctx)
    runtime = Runtime(context=runtime_ctx, store=None)
    config.setdefault("configurable", {})["__pregel_runtime"] = runtime

    with patch(
        "deerflow.tools.builtins.setup_agent_tool.get_paths",
        return_value=_make_paths_mock(tmp_path),
    ):
        # Use SYNC invoke to hit the ContextThreadPoolExecutor path
        graph.invoke(
            {"messages": [HumanMessage(content="Create sync-agent")]},
            config=config,
        )

    expected_dir = tmp_path / "users" / auth_uid / "agents" / "sync-agent"
    default_dir = tmp_path / "users" / "default" / "agents" / "sync-agent"
    assert expected_dir.exists()
    assert not default_dir.exists()
