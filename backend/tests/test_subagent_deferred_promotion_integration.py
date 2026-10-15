"""End-to-end: the subagent deferral recipe hides then promotes an MCP tool (#3341).

#3272 wired deferred MCP loading into the lead agent only. #3341 extends it to
subagents. This locks the *subagent build recipe* - the shared helpers the
executor now calls (``assemble_deferred_tools`` + ``get_deferred_tools_prompt_section``)
plus the ``DeferredToolFilterMiddleware`` that ``build_subagent_runtime_middlewares``
attaches - composing into the same hide/promote loop the lead has, under the
subagent's build shape (``system_prompt=None`` + a single ``SystemMessage``).

The hide/promote mechanics themselves are also covered for the lead path by
tests/test_deferred_promotion_integration.py; this asserts the subagent recipe
produces an equivalent loop without binding MCP schemas before promotion.

A second test (``test_subagent_builder_emits_working_deferred_filter``) closes the
remaining seam: it sources the filter from the *real* ``build_subagent_runtime_middlewares``
(the exact call ``executor._create_agent`` makes) rather than hand-constructing it, so a
regression in how the builder wires the setup into the filter - wrong catalog hash,
dropped filter, wrong deferred set - is caught at runtime. (Running the full real stack
is intentionally avoided: the other runtime middlewares need sandbox/thread infra to
execute, which would make the test flaky; their attachment + ordering is locked in
tests/test_tool_error_handling_middleware.py instead.)
"""

import asyncio

from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool as as_tool

from deerflow.agents.middlewares.deferred_tool_filter_middleware import DeferredToolFilterMiddleware
from deerflow.agents.thread_state import ThreadState
from deerflow.tools.builtins.tool_search import assemble_deferred_tools, get_deferred_tools_prompt_section
from deerflow.tools.mcp_metadata import tag_mcp_tool


@as_tool
def active_tool(x: str) -> str:
    "An always-active tool."
    return x


@as_tool
def mcp_calc(expression: str) -> str:
    "Evaluate arithmetic."
    return expression


@as_tool
def mcp_other(x: str) -> str:
    "Another deferred MCP tool."
    return x


def test_subagent_deferral_recipe_hides_then_promotes():
    bound: list[list[str]] = []

    class RecordingModel(GenericFakeChatModel):
        def bind_tools(self, tools, **kwargs):
            bound.append([getattr(t, "name", None) for t in tools])
            return self

    # The subagent build path (executor._build_initial_state): policy-filtered
    # tools -> assemble_deferred_tools appends tool_search, fail-closed.
    filtered = [active_tool, tag_mcp_tool(mcp_calc), tag_mcp_tool(mcp_other)]
    final_tools, setup = assemble_deferred_tools(filtered, enabled=True)
    assert "tool_search" in [t.name for t in final_tools]
    assert setup.deferred_names == frozenset({"mcp_calc", "mcp_other"})

    # The subagent injects the section into its single SystemMessage.
    section = get_deferred_tools_prompt_section(deferred_names=setup.deferred_names)
    assert "<available-deferred-tools>" in section
    assert "mcp_calc" in section and "mcp_other" in section

    turn1 = AIMessage(content="", tool_calls=[{"name": "tool_search", "args": {"query": "select:mcp_calc"}, "id": "c1", "type": "tool_call"}])
    turn2 = AIMessage(content="done")
    model = RecordingModel(messages=iter([turn1, turn2]))

    # The middleware DeferredToolFilterMiddleware is exactly what
    # build_subagent_runtime_middlewares attaches for this setup (locked by
    # tests/test_tool_error_handling_middleware.py); the subagent build passes
    # system_prompt=None with state_schema=ThreadState.
    graph = create_agent(
        model=model,
        tools=final_tools,
        middleware=[DeferredToolFilterMiddleware(setup.deferred_names, setup.catalog_hash)],
        system_prompt=None,
        state_schema=ThreadState,
    )

    result = asyncio.run(graph.ainvoke({"messages": [SystemMessage(content=section), HumanMessage(content="use the deferred calculator")]}))

    assert len(bound) >= 2, f"expected >=2 model binds, got {bound}"
    # Turn 1: both deferred MCP tools hidden from the subagent's model binding.
    assert "mcp_calc" not in bound[0] and "mcp_other" not in bound[0]
    # Turn 2: the searched tool is promoted; the un-searched one stays hidden.
    assert "mcp_calc" in bound[1]
    assert "mcp_other" not in bound[1]
    # Promotion recorded in graph state, scoped by catalog hash.
    assert result["promoted"] == {"catalog_hash": setup.catalog_hash, "names": ["mcp_calc"]}


def test_subagent_builder_emits_working_deferred_filter():
    """The real build path the executor calls - ``build_subagent_runtime_middlewares`` -
    must emit a ``DeferredToolFilterMiddleware`` that actually hides/promotes through a
    graph. The recipe test above hand-builds the filter; this sources it from the real
    builder given a real setup, so a regression in the builder's wiring is caught: a
    wrong catalog hash silently stops promotion (turn 2 would keep mcp_calc hidden), a
    dropped filter stops hiding (turn 1 would bind mcp_calc)."""
    from deerflow.agents.middlewares.tool_error_handling_middleware import build_subagent_runtime_middlewares
    from deerflow.config.app_config import AppConfig, CircuitBreakerConfig
    from deerflow.config.guardrails_config import GuardrailsConfig
    from deerflow.config.model_config import ModelConfig
    from deerflow.config.sandbox_config import SandboxConfig

    bound: list[list[str]] = []

    class RecordingModel(GenericFakeChatModel):
        def bind_tools(self, tools, **kwargs):
            bound.append([getattr(t, "name", None) for t in tools])
            return self

    filtered = [active_tool, tag_mcp_tool(mcp_calc), tag_mcp_tool(mcp_other)]
    final_tools, setup = assemble_deferred_tools(filtered, enabled=True)
    section = get_deferred_tools_prompt_section(deferred_names=setup.deferred_names)

    app_config = AppConfig(
        models=[
            ModelConfig(
                name="test-model",
                display_name="test-model",
                description=None,
                use="langchain_openai:ChatOpenAI",
                model="test-model",
                supports_vision=False,
            )
        ],
        sandbox=SandboxConfig(use="test"),
        guardrails=GuardrailsConfig(enabled=False),
        circuit_breaker=CircuitBreakerConfig(failure_threshold=7, recovery_timeout_sec=11),
    )

    # The exact call executor._create_agent makes. Pull the filter the builder
    # produced (not a hand-rolled one) so its wiring - deferred set + catalog hash -
    # is what's under test.
    middlewares = build_subagent_runtime_middlewares(app_config=app_config, model_name="test-model", deferred_setup=setup)
    deferred_filters = [m for m in middlewares if isinstance(m, DeferredToolFilterMiddleware)]
    assert len(deferred_filters) == 1, f"builder must emit exactly one deferred filter, got {[type(m).__name__ for m in middlewares]}"

    turn1 = AIMessage(content="", tool_calls=[{"name": "tool_search", "args": {"query": "select:mcp_calc"}, "id": "c1", "type": "tool_call"}])
    turn2 = AIMessage(content="done")
    model = RecordingModel(messages=iter([turn1, turn2]))

    # Run only the builder-produced filter (the component under test). The other
    # runtime middlewares need sandbox/thread infra to *execute*, so running the
    # full stack here would be flaky; their attachment + ordering before Safety is
    # locked in tests/test_tool_error_handling_middleware.py.
    graph = create_agent(
        model=model,
        tools=final_tools,
        middleware=deferred_filters,
        system_prompt=None,
        state_schema=ThreadState,
    )
    result = asyncio.run(graph.ainvoke({"messages": [SystemMessage(content=section), HumanMessage(content="use the deferred calculator")]}))

    assert len(bound) >= 2, f"expected >=2 model binds, got {bound}"
    # Turn 1: both deferred MCP tools hidden - the builder-produced filter is active.
    assert "mcp_calc" not in bound[0] and "mcp_other" not in bound[0]
    # Turn 2: the searched tool is promoted - proves the builder wired the catalog
    # hash correctly (a wrong hash would leave mcp_calc hidden here).
    assert "mcp_calc" in bound[1]
    assert "mcp_other" not in bound[1]
    assert result["promoted"] == {"catalog_hash": setup.catalog_hash, "names": ["mcp_calc"]}
