#!/usr/bin/env python3
"""CLI wrapper for the async/thread boundary detector."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_SUPPORT_PATH = REPO_ROOT / "backend" / "tests"
if str(TEST_SUPPORT_PATH) not in sys.path:
    sys.path.insert(0, str(TEST_SUPPORT_PATH))


def main(argv: Sequence[str] | None = None) -> int:
    from support.detectors.thread_boundaries import main as detector_main

    return detector_main(argv)


if __name__ == "__main__":
    sys.exit(main())
