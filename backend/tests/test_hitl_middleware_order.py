"""Regression tests for tool-approval placement in the middleware chain.

The middleware is deliberately NOT registered yet: a park is only answerable by
a client that can read ``__interrupt__`` and post
``Command(resume={"decisions": [...]})``, and neither the web UI nor the TUI
consumes interrupts at this revision. Registering it would let
``tools[].interrupt_on`` strand a bundled-client run with no way to approve or
reject. See ``build_middlewares`` in ``deerflow/agents/lead_agent/agent.py``.

So this file pins two things. First, that the chain stays inert while the
clients cannot answer — ``interrupt_on`` must not park a Web/TUI run. Second,
the ordering constraint the registration has to satisfy once it is restored:
``after_model`` hooks dispatch in REVERSE list order, so a middleware appended
later runs earlier. Tool approval must therefore be appended BEFORE
``ClarificationMiddleware`` so that Clarification runs first — a clarification
request drops its sibling tool calls, and gating those siblings first would ask
the human to review calls that are about to be discarded. That order lives in
source until the registration returns, so it is asserted against the source.
"""

from __future__ import annotations

import inspect

import pytest

from deerflow.agents.lead_agent import agent as agent_module
from deerflow.agents.lead_agent.agent import build_middlewares
from deerflow.agents.middlewares.clarification_middleware import ClarificationMiddleware
from deerflow.agents.middlewares.human_in_the_loop import DeerFlowHumanInTheLoopMiddleware
from deerflow.config.app_config import AppConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.config.tool_config import InterruptOnConfig, ToolConfig


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


def test_gated_tool_does_not_park_a_bundled_client_run(gated_chain):
    """``interrupt_on`` stays inert until a client can answer the park.

    A registered gate would interrupt a Web/TUI run that has no approval
    surface, leaving the thread unresumable through the product UI.
    """
    assert not any(isinstance(m, DeerFlowHumanInTheLoopMiddleware) for m in gated_chain)


def test_clarification_is_last_in_the_list(gated_chain):
    """ClarificationMiddleware stays the final append (first to dispatch)."""
    assert isinstance(gated_chain[-1], ClarificationMiddleware)


def test_approval_middleware_absent_when_no_tool_is_gated():
    """No tool configures ``interrupt_on``, so the chain is untouched."""
    chain = _chain(ToolConfig(name="bash_tool", group="sandbox", use="deerflow.sandbox.tools:bash_tool"))
    assert not any(isinstance(m, DeerFlowHumanInTheLoopMiddleware) for m in chain)
    assert isinstance(chain[-1], ClarificationMiddleware)


def test_approval_registration_site_precedes_clarification_append():
    """The commented-out registration sits before the Clarification append.

    Reverse ``after_model`` dispatch makes list position the run order, so
    restoring the registration must not move it past Clarification. Asserting
    against the source keeps that constraint recorded while the call is
    commented out; it becomes a live chain assertion again once the web-UI
    approval card ships and the lines are uncommented.
    """
    source = inspect.getsource(agent_module.build_middlewares)

    approval_at = source.index("create_interrupt_middleware(resolved_app_config")
    clarification_at = source.index("middlewares.append(ClarificationMiddleware())")

    assert approval_at < clarification_at, (
        "The tool-approval registration must stay above the ClarificationMiddleware append; reverse after_model dispatch then runs Clarification first, pruning its sibling tool calls before they are reviewed."
    )
