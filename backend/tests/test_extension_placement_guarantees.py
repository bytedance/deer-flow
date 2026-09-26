"""The guarantee each Placement makes must be met by the real stack.

Neither the type system nor the version number can catch a broken guarantee:
if a new request-transforming middleware is appended inner of the
MODEL_PHYSICAL anchor, the anchor table, the types and the pip constraints all
stay valid while the promise silently stops holding. These tests are the only
thing standing between that change and a released extension observing the wrong
data.
"""

from __future__ import annotations

from deerflow_extension_api import AgentScope, MiddlewarePlacement, Placement
from langchain.agents.middleware import AgentMiddleware

from deerflow.agents.lead_agent.agent import build_middlewares
from deerflow.agents.middlewares.tool_error_handling_middleware import (
    build_subagent_runtime_middlewares,
)
from deerflow.config.app_config import AppConfig
from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.extensions.isolation import IsolatedMiddleware
from deerflow.extensions.registry import ExtensionRegistry
from deerflow.extensions.stack import middleware_implements


class _Probe(AgentMiddleware):
    def __init__(self, tag: str) -> None:
        super().__init__()
        self.tag = tag


def _extensions(*placements: MiddlewarePlacement):
    class _C:
        def contribute_middlewares(self, app_store, ctx):
            return placements

    registry = ExtensionRegistry()
    with registry.attributed_to("probe:install"):
        registry.middlewares(_C())
    return registry.build()


def _stack_with(*placements: MiddlewarePlacement):
    return build_middlewares(
        config={"configurable": {}},
        model_name="gpt-4o",
        app_config=AppConfig(sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider")),
        extensions=_extensions(*placements),
    )


def _subagent_stack_with(*placements: MiddlewarePlacement):
    return build_subagent_runtime_middlewares(
        app_config=AppConfig(sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider")),
        model_name="gpt-4o",
        extensions=_extensions(*placements),
    )


def _index_of_probe(stack, tag: str) -> int:
    for index, middleware in enumerate(stack):
        target = middleware.inner if isinstance(middleware, IsolatedMiddleware) else middleware
        if isinstance(target, _Probe) and target.tag == tag:
            return index
    raise AssertionError(f"probe {tag!r} not found in stack")


def _unwrap(middleware):
    return middleware.inner if isinstance(middleware, IsolatedMiddleware) else middleware


def test_model_physical_sees_the_final_request():
    """Nothing inner of MODEL_PHYSICAL may transform the model request."""
    stack = _stack_with(MiddlewarePlacement(_Probe("physical"), Placement.MODEL_PHYSICAL))
    index = _index_of_probe(stack, "physical")
    offenders = [type(_unwrap(m)).__name__ for m in stack[index + 1 :] if middleware_implements(_unwrap(m), "wrap_model_call")]
    assert offenders == [], (
        f"these middlewares sit inner of the MODEL_PHYSICAL anchor and wrap model calls, breaking its documented guarantee: {offenders}. Either move them outer of the anchor or update the anchor table in deerflow/extensions/stack.py."
    )


def test_lead_model_physical_uses_the_innermost_tail_anchor():
    """A configured duplicate must not capture the lead's type-based anchor."""
    app_config = AppConfig(sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"))
    app_config.extensions = ExtensionsConfig(middlewares=["deerflow.agents.middlewares.safety_finish_reason_middleware:SafetyFinishReasonMiddleware"])
    stack = build_middlewares(
        config={"configurable": {}},
        model_name="gpt-4o",
        app_config=app_config,
        extensions=_extensions(
            MiddlewarePlacement(
                _Probe("physical"),
                Placement.MODEL_PHYSICAL,
                scope=AgentScope.LEAD,
            )
        ),
    )

    index = _index_of_probe(stack, "physical")
    offenders = [type(_unwrap(m)).__name__ for m in stack[index + 1 :] if middleware_implements(_unwrap(m), "wrap_model_call")]
    assert offenders == []


def test_lead_model_physical_reports_when_the_safety_anchor_is_disabled():
    from deerflow.extensions import get_runtime_diagnostics, reset_runtime_diagnostics

    app_config = AppConfig(sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"))
    app_config.safety_finish_reason.enabled = False
    reset_runtime_diagnostics()
    try:
        build_middlewares(
            config={"configurable": {}},
            model_name="gpt-4o",
            app_config=app_config,
            extensions=_extensions(
                MiddlewarePlacement(
                    _Probe("physical"),
                    Placement.MODEL_PHYSICAL,
                    scope=AgentScope.LEAD,
                )
            ),
        )
        diagnostics = get_runtime_diagnostics()
    finally:
        reset_runtime_diagnostics()

    assert any("MODEL_PHYSICAL fell back to a secondary anchor" in diagnostic.message for diagnostic in diagnostics)


def test_subagent_model_physical_sees_the_final_request():
    """Subagents provide the same final-request guarantee as the lead agent."""
    stack = _subagent_stack_with(
        MiddlewarePlacement(
            _Probe("physical"),
            Placement.MODEL_PHYSICAL,
            scope=AgentScope.SUBAGENT,
        )
    )
    index = _index_of_probe(stack, "physical")
    offenders = [type(_unwrap(m)).__name__ for m in stack[index + 1 :] if middleware_implements(_unwrap(m), "wrap_model_call")]
    assert offenders == [], f"these subagent middlewares sit inner of the MODEL_PHYSICAL anchor and wrap model calls, breaking its documented guarantee: {offenders}"


def test_subagent_model_physical_uses_the_innermost_core_coalescer():
    """A configured duplicate must not capture the type-based primary anchor."""
    app_config = AppConfig(sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"))
    app_config.extensions = ExtensionsConfig(middlewares=["deerflow.agents.middlewares.system_message_coalescing_middleware:SystemMessageCoalescingMiddleware"])
    stack = build_subagent_runtime_middlewares(
        app_config=app_config,
        model_name="gpt-4o",
        extensions=_extensions(
            MiddlewarePlacement(
                _Probe("physical"),
                Placement.MODEL_PHYSICAL,
                scope=AgentScope.SUBAGENT,
            )
        ),
    )

    index = _index_of_probe(stack, "physical")
    offenders = [type(_unwrap(m)).__name__ for m in stack[index + 1 :] if middleware_implements(_unwrap(m), "wrap_model_call")]
    assert offenders == []


#: The single documented middleware allowed inner of TOOL_RAW.
#:
#: ClarificationMiddleware must stay last — it short-circuits the tool loop with
#: Command(goto=END) — and it only intercepts ask_clarification, never
#: transforming the result of a tool that actually executes. So TOOL_RAW still
#: sees raw results. This carve-out is named explicitly rather than the
#: assertion being loosened: any OTHER middleware appearing here is a real
#: regression, and adding to this set must be a deliberate, argued change.
_TOOL_RAW_CARVE_OUT = {"ClarificationMiddleware"}


def test_tool_raw_is_adjacent_to_the_callable_boundary():
    """Nothing inner of TOOL_RAW may wrap tool calls, bar one documented case."""
    stack = _stack_with(MiddlewarePlacement(_Probe("raw"), Placement.TOOL_RAW))
    index = _index_of_probe(stack, "raw")
    offenders = [name for m in stack[index + 1 :] if middleware_implements(_unwrap(m), "wrap_tool_call") and (name := type(_unwrap(m)).__name__) not in _TOOL_RAW_CARVE_OUT]
    assert offenders == [], (
        f"these middlewares sit inner of TOOL_RAW and wrap tool calls: {offenders}. "
        "Either move them outer of the anchor or update the anchor table in "
        "deerflow/extensions/stack.py — do not add them to the carve-out without "
        "an argument for why TOOL_RAW still sees raw results."
    )


def test_the_tool_raw_carve_out_is_actually_needed():
    """Guards the carve-out itself: if ClarificationMiddleware ever stops
    sitting inner of TOOL_RAW, the exemption is dead and must be deleted rather
    than quietly hiding a future regression."""
    stack = _stack_with(MiddlewarePlacement(_Probe("raw"), Placement.TOOL_RAW))
    index = _index_of_probe(stack, "raw")
    inner = {type(_unwrap(m)).__name__ for m in stack[index + 1 :]}
    assert _TOOL_RAW_CARVE_OUT <= inner, f"the carve-out lists middlewares that are no longer inner of TOOL_RAW: {_TOOL_RAW_CARVE_OUT - inner}"


def test_tool_visible_sees_the_final_result():
    """Nothing outer of TOOL_VISIBLE may wrap tool calls."""
    stack = _stack_with(MiddlewarePlacement(_Probe("visible"), Placement.TOOL_VISIBLE))
    index = _index_of_probe(stack, "visible")
    offenders = [type(_unwrap(m)).__name__ for m in stack[:index] if middleware_implements(_unwrap(m), "wrap_tool_call")]
    assert offenders == [], f"these middlewares sit outer of TOOL_VISIBLE and wrap tool calls: {offenders}"


def test_model_logical_is_outer_of_the_retry_loop():
    """One logical decision must stay one event across provider retries."""
    from deerflow.agents.middlewares.llm_error_handling_middleware import LLMErrorHandlingMiddleware

    stack = _stack_with(MiddlewarePlacement(_Probe("logical"), Placement.MODEL_LOGICAL))
    logical = _index_of_probe(stack, "logical")
    retry = next(index for index, m in enumerate(stack) if isinstance(_unwrap(m), LLMErrorHandlingMiddleware))
    assert logical < retry, "MODEL_LOGICAL must be outer of the retry middleware"


def test_logical_and_physical_nest_in_the_right_order():
    """Step:Attempt is 1:N — the logical probe must enclose the physical one."""
    stack = _stack_with(
        MiddlewarePlacement(_Probe("logical"), Placement.MODEL_LOGICAL),
        MiddlewarePlacement(_Probe("physical"), Placement.MODEL_PHYSICAL),
    )
    assert _index_of_probe(stack, "logical") < _index_of_probe(stack, "physical")


def test_visible_and_raw_bracket_the_tool_chain():
    """Visible/raw form a pair around truncation and sanitization; that gap is
    what lets an extension see how much a tool result was altered."""
    stack = _stack_with(
        MiddlewarePlacement(_Probe("visible"), Placement.TOOL_VISIBLE),
        MiddlewarePlacement(_Probe("raw"), Placement.TOOL_RAW),
    )
    visible = _index_of_probe(stack, "visible")
    raw = _index_of_probe(stack, "raw")
    assert visible < raw
    between = [type(_unwrap(m)).__name__ for m in stack[visible + 1 : raw] if middleware_implements(_unwrap(m), "wrap_tool_call")]
    assert between, "the tool-processing chain must sit between the two probes"


def test_all_four_probes_coexist_without_violating_ordering():
    stack = _stack_with(
        MiddlewarePlacement(_Probe("visible"), Placement.TOOL_VISIBLE),
        MiddlewarePlacement(_Probe("logical"), Placement.MODEL_LOGICAL),
        MiddlewarePlacement(_Probe("physical"), Placement.MODEL_PHYSICAL),
        MiddlewarePlacement(_Probe("raw"), Placement.TOOL_RAW),
    )
    indices = [_index_of_probe(stack, tag) for tag in ("visible", "logical", "physical", "raw")]
    assert len(set(indices)) == 4


def test_middleware_implements_detects_overrides():
    class _Wraps(AgentMiddleware):
        def wrap_tool_call(self, request, handler):
            return handler(request)

    class _Plain(AgentMiddleware):
        pass

    assert middleware_implements(_Wraps(), "wrap_tool_call") is True
    assert middleware_implements(_Plain(), "wrap_tool_call") is False
