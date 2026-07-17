"""Regression anchor: workspace snapshot text-cache cleanup must not block the event loop.

``capture_workspace_snapshot`` offloads the scan itself via ``asyncio.to_thread``
but owns a ``tempfile.mkdtemp`` text cache whose lifecycle runs on the async
path: the directory is created up front, removed on the scan-failure branch, and
removed again by ``record_workspace_changes``' ``finally`` after every run. Those
create/delete calls are blocking filesystem IO (``shutil.rmtree`` walks and
unlinks up to ``max_files`` cached texts). If any of them regresses back onto the
event loop, the strict Blockbuster gate raises ``BlockingError`` and these tests
fail.

Both cleanup branches are driven explicitly — the failure branch of
``capture_workspace_snapshot`` and the always-run ``finally`` of
``record_workspace_changes`` — because the happy path alone never reaches the
rmtree this anchor exists to guard.

Imports are kept at module top so any import-time IO runs at collection (outside
the gate); the surface under test runs on the event loop inside the gated test.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any

import pytest

from deerflow.workspace_changes import recorder
from deerflow.workspace_changes.types import WorkspaceSnapshot

pytestmark = pytest.mark.asyncio


class _RecordingEventStore:
    """Stand-in for the real event store: the external boundary, not the offload."""

    def __init__(self) -> None:
        self.puts: list[dict[str, Any]] = []

    async def put(self, **kwargs: Any) -> dict[str, Any]:
        self.puts.append(kwargs)
        return kwargs


def _seed_workspace(tmp_path: Path) -> None:
    """Create a real on-disk workspace so the scan has something to walk."""
    work = tmp_path / "work"
    work.mkdir(parents=True, exist_ok=True)
    (work / "note.txt").write_text("hello\n", encoding="utf-8")


async def test_capture_workspace_snapshot_cleanup_does_not_block_event_loop(tmp_path: Path, monkeypatch) -> None:
    """The scan-failure branch removes the text cache; that rmtree must be offloaded."""
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    import deerflow.config.paths as paths_mod

    monkeypatch.setattr(paths_mod, "_paths", None)

    # Pin mkdtemp's parent so the assertion below sees this test's cache dir and
    # nothing else (the platform temp root is shared and macOS is not /tmp).
    cache_root = tmp_path / "tmp"
    cache_root.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(cache_root))

    # Force the failure branch. This mocks the scan (a separate, already-offloaded
    # call), never the text-cache cleanup this anchor guards.
    def _boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("scan failed")

    monkeypatch.setattr(recorder, "scan_workspace_roots", _boom)

    with pytest.raises(RuntimeError, match="scan failed"):
        await recorder.capture_workspace_snapshot("t1", include_text=True)

    # The cache dir was really created, then really removed — cleanup still runs,
    # it merely moved off the loop.
    leftovers = await asyncio.to_thread(lambda: sorted(cache_root.glob("deerflow-workspace-changes-*")))
    assert leftovers == [], f"text cache dir leaked on the failure branch: {leftovers}"


async def test_record_workspace_changes_cleanup_does_not_block_event_loop(tmp_path: Path, monkeypatch) -> None:
    """``record_workspace_changes`` rmtrees the snapshot text cache in its ``finally``."""
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    import deerflow.config.paths as paths_mod

    monkeypatch.setattr(paths_mod, "_paths", None)

    _seed_workspace(tmp_path)

    # A real text cache dir holding real files, so rmtree does real filesystem work.
    cache_dir = tmp_path / "text-cache"
    cache_dir.mkdir()
    for i in range(5):
        (cache_dir / f"cached_{i}.txt").write_text("cached\n", encoding="utf-8")

    before = WorkspaceSnapshot(files={}, truncated=False, text_cache_dir=str(cache_dir))

    await recorder.record_workspace_changes(
        _RecordingEventStore(),
        "t1",
        "r1",
        before,
    )

    still_there = await asyncio.to_thread(cache_dir.exists)
    assert not still_there, "record_workspace_changes must remove the snapshot text cache"
