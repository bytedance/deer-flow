"""Regressions for the deferred-tool redesign (#3272).

- Cross-context: building the graph in one async context and running it in a
  sibling context (that did NOT inherit the build context) must still hide
  deferred tools. The old ContextVar implementation failed this; the closure +
  graph-state implementation must pass.
- Policy leak (Finding 1): a tool removed by policy must not be searchable.
- Fail-closed (Finding 2): a wiring regression must raise, not silently leak.
- #2884 isolation: a second (subagent-style) setup build must not affect the
  lead agent's middleware/promotion.
"""

import asyncio

import pytest
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool as as_tool

from deerflow.agents.middlewares.deferred_tool_filter_middleware import DeferredToolFilterMiddleware
from deerflow.tools.builtins.tool_search import DeferredToolSetup, build_deferred_tool_setup


@as_tool
def active_tool(x: str) -> str:
    "active"
    return x


@as_tool
def mcp_secret(x: str) -> str:
    "deferred mcp tool — must be hidden from bind_tools until promoted"
    return x


def _tag(t):
    t.metadata = {**(t.metadata or {}), "deerflow_mcp": True}
    return t


_BOUND: list[list[str]] = []


class _RecordingModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        _BOUND.append([getattr(t, "name", None) for t in tools])
        return self


def _build_graph():
    filtered = [active_tool, _tag(mcp_secret)]
    setup = build_deferred_tool_setup(filtered, enabled=True)
    final = [*filtered, setup.tool_search_tool]
    model = _RecordingModel(messages=iter([AIMessage(content="done")] * 4))
    return create_agent(
        model=model,
        tools=final,
        middleware=[DeferredToolFilterMiddleware(setup.deferred_names, setup.catalog_hash)],
        system_prompt="t",
    )


async def _abuild():
    return _build_graph()


def test_deferred_hidden_when_built_and_run_in_different_contexts():
    """Build in one task, run in a sibling task that did not inherit it."""
    _BOUND.clear()

    async def main():
        graph = await asyncio.create_task(_abuild())

        async def run():
            await graph.ainvoke({"messages": [HumanMessage(content="hi")]})

        await asyncio.create_task(run())

    asyncio.run(main())

    assert _BOUND, "model was never bound"
    assert not any("mcp_secret" in names for names in _BOUND), f"deferred MCP tool leaked into bind_tools: {_BOUND}"


def test_policy_excluded_mcp_tool_not_in_catalog():
    """Finding 1: a tool removed by policy is not searchable/exposed."""
    filtered_after_policy = [active_tool]  # mcp_secret denied by skill allowed-tools
    setup = build_deferred_tool_setup(filtered_after_policy, enabled=True)
    assert setup.deferred_names == frozenset()
    assert setup.tool_search_tool is None


def test_fail_closed_when_mcp_survives_without_setup(monkeypatch):
    """Finding 2: simulate a wiring regression and assert it fails loudly.

    ``_assemble_deferred`` lazy-imports ``build_deferred_tool_setup`` from the
    source module, so patch it there (not on the agent module).
    """
    from deerflow.agents.lead_agent import agent as agentmod

    monkeypatch.setattr(
        "deerflow.tools.builtins.tool_search.build_deferred_tool_setup",
        lambda tools, *, enabled: DeferredToolSetup(None, frozenset(), None),
    )
    with pytest.raises(RuntimeError, match="fail-closed"):
        agentmod._assemble_deferred([_tag(mcp_secret)], enabled=True)


def test_subagent_reentry_does_not_touch_lead_state():
    """#2884: building a second (subagent) setup must not affect the lead's
    middleware. With no shared registry/ContextVar, the lead middleware depends
    only on its own deferred_names + the passed state."""
    lead_setup = build_deferred_tool_setup([active_tool, _tag(mcp_secret)], enabled=True)
    mw = DeferredToolFilterMiddleware(lead_setup.deferred_names, lead_setup.catalog_hash)

    # Simulate a subagent build re-entering tool assembly with its own setup.
    _ = build_deferred_tool_setup([_tag(mcp_secret)], enabled=True)

    class _Req:
        def __init__(self):
            self.tools = [active_tool, mcp_secret]
            self.state = {"promoted": {"catalog_hash": lead_setup.catalog_hash, "names": ["mcp_secret"]}}

        def override(self, tools):
            self.tools = tools
            return self

    out = mw._filter_tools(_Req())
    assert {t.name for t in out.tools} == {"active_tool", "mcp_secret"}  # promotion intact
