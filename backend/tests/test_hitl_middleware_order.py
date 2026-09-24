"""Regression test for tool-approval placement in the middleware chain.

``after_model`` hooks dispatch in REVERSE list order, so a middleware appended
later runs earlier. Tool approval must therefore be appended BEFORE
``ClarificationMiddleware`` so that Clarification runs first: a clarification
request drops its sibling tool calls, and gating those siblings first would ask
the human to review calls that are about to be discarded.
"""

from __future__ import annotations

import pytest

from deerflow.agents.lead_agent.agent import build_middlewares
from deerflow.agents.middlewares.clarification_middleware import ClarificationMiddleware
from deerflow.agents.middlewares.human_in_the_loop import DeerFlowHumanInTheLoopMiddleware
from deerflow.config.app_config import AppConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.config.tool_config import InterruptOnConfig, ToolConfig


def _index_of(middlewares, cls) -> int:
    for index, middleware in enumerate(middlewares):
        if isinstance(middleware, cls):
            return index
    raise AssertionError(f"{cls.__name__} is not in the chain")


def _chain(*tools: ToolConfig):
    return build_middlewares(
        config={"configurable": {"thread_id": "t-1"}},
        model_name="gpt-4o",
        app_config=AppConfig(
            sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
            tools=list(tools),
        ),
    )


@pytest.fixture
def gated_chain():
    """The lead chain with one approval-gated tool configured."""
    return _chain(
        ToolConfig(
            name="bash_tool",
            group="sandbox",
            use="deerflow.sandbox.tools:bash_tool",
            interrupt_on=InterruptOnConfig(allowed_decisions=["approve", "reject"]),
        )
    )


def test_tool_approval_precedes_clarification_in_the_list(gated_chain):
    """Appended before Clarification, so it DISPATCHES after it."""
    approval_index = _index_of(gated_chain, DeerFlowHumanInTheLoopMiddleware)
    clarification_index = _index_of(gated_chain, ClarificationMiddleware)
    assert approval_index < clarification_index, (
        "Tool approval must be appended before ClarificationMiddleware; after_model dispatches in reverse, so this ordering makes Clarification run first and prune its sibling tool calls before they are reviewed."
    )


def test_clarification_is_last_in_the_list(gated_chain):
    """ClarificationMiddleware stays the final append (first to dispatch)."""
    assert isinstance(gated_chain[-1], ClarificationMiddleware)


def test_approval_middleware_absent_when_no_tool_is_gated():
    """No tool configures ``interrupt_on``, so the chain is untouched."""
    chain = _chain(ToolConfig(name="bash_tool", group="sandbox", use="deerflow.sandbox.tools:bash_tool"))
    assert not any(isinstance(m, DeerFlowHumanInTheLoopMiddleware) for m in chain)
    assert isinstance(chain[-1], ClarificationMiddleware)
