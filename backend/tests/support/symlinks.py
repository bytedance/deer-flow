"""Symlink-planting helper shared by suites that exercise symlink confinement.

Windows only grants symlink creation with Developer Mode enabled or an
elevated process, so a plain ``symlink_to`` raises ``OSError: [WinError
1314]`` on a stock Windows contributor machine. Suites that need real
symlinks skip exactly at the creation point instead of erroring, while hosts
with the privilege (CI, Linux, Developer Mode) run the full assertion.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def symlink_or_skip(link: Path, target: Path, *, target_is_directory: bool = False) -> None:
    """Create ``link`` -> ``target``, skipping the test when the host cannot."""
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
    except OSError:
        pytest.skip("symlink creation is unavailable on this host (on Windows it requires Developer Mode or elevation)")
