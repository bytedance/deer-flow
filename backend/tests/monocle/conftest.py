"""Fixtures for the DeerFlow Monocle behavioural tests.

Only fixtures live here. Paths and ``run_deerflow`` are in ``_helpers.py`` so
nothing imports ``conftest`` as a module. The ``sys.path`` insert (mirroring the
backend root ``conftest.py``) makes ``_helpers`` importable under any pytest
import mode. The ``.env`` load is scoped to the live fixture, so collecting or
running the offline test never reads secrets.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))


@pytest.fixture
def run_agent() -> Callable[[str], str]:
    """Live agent runner, skipping cleanly when the end-to-end path can't run.

    Skips when the DeerFlow app is not importable (e.g. a test-tools-only venv),
    when ``OPENAI_API_KEY`` is unset, or when ``config.yaml`` is absent.
    """
    pytest.importorskip("deerflow", reason="DeerFlow app not importable in this venv")

    from _helpers import CONFIG_PATH, REPO_ROOT, run_deerflow
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set")
    if not CONFIG_PATH.exists():
        pytest.skip(f"config.yaml not found at {CONFIG_PATH}")
    return run_deerflow
