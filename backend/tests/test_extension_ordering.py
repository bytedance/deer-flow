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


def test_every_duplicate_participant_must_satisfy_the_constraint():
    """A valid first pair must not hide a later contributed violation."""
    stack = [_Outer(), _Inner(), _Outer()]

    with pytest.raises(RuntimeError) as exc_info:
        assert_ordering(stack, {2: "late:install"}, _CONSTRAINTS)

    assert "late:install" in str(exc_info.value)


def test_core_constraints_are_declared():
    from deerflow.agents.middlewares.tool_error_handling_middleware import ToolErrorHandlingMiddleware
    from deerflow.agents.middlewares.tool_progress_middleware import ToolProgressMiddleware
    from deerflow.extensions.ordering import core_ordering_constraints

    pairs = {(c.outer, c.inner) for c in core_ordering_constraints()}
    assert (ToolProgressMiddleware, ToolErrorHandlingMiddleware) in pairs


def test_core_constraints_are_a_plain_tuple():
    """Deferred resolution must not be paid for with an object that reports one
    thing when iterated and another when measured.

    The predecessor was a ``tuple`` subclass whose backing storage stayed empty
    (a tuple cannot fill its own storage after construction), so ``len`` was 0,
    ``bool`` was False, ``in`` was always False and it compared unequal to the
    very tuples tests substitute for it — while iteration yielded the real
    constraints.
    """
    from deerflow.extensions.ordering import core_ordering_constraints

    constraints = core_ordering_constraints()
    iterated = list(constraints)

    assert type(constraints) is tuple
    assert len(constraints) == len(iterated)
    assert bool(constraints) is bool(iterated)
    assert constraints == tuple(iterated)
    assert all(constraint in constraints for constraint in iterated)
    assert constraints[0] is iterated[0]
    assert list(reversed(constraints)) == list(reversed(iterated))


def test_resolution_stays_deferred_until_first_use():
    """Importing this module must not drag in the middleware layer.

    ``extensions/`` is the layer the middleware layer calls into, so resolving
    the table at import time would give it a backward dependency on the layer
    it exists to serve — an import cycle waiting for the first middleware that
    imports anything under ``extensions/`` at module level. Resolution belongs
    at ``assert_ordering`` time, which already runs inside the middleware
    builder.
    """
    import os
    import subprocess
    import sys
    from pathlib import Path

    backend_root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(backend_root), str(backend_root / "packages" / "harness"), os.environ.get("PYTHONPATH", "")])}
    probe = (
        "import sys\n"
        "from deerflow.extensions import ordering\n"
        "targets = ('deerflow.agents.middlewares.tool_progress_middleware', 'deerflow.agents.middlewares.tool_error_handling_middleware')\n"
        "print('after_import', [t for t in targets if t in sys.modules])\n"
        "ordering.core_ordering_constraints()\n"
        "print('after_call', sorted(t for t in targets if t in sys.modules))\n"
    )
    result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, env=env)

    assert result.returncode == 0, result.stderr
    assert "after_import []" in result.stdout, "importing extensions.ordering must not load the middleware layer"
    assert "after_call ['deerflow.agents.middlewares.tool_error_handling_middleware', 'deerflow.agents.middlewares.tool_progress_middleware']" in result.stdout
