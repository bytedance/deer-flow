"""Declarative ordering invariants for the middleware stack.

Replaces hand-written index comparisons. Extension-contributed middlewares are
merged before validation runs, so a contribution cannot slip past an invariant,
and the failure names the extension responsible.

A broken invariant is the one hard failure in this system: unlike a missing
observation, it produces wrong behaviour without an error.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import cache

from deerflow.extensions.isolation import IsolatedMiddleware


@dataclass(frozen=True)
class OrderingConstraint:
    outer: type
    inner: type
    reason: str


def _indices_of(middlewares: Sequence[object], target: type) -> list[int]:
    indices: list[int] = []
    for index, middleware in enumerate(middlewares):
        candidate = middleware.inner if isinstance(middleware, IsolatedMiddleware) else middleware
        if isinstance(candidate, target):
            indices.append(index)
    return indices


def assert_ordering(
    middlewares: Sequence[object],
    provenance: Mapping[int, str],
    constraints: Sequence[OrderingConstraint] | None = None,
) -> None:
    """Raise when a constraint is violated. No-op when both sides are absent."""
    for constraint in constraints if constraints is not None else core_ordering_constraints():
        outer_indices = _indices_of(middlewares, constraint.outer)
        inner_indices = _indices_of(middlewares, constraint.inner)
        if not outer_indices or not inner_indices:
            continue
        if max(outer_indices) < min(inner_indices):
            continue
        violating_indices = [index for index in outer_indices if index >= min(inner_indices)] + [index for index in inner_indices if index <= max(outer_indices)]
        culprits = sorted({source for index in violating_indices if (source := provenance.get(index)) is not None})
        blame = ", ".join(culprits) if culprits else "core middleware order"
        raise RuntimeError(
            f"Middleware ordering constraint violated: {constraint.outer.__name__} must be outer "
            f"(lower index) of every {constraint.inner.__name__}, but found outer indices "
            f"{outer_indices} vs inner indices {inner_indices}. Reason: {constraint.reason}. "
            f"Contributed by: {blame}."
        )


@cache
def core_ordering_constraints() -> tuple[OrderingConstraint, ...]:
    """The host's ordering invariants, resolved on first use.

    Deferred deliberately, and the deferral is about dependency *direction*,
    not just cycles: ``extensions/`` is the layer the middleware layer calls
    into, so importing ``agents.middlewares`` at module scope here would point
    the dependency backwards and close a cycle the moment any middleware
    imports something under ``extensions/`` at module level. Resolution instead
    happens at ``assert_ordering`` time, which already runs inside the
    middleware builder — a forward reference within one layer.

    Returns a plain tuple. The predecessor deferred by way of a ``tuple``
    subclass overriding only ``__iter__``; because a tuple cannot populate its
    own storage after construction, every operation reading that storage
    (``len``, ``bool``, ``in``, indexing, slicing, ``reversed``, ``==``)
    reported an empty sequence while iteration yielded the real constraints.
    Deferring the call instead of faking the value keeps one answer.
    """
    from deerflow.agents.middlewares.read_before_write_middleware import ReadBeforeWriteMiddleware
    from deerflow.agents.middlewares.sandbox_audit_middleware import SandboxAuditMiddleware
    from deerflow.agents.middlewares.tool_error_handling_middleware import ToolErrorHandlingMiddleware
    from deerflow.agents.middlewares.tool_progress_middleware import ToolProgressMiddleware
    from deerflow.agents.middlewares.tool_receipt_middleware import ToolReceiptMiddleware
    from deerflow.guardrails.middleware import GuardrailMiddleware

    return (
        OrderingConstraint(
            outer=ToolProgressMiddleware,
            inner=ToolErrorHandlingMiddleware,
            reason=("ToolProgressMiddleware reads deerflow_tool_meta in _update_state_from_result, so its wrap_tool_call chain must enclose the ToolErrorHandlingMiddleware step that stamps it"),
        ),
        OrderingConstraint(
            outer=ToolReceiptMiddleware,
            inner=ToolErrorHandlingMiddleware,
            reason=("ToolReceiptMiddleware reads the deerflow_tool_meta status stamped by ToolErrorHandlingMiddleware when building each receipt, so its wrap_tool_call chain must enclose the stamping step"),
        ),
        *(
            OrderingConstraint(
                outer=ToolReceiptMiddleware,
                inner=short_circuiter,
                reason=(f"{short_circuiter.__name__} can return or rebuild a ToolMessage without invoking its handler; ToolReceiptMiddleware must wrap it or those results never get a receipt and the ledger silently gaps"),
            )
            for short_circuiter in (
                GuardrailMiddleware,
                SandboxAuditMiddleware,
                ReadBeforeWriteMiddleware,
                ToolProgressMiddleware,
            )
        ),
    )
