"""Tests for declarative middleware ordering constraints."""

from __future__ import annotations

import pytest

from deerflow.extensions.isolation import IsolatedMiddleware
from deerflow.extensions.ordering import OrderingConstraint, assert_ordering


class _Outer:
    pass


class _Inner:
    pass


class _Unrelated:
    pass


_CONSTRAINTS = (OrderingConstraint(outer=_Outer, inner=_Inner, reason="outer must wrap inner"),)


def test_correct_order_passes():
    assert_ordering([_Outer(), _Inner()], {}, _CONSTRAINTS)


def test_reversed_order_raises():
    with pytest.raises(RuntimeError, match="outer must wrap inner"):
        assert_ordering([_Inner(), _Outer()], {}, _CONSTRAINTS)


def test_missing_participant_is_not_a_violation():
    """The stack is conditionally built; an absent middleware means the
    constraint simply does not apply."""
    assert_ordering([_Outer(), _Unrelated()], {}, _CONSTRAINTS)
    assert_ordering([_Unrelated()], {}, _CONSTRAINTS)


def test_violation_message_names_the_responsible_extension():
    """Without attribution, an operator cannot tell which extension to remove."""
    stack = [_Inner(), _Outer()]
    provenance = {0: "bad_ext:install"}
    with pytest.raises(RuntimeError) as excinfo:
        assert_ordering(stack, provenance, _CONSTRAINTS)
    assert "bad_ext:install" in str(excinfo.value)


def test_violation_without_extensions_says_core():
    stack = [_Inner(), _Outer()]
    with pytest.raises(RuntimeError) as excinfo:
        assert_ordering(stack, {}, _CONSTRAINTS)
    assert "core" in str(excinfo.value).lower()


def test_violation_does_not_blame_an_uninvolved_extension():
    """Only the two positions in the violating pair can be responsible. A
    provenance entry for some other index — an extension that contributed
    elsewhere in the stack but is not part of this constraint — must not be
    named, even though it is the only entry in `provenance`."""
    stack = [_Inner(), _Outer(), _Unrelated()]
    provenance = {2: "innocent_ext:install"}
    with pytest.raises(RuntimeError) as excinfo:
        assert_ordering(stack, provenance, _CONSTRAINTS)
    message = str(excinfo.value)
    assert "innocent_ext:install" not in message
    assert "core" in message.lower()


def test_reversed_order_raises_when_a_participant_is_wrapped():
    """Extension-contributed middlewares are wrapped in IsolatedMiddleware before
    they reach the merged stack. If _index_of matched only the wrapper's own
    type, a wrapped participant would read as absent and the constraint would
    silently stop being enforced instead of raising — the worst possible failure
    mode for a safety check."""
    stack = [IsolatedMiddleware(_Inner(), "bad_ext:install", lambda d: None), _Outer()]
    with pytest.raises(RuntimeError, match="outer must wrap inner"):
        assert_ordering(stack, {}, _CONSTRAINTS)


def test_core_constraints_are_declared():
    from deerflow.agents.middlewares.tool_error_handling_middleware import ToolErrorHandlingMiddleware
    from deerflow.agents.middlewares.tool_progress_middleware import ToolProgressMiddleware
    from deerflow.extensions.ordering import CORE_ORDERING_CONSTRAINTS

    pairs = {(c.outer, c.inner) for c in CORE_ORDERING_CONSTRAINTS}
    assert (ToolProgressMiddleware, ToolErrorHandlingMiddleware) in pairs
