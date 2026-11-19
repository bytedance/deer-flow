"""Fixtures for the DeerFlow Monocle behavioural tests.

Only fixtures live here. Paths and ``run_deerflow`` are in ``_helpers.py`` so
nothing imports ``conftest`` as a module. The ``sys.path`` insert (mirroring the
backend root ``conftest.py``) makes ``_helpers`` importable under any pytest
import mode. The ``.env`` load is scoped to the live fixture, so collecting or
running the offline test never reads secrets.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))


@pytest.fixture
def run_agent() -> Callable[[str], str]:
    """Live agent runner. Explicit opt-in, so a default run can never go live.

    Skips unless ``MONOCLE_LIVE_TESTS=1`` is set, when the DeerFlow app is not
    importable (e.g. a test-tools-only venv), or when ``config.yaml`` is absent.
    Provider credentials are validated by the configured model itself —
    ``config.yaml`` may select any provider, not just OpenAI, so there is no
    hard-coded key check here.
    """
    from _helpers import CONFIG_PATH, REPO_ROOT, live_tests_enabled, run_deerflow

    if not live_tests_enabled():
        pytest.skip("live tests are opt-in: set MONOCLE_LIVE_TESTS=1")
    pytest.importorskip("deerflow", reason="DeerFlow app not importable in this venv")

    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
    if not CONFIG_PATH.exists():
        pytest.skip(f"config.yaml not found at {CONFIG_PATH}")
    return run_deerflow
