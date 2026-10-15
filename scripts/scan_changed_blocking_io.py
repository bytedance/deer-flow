#!/usr/bin/env python3
"""CLI wrapper for the changed-lines blocking IO scanner."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from _detector_cli import run_detector


def main(argv: Sequence[str] | None = None) -> int:
    return run_detector("support.detectors.blocking_io_changed", argv)


if __name__ == "__main__":
    sys.exit(main())
