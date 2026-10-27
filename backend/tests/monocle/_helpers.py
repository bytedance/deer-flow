"""Helpers for the DeerFlow Monocle behavioural tests.

Kept out of ``conftest.py`` so nothing imports ``conftest`` as a module.
Monocle instrumentation is owned by the Test Tools validator (installed by the
``monocle_trace_asserter`` fixture), so ``run_deerflow`` only drives the agent;
the already-installed instrumentation captures the run's spans.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
TRACES = HERE / "traces"
REPO_ROOT = HERE.parents[2]  # backend/tests/monocle -> backend/tests -> backend -> repo root
CONFIG_PATH = REPO_ROOT / "config.yaml"

_TRUTHY = {"1", "true", "yes", "on"}


def live_tests_enabled() -> bool:
    """Whether the live tests are explicitly opted into via ``MONOCLE_LIVE_TESTS``.

    Off by default so the plain ``pytest backend/tests/monocle/`` run can never
    spend model tokens, hit the network, or write to a sandbox — even on a fully
    configured checkout where credentials and ``config.yaml`` are present.
    """
    return os.getenv("MONOCLE_LIVE_TESTS", "").strip().lower() in _TRUTHY


def run_deerflow(message: str) -> str:
    """Run the DeerFlow agent once and return its response text.

    The model is resolved from ``config.yaml`` (no hardcoded override) so the
    live test exercises DeerFlow's own model-resolution path.
    """
    from deerflow.client import DeerFlowClient

    client = DeerFlowClient(config_path=str(CONFIG_PATH))
    return client.chat(message, thread_id=f"monocle-test-{uuid.uuid4().hex[:8]}")
