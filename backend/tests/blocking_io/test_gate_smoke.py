"""Smoke test: the strict Blockbuster gate is wired up and actively catching.

Independent of any specific production code path, asserts that calling a
known blocking IO function directly from an `async def` (without an
`asyncio.to_thread` wrapper) raises `BlockingError`. If this test ever
stops raising, the gate machinery itself is broken — typical causes are
`scanned_modules` misconfiguration, accidental removal of the Blockbuster
dev dependency, or the conftest hookwrapper no longer firing.

This is the meta-test that protects every other test in this directory
from silent regressions (a green gate that no longer catches anything is
worse than no gate at all).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from blockbuster import BlockingError
from support.detectors.blocking_io_runtime import detect_blocking_io_strict

pytestmark = pytest.mark.asyncio


async def test_gate_catches_unoffloaded_blocking_io_in_deerflow_module(tmp_path: Path) -> None:
    from deerflow.runtime.store._sqlite_utils import ensure_sqlite_parent_dir

    db_file = tmp_path / "subdir" / "store.db"

    with pytest.raises(BlockingError):
        ensure_sqlite_parent_dir(str(db_file))


async def test_gate_restores_blockbuster_patches_after_exceptions() -> None:
    original_stat = os.stat

    with pytest.raises(RuntimeError, match="boom"):
        with detect_blocking_io_strict():
            raise RuntimeError("boom")

    assert os.stat is original_stat


@pytest.mark.allow_blocking_io
async def test_allow_blocking_io_marker_opts_out_of_gate(tmp_path: Path) -> None:
    """Verify the @pytest.mark.allow_blocking_io opt-out actually disables the gate."""
    from deerflow.runtime.store._sqlite_utils import ensure_sqlite_parent_dir

    db_file = tmp_path / "subdir" / "store.db"

    ensure_sqlite_parent_dir(str(db_file))

    assert db_file.parent.exists()
