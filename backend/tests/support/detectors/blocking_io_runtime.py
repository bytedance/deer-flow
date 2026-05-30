"""Strict Blockbuster runtime context scoped to DeerFlow business code.

Creates a `BlockBuster` instance with `scanned_modules=("app", "deerflow")`
so that test infrastructure (pytest, langchain, importlib, third-party libs)
is out of scope and does not produce false positives. Only loop-blocking
sync IO whose caller stack passes through `app.*` or `deerflow.*` raises
`BlockingError`.

Used by `backend/tests/blocking_io/conftest.py` to gate the regression suite.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from blockbuster import BlockBuster, BlockBusterFunction, BlockingError

_SCANNED_MODULES: tuple[str, ...] = ("app", "deerflow")

# Add DeerFlow-local rules here only when Blockbuster's default rule set misses
# a generic blocking primitive used by production code. If a path is invisible
# because no test exercises it, add a production-path runtime anchor instead.
_PROJECT_BLOCKING_RULES: tuple[tuple[str, BlockBusterFunction], ...] = ()


def _install_project_rules(bb: BlockBuster) -> None:
    for name, rule in _PROJECT_BLOCKING_RULES:
        bb.functions[name] = rule


@contextmanager
def detect_blocking_io_strict() -> Iterator[BlockBuster]:
    """Activate Blockbuster scoped to app.* and deerflow.* callers only."""
    bb = BlockBuster(scanned_modules=list(_SCANNED_MODULES))
    _install_project_rules(bb)
    try:
        bb.activate()
        yield bb
    finally:
        bb.deactivate()


__all__ = ["BlockingError", "detect_blocking_io_strict"]
