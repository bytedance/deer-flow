"""Shared bootstrap for the detector CLI shims in this directory.

The detectors live under `backend/tests/support/detectors/` so they can be
exercised by the test suite; the shims here only put that package on
`sys.path` and delegate. Keeping the path computation in one place means a
layout change breaks loudly in exactly one file instead of silently drifting
across copies.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Sequence
from pathlib import Path

TEST_SUPPORT_PATH = Path(__file__).resolve().parents[1] / "backend" / "tests"


def run_detector(module_name: str, argv: Sequence[str] | None = None) -> int:
    """Import a `support.detectors.*` module and run its `main(argv)`."""
    if not TEST_SUPPORT_PATH.is_dir():
        raise RuntimeError(f"detector support path not found: {TEST_SUPPORT_PATH}; the scripts/ directory has moved relative to backend/tests")
    if str(TEST_SUPPORT_PATH) not in sys.path:
        sys.path.insert(0, str(TEST_SUPPORT_PATH))
    module = importlib.import_module(module_name)
    return module.main(argv)
