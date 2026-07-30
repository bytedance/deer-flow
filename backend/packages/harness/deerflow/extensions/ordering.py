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

from deerflow.extensions.isolation import IsolatedMiddleware


@dataclass(frozen=True)
class OrderingConstraint:
    outer: type
    inner: type
    reason: str


def _index_of(middlewares: Sequence[object], target: type) -> int | None:
    for index, middleware in enumerate(middlewares):
        candidate = middleware.inner if isinstance(middleware, IsolatedMiddleware) else middleware
        if isinstance(candidate, target):
            return index
    return None


def assert_ordering(
    middlewares: Sequence[object],
    provenance: Mapping[int, str],
    constraints: Sequence[OrderingConstraint] | None = None,
) -> None:
    """Raise when a constraint is violated. No-op when both sides are absent."""
    for constraint in constraints if constraints is not None else CORE_ORDERING_CONSTRAINTS:
        outer_index = _index_of(middlewares, constraint.outer)
        inner_index = _index_of(middlewares, constraint.inner)
        if outer_index is None or inner_index is None:
            continue
        if outer_index < inner_index:
            continue
        culprits = sorted({source for index in (outer_index, inner_index) if (source := provenance.get(index)) is not None})
        blame = ", ".join(culprits) if culprits else "core middleware order"
        raise RuntimeError(
            f"Middleware ordering constraint violated: {constraint.outer.__name__} must be outer "
            f"(lower index) of {constraint.inner.__name__}, but found at index {outer_index} vs "
            f"{inner_index}. Reason: {constraint.reason}. Contributed by: {blame}."
        )


def _core_constraints() -> tuple[OrderingConstraint, ...]:
    from deerflow.agents.middlewares.tool_error_handling_middleware import ToolErrorHandlingMiddleware
    from deerflow.agents.middlewares.tool_progress_middleware import ToolProgressMiddleware

    return (
        OrderingConstraint(
            outer=ToolProgressMiddleware,
            inner=ToolErrorHandlingMiddleware,
            reason=("ToolProgressMiddleware reads deerflow_tool_meta in _update_state_from_result, so its wrap_tool_call chain must enclose the ToolErrorHandlingMiddleware step that stamps it"),
        ),
    )


class _LazyConstraints(tuple):
    """Defer the middleware imports until first use to avoid an import cycle."""

    _resolved: tuple[OrderingConstraint, ...] | None = None

    def __iter__(self):
        if _LazyConstraints._resolved is None:
            _LazyConstraints._resolved = _core_constraints()
        return iter(_LazyConstraints._resolved)


CORE_ORDERING_CONSTRAINTS = _LazyConstraints()
