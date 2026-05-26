"""Real-LLM end-to-end verification for issue #2884.

Drives a real ``langchain.agents.create_agent`` graph against a real OpenAI-
compatible LLM (one-api gateway), bound through ``DeferredToolFilterMiddleware``
and the production ``get_available_tools`` pipeline. The only thing we mock is
the MCP tool source — we hand-roll two ``@tool``s and inject them through
``deerflow.mcp.cache.get_cached_mcp_tools``.

The flow exercised:
  1. Turn 1: agent sees ``tool_search`` (plus a ``fake_subagent_trigger``
     that re-enters ``get_available_tools`` on the same task — this is the
     code path issue #2884 reports). It must call ``tool_search`` to
     discover the deferred ``fake_calculator`` tool.
  2. Tool batch: ``tool_search`` promotes ``fake_calculator``;
     ``fake_subagent_trigger`` re-enters ``get_available_tools``.
  3. Turn 2: the promoted ``fake_calculator`` schema must reach the model
     so it can actually call it. Without this PR's fix, the re-entry wipes
     the promotion and the model can no longer invoke the tool.

Skipped unless ``ONEAPI_E2E=1`` is set so this doesn't burn credits on every
test run. Run with::

    ONEAPI_E2E=1 OPENAI_API_KEY=... OPENAI_API_BASE=... \
        PYTHONPATH=. uv run pytest \
        tests/test_deferred_tool_promotion_real_llm.py -v -s
"""

from __future__ import annotations

import os

import pytest
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool as as_tool

# ---------------------------------------------------------------------------
# Skip control: only run when explicitly opted in.
# ---------------------------------------------------------------------------


pytestmark = pytest.mark.skipif(
    os.getenv("ONEAPI_E2E") != "1",
    reason="Real-LLM e2e: opt in with ONEAPI_E2E=1 (requires OPENAI_API_KEY + OPENAI_API_BASE)",
)


# ---------------------------------------------------------------------------
# Fake "MCP" tools the agent should discover via tool_search.
# Keep them obviously synthetic so the model can pattern-match the search.
# ---------------------------------------------------------------------------


_calls: list[str] = []


@as_tool
def fake_calculator(expression: str) -> str:
    """Evaluate a tiny arithmetic expression like '2 + 2'.

    Reserved for the user — only call this if the user asks for arithmetic.
    """
    _calls.append(f"fake_calculator:{expression}")
    try:
        # Trivially safe-eval just for the e2e check
        allowed = set("0123456789+-*/() .")
        if not set(expression) <= allowed:
            return "expression contains disallowed characters"
        return str(eval(expression, {"__builtins__": {}}, {}))  # noqa: S307
    except Exception as e:
        return f"error: {e}"


@as_tool
def fake_translator(text: str, target_lang: str) -> str:
    """Translate text into the given language code. Decorative — not used."""
    _calls.append(f"fake_translator:{text}:{target_lang}")
    return f"[{target_lang}] {text}"


# ---------------------------------------------------------------------------
# Pipeline wiring (same shape as the in-process tests).
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_registry_between_tests():
    from deerflow.tools.builtins.tool_search import reset_deferred_registry

    reset_deferred_registry()
    yield
    reset_deferred_registry()


def _patch_mcp_pipeline(monkeypatch: pytest.MonkeyPatch, mcp_tools: list) -> None:
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
    """Build a minimal mock AppConfig and patch the symbol — never call the
    real loader, which would trigger ``_apply_singleton_configs`` and
    permanently mutate cross-test singletons (memory, title, …)."""
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
# Real-LLM e2e test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_real_llm_promotes_then_invokes_with_subagent_reentry(monkeypatch: pytest.MonkeyPatch):
    """End-to-end against a real OpenAI-compatible LLM.

    The model must:
      Turn 1 — see ``tool_search`` (deferred tools aren't bound yet) and
               batch-call BOTH ``tool_search(select:fake_calculator)`` AND
               ``fake_subagent_trigger(...)``.
      Turn 2 — call ``fake_calculator`` and finish.

    Pass criterion: ``fake_calculator`` actually gets invoked at the tool
    layer — recorded in ``_calls`` — which proves the model received the
    promoted schema after the re-entrant ``get_available_tools`` call.
    """
    from langchain.agents import create_agent
    from langchain_openai import ChatOpenAI

    from deerflow.agents.middlewares.deferred_tool_filter_middleware import DeferredToolFilterMiddleware
    from deerflow.tools.tools import get_available_tools

    _patch_mcp_pipeline(monkeypatch, [fake_calculator, fake_translator])
    _force_tool_search_enabled(monkeypatch)
    _calls.clear()

    @as_tool
    async def fake_subagent_trigger(prompt: str) -> str:
        """Pretend to spawn a subagent. Internally rebuilds the toolset.

        Use this whenever the user asks you to delegate work — pass a short
        description as ``prompt``.
        """
        # ``task_tool`` does this internally. Whether the registry-reset that
        # used to happen here actually leaks back to the parent task depends
        # on asyncio's implicit context-copying semantics (gather creates
        # child tasks with copied contexts, so reset_deferred_registry is
        # task-local) — but the fix in this PR is what GUARANTEES the
        # promotion sticks regardless of which integration path triggers a
        # re-entrant ``get_available_tools`` call.
        get_available_tools(subagent_enabled=False)
        _calls.append(f"fake_subagent_trigger:{prompt}")
        return "subagent completed"

    tools = get_available_tools() + [fake_subagent_trigger]

    model = ChatOpenAI(
        model=os.environ.get("ONEAPI_MODEL", "claude-sonnet-4-6"),
        api_key=os.environ["OPENAI_API_KEY"],
        base_url=os.environ["OPENAI_API_BASE"],
        temperature=0,
        max_retries=1,
    )

    system_prompt = (
        "You are a meticulous assistant. Available deferred tools include a "
        "calculator and a translator — their schemas are hidden until you "
        "search for them via tool_search.\n\n"
        "Procedure for the user's request:\n"
        "  1. Call tool_search with query 'select:fake_calculator' AND "
        "in the SAME tool batch also call fake_subagent_trigger(prompt='go') "
        "to delegate the side work. Put both tool_calls in your first response.\n"
        "  2. After both tool messages come back, call fake_calculator with "
        "the user's expression.\n"
        "  3. Reply with just the numeric result."
    )

    graph = create_agent(
        model=model,
        tools=tools,
        middleware=[DeferredToolFilterMiddleware()],
        system_prompt=system_prompt,
    )

    result = await graph.ainvoke(
        {"messages": [HumanMessage(content="What is 17 * 23? Use the deferred calculator tool.")]},
        config={"recursion_limit": 12},
    )

    print("\n=== tool calls recorded ===")
    for c in _calls:
        print(f"  {c}")
    print("\n=== final message ===")
    final_text = result["messages"][-1].content if result["messages"] else "(none)"
    print(f"  {final_text!r}")

    # The smoking-gun assertion: fake_calculator was actually invoked at the
    # tool layer. This is only possible if the promoted schema reached the
    # model in turn 2, despite the subagent-style re-entry in turn 1.
    calc_calls = [c for c in _calls if c.startswith("fake_calculator:")]
    assert calc_calls, f"REGRESSION (#2884): the model never managed to call fake_calculator. All recorded tool calls: {_calls!r}. Final text: {final_text!r}"

    # And the math should actually be done correctly (sanity that the LLM
    # really used the result, not just hallucinated the answer).
    assert "391" in str(final_text), f"Model didn't surface 17*23=391. Final text: {final_text!r}"
