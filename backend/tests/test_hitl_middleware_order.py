"""Regression test for tool-approval placement in the middleware chain.

``after_model`` hooks dispatch in REVERSE list order, so a middleware appended
later runs earlier. Tool approval must therefore be appended BEFORE
``ClarificationMiddleware`` so that Clarification runs first: a clarification
request drops its sibling tool calls, and gating those siblings first would ask
the human to review calls that are about to be discarded.

It must equally be appended AFTER every AI-only suppression guard, so those
guards dispatch first — see ``TestApprovalRunsAfterTheSuppressionGuards``.
"""

from __future__ import annotations

import pytest

from deerflow.agents.lead_agent.agent import build_middlewares
from deerflow.agents.middlewares.clarification_middleware import ClarificationMiddleware
from deerflow.agents.middlewares.human_in_the_loop import DeerFlowHumanInTheLoopMiddleware
from deerflow.agents.middlewares.loop_detection_middleware import LoopDetectionMiddleware
from deerflow.agents.middlewares.model_length_finish_reason_middleware import ModelLengthFinishReasonMiddleware
from deerflow.agents.middlewares.safety_finish_reason_middleware import SafetyFinishReasonMiddleware
from deerflow.agents.middlewares.subagent_limit_middleware import SubagentLimitMiddleware
from deerflow.agents.middlewares.terminal_response_middleware import TerminalResponseMiddleware
from deerflow.agents.middlewares.token_budget_middleware import TokenBudgetMiddleware
from deerflow.config.app_config import AppConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.config.token_budget_config import TokenBudgetConfig
from deerflow.config.tool_config import InterruptOnConfig, ToolConfig


def _index_of(middlewares, cls) -> int:
    for index, middleware in enumerate(middlewares):
        if isinstance(middleware, cls):
            return index
    raise AssertionError(f"{cls.__name__} is not in the chain")


def _chain(*tools: ToolConfig, config: dict | None = None, app_config: AppConfig | None = None):
    return build_middlewares(
        config=config or {"configurable": {"thread_id": "t-1"}},
        model_name="gpt-4o",
        app_config=app_config
        or AppConfig(
            sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
            tools=list(tools),
        ),
    )


_GATED_BASH = ToolConfig(
    name="bash_tool",
    group="sandbox",
    use="deerflow.sandbox.tools:bash_tool",
    interrupt_on=InterruptOnConfig(allowed_decisions=["approve", "reject"]),
)


@pytest.fixture
def gated_chain():
    """The lead chain with one approval-gated tool configured."""
    return _chain(_GATED_BASH)


@pytest.fixture
def fully_guarded_chain():
    """A gated chain with every AI-only suppression guard also present.

    ``token_budget`` and ``subagent_enabled`` are off by default, so the chain
    from :func:`_chain` alone cannot show whether approval outranks them.
    """
    return _chain(
        config={"configurable": {"thread_id": "t-1", "subagent_enabled": True}},
        app_config=AppConfig(
            sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
            tools=[_GATED_BASH],
            token_budget=TokenBudgetConfig(enabled=True),
        ),
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


class TestApprovalRunsAfterTheSuppressionGuards:
    """Every AI-only guard must dispatch before approval can answer a call.

    The suppression guards all bail on ``not isinstance(messages[-1], AIMessage)``
    (or the ``type != "ai"`` spelling). A ``reject`` or ``respond`` decision
    appends a synthetic ``ToolMessage``, so any guard dispatching *after*
    approval silently skips itself — while LangChain's ``model_to_tools`` router
    searches backward for the AI message and still dispatches its unanswered
    sibling calls. A safety- or length-terminated batch holding a gated ``bash``
    plus an ungated ``write_file`` would therefore execute ``write_file`` after
    the human rejected ``bash``, defeating the whole-batch suppression rule.

    Appended later == dispatched earlier, so approval must be appended BEFORE
    each of these.
    """

    GUARDS = (
        SafetyFinishReasonMiddleware,
        ModelLengthFinishReasonMiddleware,
        TerminalResponseMiddleware,
        TokenBudgetMiddleware,
        LoopDetectionMiddleware,
        SubagentLimitMiddleware,
    )

    @pytest.mark.parametrize("guard", GUARDS, ids=lambda cls: cls.__name__)
    def test_a_suppression_guard_dispatches_before_approval(self, fully_guarded_chain, guard):
        approval_index = _index_of(fully_guarded_chain, DeerFlowHumanInTheLoopMiddleware)
        guard_index = _index_of(fully_guarded_chain, guard)
        assert approval_index < guard_index, (
            f"{guard.__name__} must be appended after tool approval so it DISPATCHES first; otherwise a reject/respond ToolMessage makes its last-message check skip the guard while the tools router still runs the unanswered sibling calls."
        )

    def test_clarification_still_dispatches_before_approval(self, fully_guarded_chain):
        """The pre-existing constraint must survive the reordering."""
        approval_index = _index_of(fully_guarded_chain, DeerFlowHumanInTheLoopMiddleware)
        clarification_index = _index_of(fully_guarded_chain, ClarificationMiddleware)
        assert approval_index < clarification_index


def test_registration_is_not_gated_on_a_client_capability_flag(gated_chain):
    """The gate is registered for every caller; clients opt out per run instead.

    Suppressing the registration would make ``tools[].interrupt_on`` inert and
    ``DeerFlowClient.resume()`` unreachable for the embedded callers that do
    implement the resume protocol. Clients without an approval surface send
    ``disable_tool_approval`` on the run instead — see
    ``tests/test_tool_approval_client_downgrade.py``, which pins that opt-out at
    every such entry point.
    """
    assert any(isinstance(m, DeerFlowHumanInTheLoopMiddleware) for m in gated_chain)
