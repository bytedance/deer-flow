"""Pytest conftest for the strict Blockbuster runtime gate.

Activates `detect_blocking_io_strict()` around the entire pytest item
protocol (setup + call + teardown) so blocking IO in async fixtures and
lifespan code is also caught, not just blocking IO inside the test body.

Scope: only applies to items whose path is under `backend/tests/blocking_io/`.
Pytest registers conftest hookwrappers globally once the file is loaded,
so an explicit path filter is required to keep the strict gate from
firing on unrelated tests when the full suite is collected.

Opt-out: mark a test with `@pytest.mark.allow_blocking_io` to skip the gate.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from support.detectors.blocking_io_runtime import detect_blocking_io_strict

_BLOCKING_IO_TEST_ROOT = Path(__file__).resolve().parent


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item: pytest.Item, nextitem: pytest.Item | None) -> Generator[None, None, None]:
    if not _is_blocking_io_item(item) or item.get_closest_marker("allow_blocking_io") is not None:
        yield
        return

    with detect_blocking_io_strict():
        yield


def _is_blocking_io_item(item: pytest.Item) -> bool:
    return Path(item.path).resolve().is_relative_to(_BLOCKING_IO_TEST_ROOT)
