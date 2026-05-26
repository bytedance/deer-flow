"""Pytest conftest for the strict Blockbuster runtime gate.

Activates `detect_blocking_io_strict()` around the entire pytest item
protocol (setup + call + teardown) so blocking IO in async fixtures and
lifespan code is also caught, not just blocking IO inside the test body.

Scope: only applies to tests collected under `backend/tests/blocking_io/`
because pytest hookwrappers in a subdirectory conftest fire only for items
under that subdirectory.

Opt-out: mark a test with `@pytest.mark.allow_blocking_io` to skip the gate.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from support.detectors.blocking_io_runtime import detect_blocking_io_strict


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item: pytest.Item, nextitem: pytest.Item | None) -> Generator[None, None, None]:
    if item.get_closest_marker("allow_blocking_io") is not None:
        yield
        return

    with detect_blocking_io_strict():
        yield
