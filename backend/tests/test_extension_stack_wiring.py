"""Tests for wiring extension contributions into the real middleware builders."""

from __future__ import annotations

import pytest
from deerflow_extension_api import AgentScope, MiddlewarePlacement, Placement
from langchain.agents.middleware import AgentMiddleware

from deerflow.agents.lead_agent.agent import build_middlewares
from deerflow.config.app_config import AppConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.extensions.isolation import IsolatedMiddleware
from deerflow.extensions.registry import ExtensionRegistry
from deerflow.extensions.stack import PLACEMENT_ANCHORS


def _app_config() -> AppConfig:
    # AppConfig.sandbox has no default (`use` is a required field), so a bare
    # AppConfig() always fails pydantic validation in this repo. The brief's
    # verbatim test code assumed a default-constructible AppConfig; every
    # other builder test in this suite (e.g. test_lead_agent_model_resolution.py)
    # supplies this same minimal sandbox stanza for the same reason.
    return AppConfig(sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"))


class _Probe(AgentMiddleware):
    def __init__(self, tag: str) -> None:
        super().__init__()
        self.tag = tag


def _extensions(*placements: MiddlewarePlacement):
    class _C:
        def contribute_middlewares(self, app_store, ctx):
            return placements

    registry = ExtensionRegistry()
    with registry.attributed_to("demo:install"):
        registry.middlewares(_C())
    return registry.build()


def _tags(stack):
    out = []
    for m in stack:
        target = m.inner if isinstance(m, IsolatedMiddleware) else m
        out.append(target.tag if isinstance(target, _Probe) else type(target).__name__)
    return out


def _lead_stack(extensions=None, app_config=None, configurable=None):
    return build_middlewares(
        config={"configurable": configurable or {}},
        model_name="gpt-4o",
        app_config=app_config or _app_config(),
        extensions=extensions,
    )


def test_anchor_table_covers_every_placement():
    assert set(PLACEMENT_ANCHORS) == set(Placement)


def test_zero_extensions_leaves_the_stack_unchanged():
    baseline = _tags(_lead_stack())
    with_empty = _tags(_lead_stack(ExtensionRegistry().build()))
    assert baseline == with_empty
    assert not any(isinstance(m, IsolatedMiddleware) for m in _lead_stack())


def test_zero_extensions_skip_policy_projection(monkeypatch):
    from deerflow.agents.middlewares.tool_error_handling_middleware import (
        build_subagent_runtime_middlewares,
    )
    from deerflow.extensions import policy as policy_module

    def _unexpected_projection(app_config):
        raise AssertionError("zero-extension path constructed an extension payload")

    monkeypatch.setattr(policy_module, "project_host_policy", _unexpected_projection)
    empty = ExtensionRegistry().build()

    _lead_stack(empty)
    build_subagent_runtime_middlewares(app_config=_app_config(), extensions=empty)


def test_zero_extension_composition_reuses_the_built_stack():
    from deerflow_extension_api import AgentBuildContext

    from deerflow.extensions.stack import compose_with_extensions

    middlewares = []
    result = compose_with_extensions(
        middlewares,
        AgentScope.LEAD,
        AgentBuildContext(scope=AgentScope.LEAD),
        ExtensionRegistry().build(),
    )

    assert result is middlewares


def test_bound_build_snapshot_is_used_by_lead_and_subagent_fallbacks():
    from deerflow.agents.middlewares.tool_error_handling_middleware import (
        build_subagent_runtime_middlewares,
    )
    from deerflow.extensions import bind_agent_build_extensions

    lead_capture = _CtxCapture()
    subagent_capture = _CtxCapture()
    lead_extensions = _extensions_with_contributor(lead_capture)
    subagent_extensions = _extensions_with_contributor(subagent_capture)

    with bind_agent_build_extensions(lead_extensions):
        _lead_stack()
    with bind_agent_build_extensions(subagent_extensions):
        build_subagent_runtime_middlewares(app_config=_app_config(), model_name="gpt-4o")

    assert lead_capture.ctx is not None
    assert subagent_capture.ctx is not None


def test_lead_system_middlewares_capture_the_explicit_build_snapshot():
    from deerflow.agents.middlewares.title_middleware import TitleMiddleware

    registry = ExtensionRegistry()
    with registry.attributed_to("observer:install"):
        registry.system_model_observer(object())
    extensions = registry.build()

    stack = _lead_stack(extensions)
    title = next(item for item in stack if isinstance(item, TitleMiddleware))

    assert title._extensions is extensions


def test_tool_visible_lands_at_the_outermost_position():
    stack = _lead_stack(_extensions(MiddlewarePlacement(_Probe("visible"), Placement.TOOL_VISIBLE)))
    assert _tags(stack)[0] == "visible"


def test_model_logical_lands_outside_the_retry_middleware():
    stack = _lead_stack(_extensions(MiddlewarePlacement(_Probe("decision"), Placement.MODEL_LOGICAL)))
    tags = _tags(stack)
    assert tags.index("decision") < tags.index("LLMErrorHandlingMiddleware")


def test_tool_raw_lands_inside_tool_error_handling():
    stack = _lead_stack(_extensions(MiddlewarePlacement(_Probe("raw"), Placement.TOOL_RAW)))
    tags = _tags(stack)
    assert tags.index("raw") > tags.index("ToolErrorHandlingMiddleware")


def test_runtime_isolation_failure_is_recorded_after_stack_composition():
    from deerflow.extensions import get_runtime_diagnostics, reset_runtime_diagnostics

    class _FailingObserver(AgentMiddleware):
        def wrap_tool_call(self, request, handler):
            raise ValueError("observation exploded")

    reset_runtime_diagnostics()
    try:
        stack = _lead_stack(
            _extensions(
                MiddlewarePlacement(
                    _FailingObserver(),
                    Placement.TOOL_VISIBLE,
                )
            )
        )
        isolated = next(middleware for middleware in stack if isinstance(middleware, IsolatedMiddleware))
        handler_calls = 0

        def handler(request):
            nonlocal handler_calls
            handler_calls += 1
            return "core-result"

        assert isolated.wrap_tool_call("request", handler) == "core-result"
        diagnostics = get_runtime_diagnostics()
    finally:
        reset_runtime_diagnostics()

    assert handler_calls == 1
    assert len(diagnostics) == 1
    assert diagnostics[0].source == "demo:install"
    assert diagnostics[0].level == "error"
    assert "wrap_tool_call" in diagnostics[0].message


def test_build_and_runtime_diagnostics_are_each_recorded_once():
    from deerflow.extensions import get_runtime_diagnostics, reset_runtime_diagnostics

    class _FailingObserver(AgentMiddleware):
        def wrap_model_call(self, request, handler):
            raise ValueError("observation exploded")

    app_config = _app_config()
    app_config.safety_finish_reason.enabled = False
    reset_runtime_diagnostics()
    try:
        stack = _lead_stack(
            _extensions(
                MiddlewarePlacement(
                    _FailingObserver(),
                    Placement.MODEL_PHYSICAL,
                )
            ),
            app_config=app_config,
        )
        isolated = next(middleware for middleware in stack if isinstance(middleware, IsolatedMiddleware))

        assert isolated.wrap_model_call("request", lambda request: "core-result") == "core-result"
        diagnostics = get_runtime_diagnostics()
    finally:
        reset_runtime_diagnostics()

    assert [diagnostic.level for diagnostic in diagnostics] == ["warning", "error"]
    assert sum("fell back to a secondary anchor" in diagnostic.message for diagnostic in diagnostics) == 1
    assert sum("wrap_model_call" in diagnostic.message for diagnostic in diagnostics) == 1


def test_lead_only_contribution_is_absent_from_subagent_stack():
    from deerflow.agents.middlewares.tool_error_handling_middleware import (
        build_subagent_runtime_middlewares,
    )

    extensions = _extensions(MiddlewarePlacement(_Probe("lead-only"), Placement.STANDARD, scope=AgentScope.LEAD))
    stack = build_subagent_runtime_middlewares(app_config=_app_config(), extensions=extensions)
    assert "lead-only" not in _tags(stack)


def test_first_subagent_build_resolves_every_lazy_anchor(monkeypatch):
    """A lazy anchor table must be populated before its subagent copy is made.

    ``dict(dict_subclass)`` bypasses the subclass's ``__iter__``/``__len__``
    hooks in CPython.  Building a subagent first therefore used to copy an
    empty table, then populate only MODEL_PHYSICAL as it installed the
    subagent-specific override.
    """
    from deerflow.agents.middlewares.tool_error_handling_middleware import (
        build_subagent_runtime_middlewares,
    )
    from deerflow.extensions import stack as stack_module

    fresh_table = stack_module._AnchorTable()
    monkeypatch.setattr(stack_module._AnchorTable, "_loaded", False)
    monkeypatch.setattr(stack_module, "PLACEMENT_ANCHORS", fresh_table)

    extensions = _extensions(
        MiddlewarePlacement(
            _Probe("subagent-standard"),
            Placement.STANDARD,
            scope=AgentScope.SUBAGENT,
        )
    )
    stack = build_subagent_runtime_middlewares(
        app_config=_app_config(),
        extensions=extensions,
    )

    assert "subagent-standard" in _tags(stack)


def test_core_ordering_table_is_enforced_against_a_real_stack(monkeypatch):
    """The default constraint table must be consulted on the REAL built stack.

    Task 7 deleted the in-builder guard and the test that forced a real
    misordering. Exercising assert_ordering with synthetic classes proves the
    function works; it does not prove the composing builder calls it with
    core_ordering_constraints() against the stack it actually produces. This
    test is the only thing that does.

    It patches the default table rather than reordering real middlewares: the
    builder imports its middlewares inside the function body, so reordering
    them would require stubbing sys.modules entries, which tests the stubbing
    more than the wiring. Patching the table asserts exactly the claim at issue.
    """
    from deerflow.agents.middlewares.input_sanitization_middleware import InputSanitizationMiddleware
    from deerflow.agents.middlewares.tool_error_handling_middleware import ToolErrorHandlingMiddleware
    from deerflow.extensions import ordering as ordering_mod

    # InputSanitization is the outermost wrapper and ToolErrorHandling sits deep
    # in the tail, so demanding the reverse is a constraint the real stack breaks.
    impossible = (
        ordering_mod.OrderingConstraint(
            outer=ToolErrorHandlingMiddleware,
            inner=InputSanitizationMiddleware,
            reason="deliberately inverted for this test",
        ),
    )
    monkeypatch.setattr(ordering_mod, "core_ordering_constraints", lambda: impossible)

    with pytest.raises(RuntimeError) as excinfo:
        _lead_stack()
    message = str(excinfo.value)
    assert "ToolErrorHandlingMiddleware" in message
    assert "InputSanitizationMiddleware" in message
    assert "core middleware order" in message, "with no extension at either participating index the blame must fall on core order"


def test_core_ordering_table_passes_on_the_unmodified_stack():
    """The real stack must satisfy the real constraints — otherwise the test
    above would pass for the wrong reason."""
    _lead_stack()  # must not raise


def test_ordering_violation_raises_and_names_the_extension():
    """A contribution that inverts a core invariant must fail loudly at build
    time — the resulting behaviour would otherwise be wrong without an error."""
    from deerflow.agents.middlewares.tool_error_handling_middleware import ToolErrorHandlingMiddleware
    from deerflow.extensions.ordering import OrderingConstraint, assert_ordering

    stack = [ToolErrorHandlingMiddleware(app_config=_app_config()), _Probe("x")]
    constraints = (OrderingConstraint(outer=_Probe, inner=ToolErrorHandlingMiddleware, reason="test"),)
    with pytest.raises(RuntimeError, match="demo:install"):
        assert_ordering(stack, {1: "demo:install"}, constraints)


# --- AgentBuildContext.policy -----------------------------------------------
#
# Extensions read ctx.policy to adapt metering/behaviour to the limits the
# host actually enforces. Both builders must fill it from the resolved
# AppConfig — the field defaults to an all-disabled snapshot, so an omission
# is silent and hands extensions wrong values.


class _CtxCapture:
    def __init__(self) -> None:
        self.ctx = None

    def contribute_middlewares(self, app_store, ctx):
        self.ctx = ctx
        return ()


def _extensions_with_contributor(contributor):
    registry = ExtensionRegistry()
    with registry.attributed_to("capture:install"):
        registry.middlewares(contributor)
    return registry.build()


def _policy_config() -> AppConfig:
    from deerflow.config.subagents_config import SubagentsAppConfig
    from deerflow.config.token_budget_config import TokenBudgetConfig

    return AppConfig(
        sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
        token_budget=TokenBudgetConfig(
            enabled=True,
            max_tokens=12345,
            max_input_tokens=1000,
            max_output_tokens=2000,
            warn_threshold=0.7,
            hard_stop_threshold=0.95,
        ),
        subagents=SubagentsAppConfig(
            max_total_per_run=7,
            token_budget=TokenBudgetConfig(
                enabled=True,
                max_tokens=54321,
                max_input_tokens=3000,
                max_output_tokens=4000,
                warn_threshold=0.6,
                hard_stop_threshold=0.9,
            ),
        ),
    )


def _assert_projected_policy(policy) -> None:
    assert policy.token_budget_enabled is True
    assert policy.max_input_tokens == 1000
    assert policy.max_output_tokens == 2000
    assert policy.max_total_tokens == 12345
    assert policy.budget_warn_fraction == 0.7
    assert policy.budget_hard_fraction == 0.95
    assert policy.max_subagents_per_run is None


def _assert_subagent_policy(policy) -> None:
    assert policy.token_budget_enabled is True
    assert policy.max_input_tokens == 3000
    assert policy.max_output_tokens == 4000
    assert policy.max_total_tokens == 54321
    assert policy.budget_warn_fraction == 0.6
    assert policy.budget_hard_fraction == 0.9
    assert policy.max_subagents_per_run is None


def test_lead_build_context_carries_the_projected_host_policy():
    capture = _CtxCapture()
    _lead_stack(extensions=_extensions_with_contributor(capture), app_config=_policy_config())
    assert capture.ctx is not None, "the contributor was never consulted"
    _assert_projected_policy(capture.ctx.policy)


def test_subagent_build_context_carries_the_projected_host_policy():
    from deerflow.agents.middlewares.tool_error_handling_middleware import build_subagent_runtime_middlewares

    capture = _CtxCapture()
    build_subagent_runtime_middlewares(
        app_config=_policy_config(),
        model_name="gpt-4o",
        extensions=_extensions_with_contributor(capture),
    )
    assert capture.ctx is not None, "the contributor was never consulted"
    _assert_subagent_policy(capture.ctx.policy)


def test_lead_build_context_projects_the_effective_delegation_override():
    capture = _CtxCapture()
    _lead_stack(
        extensions=_extensions_with_contributor(capture),
        app_config=_policy_config(),
        configurable={
            "subagent_enabled": True,
            "max_total_subagents": 3,
        },
    )

    assert capture.ctx is not None
    assert capture.ctx.policy.max_subagents_per_run == 3
