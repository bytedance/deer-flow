"""Reproduce + regression-guard issue #2884.

Hypothesis from the issue:
  ``tools.tools.get_available_tools`` unconditionally calls
  ``reset_deferred_registry()`` and constructs a fresh ``DeferredToolRegistry``
  every time it is invoked. If anything calls ``get_available_tools`` again
  during the same async context (after the agent has promoted tools via
  ``tool_search``), the promotion is wiped and the next model call hides the
  tool's schema again.

These tests pin two things:

A. **At the unit boundary** — verify the failure mode directly. Promote a
   tool in the registry, then call ``get_available_tools`` again and observe
   that the ContextVar registry is reset and the promotion is lost.

B. **At the graph-execution boundary** — drive a real ``create_agent`` graph
   with the real ``DeferredToolFilterMiddleware`` through two model turns.
   The first turn calls ``tool_search`` which promotes a tool. The second
   turn must see that tool's schema in ``request.tools``. If
   ``get_available_tools`` were to run again between the two turns and reset
   the registry, the second turn's filter would strip the tool.

Strategy: use the production ``deerflow.tools.tools.get_available_tools``
unmodified; mock only the LLM and the MCP tool source. Patch
``deerflow.mcp.cache.get_cached_mcp_tools`` (the symbol that
``get_available_tools`` resolves via lazy import) to return our fixture
tools so we don't need a real MCP server.
"""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import Runnable
from langchain_core.tools import tool as as_tool


class FakeToolCallingModel(FakeMessagesListChatModel):
    """FakeMessagesListChatModel + no-op bind_tools so create_agent works."""

    def bind_tools(  # type: ignore[override]
        self,
        tools: Any,
        *,
        tool_choice: Any = None,
        **kwargs: Any,
    ) -> Runnable:
        return self


# ---------------------------------------------------------------------------
# Fixtures: a fake MCP tool source + a way to force config.tool_search.enabled
# ---------------------------------------------------------------------------


@as_tool
def fake_mcp_search(query: str) -> str:
    """Pretend to search a knowledge base for the given query."""
    return f"results for {query}"


@as_tool
def fake_mcp_fetch(url: str) -> str:
    """Pretend to fetch a page at the given URL."""
    return f"content of {url}"


@pytest.fixture(autouse=True)
def _supply_env(monkeypatch: pytest.MonkeyPatch):
    """config.yaml references $OPENAI_API_KEY at parse time; supply a placeholder."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake-not-used")
    monkeypatch.setenv("OPENAI_API_BASE", "https://example.invalid")


@pytest.fixture(autouse=True)
def _reset_deferred_registry_between_tests():
    """Each test must start with a clean ContextVar.

    The registry lives in a module-level ContextVar with no per-task isolation
    in a synchronous test runner, so one test's promotion can leak into the
    next and silently break filter assertions.
    """
    from deerflow.tools.builtins.tool_search import reset_deferred_registry

    reset_deferred_registry()
    yield
    reset_deferred_registry()


def _patch_mcp_pipeline(monkeypatch: pytest.MonkeyPatch, mcp_tools: list) -> None:
    """Make get_available_tools believe an MCP server is registered.

    Build a real ``ExtensionsConfig`` with one enabled MCP server entry so
    that both ``AppConfig.from_file`` (which calls
    ``ExtensionsConfig.from_file().model_dump()``) and ``tools.get_available_tools``
    (which calls ``ExtensionsConfig.from_file().get_enabled_mcp_servers()``)
    see a valid instance. Then point the MCP tool cache at our fixture tools.
    """
    from deerflow.config.extensions_config import ExtensionsConfig, McpServerConfig

    real_ext = ExtensionsConfig(
        mcpServers={"fake-server": McpServerConfig(type="stdio", command="echo", enabled=True)},
    )
    monkeypatch.setattr(
        "deerflow.config.extensions_config.ExtensionsConfig.from_file",
        classmethod(lambda cls: real_ext),
    )
    monkeypatch.setattr("deerflow.mcp.cache.get_cached_mcp_tools", lambda: list(mcp_tools))


def _force_tool_search_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force config.tool_search.enabled=True without touching the yaml.

    Calling the real ``get_app_config()`` would trigger ``_apply_singleton_configs``
    which permanently mutates module-level singletons (``_memory_config``,
    ``_title_config``, …) to match the developer's ``config.yaml`` — even
    after pytest restores our patch. That leaks across tests later in the
    run that rely on those singletons' DEFAULTS (e.g. memory queue tests
    require ``_memory_config.enabled = True``, which is the dataclass default
    but FALSE in the actual yaml).

    Build a minimal mock AppConfig instead and never call the real loader.
    """
    from deerflow.config.app_config import AppConfig
    from deerflow.config.tool_search_config import ToolSearchConfig

    mock_cfg = AppConfig.model_construct(
        log_level="info",
        models=[],
        tools=[],
        tool_groups=[],
        sandbox=AppConfig.model_fields["sandbox"].annotation.model_construct(use="x"),
        tool_search=ToolSearchConfig(enabled=True),
    )
    monkeypatch.setattr("deerflow.tools.tools.get_app_config", lambda: mock_cfg)


# ---------------------------------------------------------------------------
# Section A — direct unit-level reproduction
# ---------------------------------------------------------------------------


def test_get_available_tools_preserves_promotions_across_reentrant_calls(monkeypatch: pytest.MonkeyPatch):
    """Re-entrant ``get_available_tools()`` must preserve prior promotions.

    Step 1: call get_available_tools() — registers MCP tools as deferred.
    Step 2: simulate the agent calling tool_search by promoting one tool.
    Step 3: call get_available_tools() again (the same code path
            ``task_tool`` exercises mid-run).

    Assertion: after step 3, the promoted tool is STILL promoted (not
    re-deferred). On ``main`` before the fix, step 3's
    ``reset_deferred_registry()`` wiped the promotion and re-registered
    every MCP tool as deferred — this assertion fired with
    ``REGRESSION (#2884)``.
    """
    from deerflow.tools.builtins.tool_search import get_deferred_registry
    from deerflow.tools.tools import get_available_tools

    _patch_mcp_pipeline(monkeypatch, [fake_mcp_search, fake_mcp_fetch])
    _force_tool_search_enabled(monkeypatch)

    # Step 1: first call — both MCP tools start deferred
    get_available_tools()
    reg1 = get_deferred_registry()
    assert reg1 is not None
    assert {e.name for e in reg1.entries} == {"fake_mcp_search", "fake_mcp_fetch"}

    # Step 2: simulate tool_search promoting one of them
    reg1.promote({"fake_mcp_search"})
    assert {e.name for e in reg1.entries} == {"fake_mcp_fetch"}, "Sanity: promote should remove fake_mcp_search"

    # Step 3: second call — registry must NOT silently undo the promotion
    get_available_tools()
    reg2 = get_deferred_registry()
    assert reg2 is not None
    deferred_after = {e.name for e in reg2.entries}
    assert "fake_mcp_search" not in deferred_after, f"REGRESSION (#2884): get_available_tools wiped the deferred registry, re-deferring a tool that was already promoted by tool_search. deferred_after_second_call={deferred_after!r}"


# ---------------------------------------------------------------------------
# Section B — graph-execution reproduction
# ---------------------------------------------------------------------------


class _ToolSearchPromotingModel(FakeToolCallingModel):
    """Two-turn model that:

      Turn 1 → emit a tool_call for ``tool_search`` (the real one)
      Turn 2 → emit a tool_call for ``fake_mcp_search`` (the promoted tool)

    Records the tools it received on each turn so the test can inspect what
    DeferredToolFilterMiddleware actually fed to ``bind_tools``.
    """

    bound_tools_per_turn: list[list[str]] = []

    def bind_tools(  # type: ignore[override]
        self,
        tools: Any,
        *,
        tool_choice: Any = None,
        **kwargs: Any,
    ) -> Runnable:
        # Record the tool names the model would see in this turn
        names = [getattr(t, "name", getattr(t, "__name__", repr(t))) for t in tools]
        self.bound_tools_per_turn.append(names)
        return self


def _build_promoting_model() -> _ToolSearchPromotingModel:
    return _ToolSearchPromotingModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "tool_search",
                        "args": {"query": "select:fake_mcp_search"},
                        "id": "call_search_1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "fake_mcp_search",
                        "args": {"query": "hello"},
                        "id": "call_mcp_1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="all done"),
        ]
    )


def test_promoted_tool_is_visible_to_model_on_second_turn(monkeypatch: pytest.MonkeyPatch):
    """End-to-end: drive a real create_agent graph through two turns.

    Without the fix, the second-turn bind_tools call should NOT contain
    fake_mcp_search (because DeferredToolFilterMiddleware sees it in the
    registry and strips it). With the fix, the model sees the schema and can
    invoke it.
    """
    from langchain.agents import create_agent

    from deerflow.agents.middlewares.deferred_tool_filter_middleware import DeferredToolFilterMiddleware
    from deerflow.tools.tools import get_available_tools

    _patch_mcp_pipeline(monkeypatch, [fake_mcp_search, fake_mcp_fetch])
    _force_tool_search_enabled(monkeypatch)

    tools = get_available_tools()
    # Sanity: the assembled tool list includes the deferred tools (they're in
    # bind_tools but DeferredToolFilterMiddleware strips deferred ones before
    # they reach the model)
    tool_names = {getattr(t, "name", "") for t in tools}
    assert {"tool_search", "fake_mcp_search", "fake_mcp_fetch"} <= tool_names

    model = _build_promoting_model()
    model.bound_tools_per_turn = []  # reset class-level recorder

    graph = create_agent(
        model=model,
        tools=tools,
        middleware=[DeferredToolFilterMiddleware()],
        system_prompt="bug-2884-repro",
    )

    graph.invoke({"messages": [HumanMessage(content="use the search tool")]})

    # Turn 1: model should NOT see fake_mcp_search (it's deferred)
    turn1 = set(model.bound_tools_per_turn[0])
    assert "fake_mcp_search" not in turn1, f"Turn 1 sanity: deferred tools must be hidden from the model. Saw: {turn1!r}"
    assert "tool_search" in turn1, f"Turn 1 sanity: tool_search must be visible so the agent can discover. Saw: {turn1!r}"

    # Turn 2: AFTER tool_search promotes fake_mcp_search, the model must see it.
    # This is the load-bearing assertion for issue #2884.
    assert len(model.bound_tools_per_turn) >= 2, f"Expected at least 2 model turns, got {len(model.bound_tools_per_turn)}"
    turn2 = set(model.bound_tools_per_turn[1])
    assert "fake_mcp_search" in turn2, f"REGRESSION (#2884): tool_search promoted fake_mcp_search in turn 1, but the deferred-tool filter still hid it from the model in turn 2. Turn 2 bound tools: {turn2!r}"


# ---------------------------------------------------------------------------
# Section C — the actual issue #2884 trigger: a re-entrant
# get_available_tools call (e.g. when task_tool spawns a subagent) must not
# wipe the parent's promotion.
# ---------------------------------------------------------------------------


def test_reentrant_get_available_tools_preserves_promotion(monkeypatch: pytest.MonkeyPatch):
    """Issue #2884 in its real shape: a re-entrant get_available_tools call
    (the same pattern that happens when ``task_tool`` builds a subagent's
    toolset mid-run) must not wipe the parent agent's tool_search promotions.

    Turn 1's tool batch contains BOTH ``tool_search`` (which promotes
    ``fake_mcp_search``) AND ``fake_subagent_trigger`` (which calls
    ``get_available_tools`` again — exactly what ``task_tool`` does when it
    builds a subagent's toolset). With the fix, turn 2's bind_tools sees the
    promoted tool. Without the fix, the re-entry wipes the registry and
    the filter re-hides it.
    """
    from langchain.agents import create_agent

    from deerflow.agents.middlewares.deferred_tool_filter_middleware import DeferredToolFilterMiddleware
    from deerflow.tools.tools import get_available_tools

    _patch_mcp_pipeline(monkeypatch, [fake_mcp_search, fake_mcp_fetch])
    _force_tool_search_enabled(monkeypatch)

    # The trigger tool simulates what task_tool does internally: rebuild the
    # toolset by calling get_available_tools while the registry is live.
    @as_tool
    def fake_subagent_trigger(prompt: str) -> str:
        """Pretend to spawn a subagent. Internally rebuilds the toolset."""
        get_available_tools(subagent_enabled=False)
        return f"spawned subagent for: {prompt}"

    tools = get_available_tools() + [fake_subagent_trigger]

    bound_per_turn: list[list[str]] = []

    class _Model(FakeToolCallingModel):
        def bind_tools(self, tools_arg, **kwargs):  # type: ignore[override]
            bound_per_turn.append([getattr(t, "name", repr(t)) for t in tools_arg])
            return self

    model = _Model(
        responses=[
            # Turn 1: do both in one batch — promote AND trigger the
            # subagent-style rebuild. LangGraph executes them in order in the
            # same agent step.
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "tool_search",
                        "args": {"query": "select:fake_mcp_search"},
                        "id": "call_search_1",
                        "type": "tool_call",
                    },
                    {
                        "name": "fake_subagent_trigger",
                        "args": {"prompt": "go"},
                        "id": "call_trigger_1",
                        "type": "tool_call",
                    },
                ],
            ),
            # Turn 2: try to invoke the promoted tool. The model gets this
            # turn only if turn 1's bind_tools recorded what the filter sent.
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "fake_mcp_search",
                        "args": {"query": "hello"},
                        "id": "call_mcp_1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="all done"),
        ]
    )

    graph = create_agent(
        model=model,
        tools=tools,
        middleware=[DeferredToolFilterMiddleware()],
        system_prompt="bug-2884-subagent-repro",
    )
    graph.invoke({"messages": [HumanMessage(content="use the search tool")]})

    # Turn 1 sanity: deferred tool not visible yet
    assert "fake_mcp_search" not in set(bound_per_turn[0]), bound_per_turn[0]

    # The smoking-gun assertion: turn 2 sees the promoted tool DESPITE the
    # re-entrant get_available_tools call that happened in turn 1's tool batch.
    assert len(bound_per_turn) >= 2, f"Expected ≥2 turns, got {len(bound_per_turn)}"
    turn2 = set(bound_per_turn[1])
    assert "fake_mcp_search" in turn2, f"REGRESSION (#2884): a re-entrant get_available_tools call (e.g. task_tool spawning a subagent) wiped the parent agent's promotion. Turn 2 bound tools: {turn2!r}"
