#!/usr/bin/env python3
"""CLI wrapper for the changed-lines blocking IO scanner."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_SUPPORT_PATH = REPO_ROOT / "backend" / "tests"
if str(TEST_SUPPORT_PATH) not in sys.path:
    sys.path.insert(0, str(TEST_SUPPORT_PATH))


def main(argv: Sequence[str] | None = None) -> int:
    from support.detectors.blocking_io_changed import main as scanner_main

    return scanner_main(argv)


if __name__ == "__main__":
    sys.exit(main())
