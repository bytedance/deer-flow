#!/usr/bin/env python3
"""CLI wrapper for the async/thread boundary detector."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from _detector_cli import run_detector


def main(argv: Sequence[str] | None = None) -> int:
    return run_detector("support.detectors.thread_boundaries", argv)


if __name__ == "__main__":
    sys.exit(main())
