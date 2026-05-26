"""Strict Blockbuster runtime context scoped to DeerFlow business code.

Wraps `blockbuster.blockbuster_ctx` with `scanned_modules=("app", "deerflow")`
so that test infrastructure (pytest, langchain, importlib, third-party libs)
is out of scope and does not produce false positives. Only loop-blocking
sync IO whose caller stack passes through `app.*` or `deerflow.*` raises
`BlockingError`.

Used by `backend/tests/blocking_io/conftest.py` to gate the regression suite.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from blockbuster import BlockBuster, BlockingError, blockbuster_ctx

_SCANNED_MODULES: tuple[str, ...] = ("app", "deerflow")


@contextmanager
def detect_blocking_io_strict() -> Iterator[BlockBuster]:
    """Activate Blockbuster scoped to app.* and deerflow.* callers only."""
    with blockbuster_ctx(scanned_modules=list(_SCANNED_MODULES)) as bb:
        yield bb


__all__ = ["BlockingError", "detect_blocking_io_strict"]
