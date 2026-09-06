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

Because ``mkdtemp`` must be offloaded, its worker handoff is also a cancellation
hazard: a run cancelled after ``mkdtemp`` but before the coroutine receives the
path would orphan the dir. The last test pins the shield+reclaim guard that
removes such a dir instead of leaking it.

Imports are kept at module top so any import-time IO runs at collection (outside
the gate); the surface under test runs on the event loop inside the gated test.
"""

from __future__ import annotations

import asyncio
import tempfile
import threading
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


async def test_capture_workspace_snapshot_cancelled_handoff_leaks_no_text_cache(tmp_path: Path, monkeypatch) -> None:
    """A run cancelled during the mkdtemp handoff must not orphan the text cache.

    ``mkdtemp`` runs in the ``_prepare_capture`` worker, so if the run is
    cancelled after the dir is created but before the coroutine receives the
    path, nothing downstream owns it. The shield+reclaim guard waits for the
    worker and removes the dir; without it the dir leaks into the temp root.
    """
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    import deerflow.config.paths as paths_mod

    monkeypatch.setattr(paths_mod, "_paths", None)

    cache_root = tmp_path / "tmp"
    cache_root.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(cache_root))

    entered = threading.Event()
    release = threading.Event()
    real_mkdtemp = tempfile.mkdtemp

    def _blocking_mkdtemp(*args: Any, **kwargs: Any) -> str:
        created = real_mkdtemp(*args, **kwargs)  # the dir really exists now
        entered.set()
        release.wait(timeout=5)  # park the worker mid-handoff, holding the result
        return created

    monkeypatch.setattr(recorder.tempfile, "mkdtemp", _blocking_mkdtemp)

    task = asyncio.ensure_future(recorder.capture_workspace_snapshot("t1", include_text=True))
    await asyncio.to_thread(entered.wait, 5)  # mkdtemp created the dir; worker is parked
    parked = await asyncio.to_thread(lambda: sorted(cache_root.glob("deerflow-workspace-changes-*")))
    assert parked, "text cache dir should exist while the worker is parked mid-handoff"

    task.cancel()
    release.set()  # let the worker finish and hand its result to the reclaim path
    with pytest.raises(asyncio.CancelledError):
        await task

    leftovers = await asyncio.to_thread(lambda: sorted(cache_root.glob("deerflow-workspace-changes-*")))
    assert leftovers == [], f"cancelled capture leaked a text cache dir: {leftovers}"


async def test_capture_workspace_snapshot_repeated_cancellation_leaks_no_text_cache(tmp_path: Path, monkeypatch) -> None:
    """A *second* cancellation during the reclaim await must not orphan the cache.

    After the first cancel enters the reclaim path, the coroutine awaits the
    shielded worker's result. A second cancel lands on that await: because the
    reclaim+remove is owned by a task the caller cannot abandon, the guard drains
    the repeated cancellation until the dir is removed, then restores the
    cancellation. A plain re-await would let the second ``CancelledError`` skip
    the reclaim (``except Exception`` does not catch it) while the shielded worker
    still finishes and leaks its dir.
    """
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    import deerflow.config.paths as paths_mod

    monkeypatch.setattr(paths_mod, "_paths", None)

    cache_root = tmp_path / "tmp"
    cache_root.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(cache_root))

    entered = threading.Event()
    release = threading.Event()
    real_mkdtemp = tempfile.mkdtemp

    def _blocking_mkdtemp(*args: Any, **kwargs: Any) -> str:
        created = real_mkdtemp(*args, **kwargs)  # the dir really exists now
        entered.set()
        release.wait(timeout=5)  # park the worker mid-handoff, holding the result
        return created

    monkeypatch.setattr(recorder.tempfile, "mkdtemp", _blocking_mkdtemp)

    task = asyncio.ensure_future(recorder.capture_workspace_snapshot("t1", include_text=True))
    await asyncio.to_thread(entered.wait, 5)  # mkdtemp created the dir; worker is parked
    parked = await asyncio.to_thread(lambda: sorted(cache_root.glob("deerflow-workspace-changes-*")))
    assert parked, "text cache dir should exist while the worker is parked mid-handoff"

    task.cancel()  # cancel #1 -> enters reclaim, awaits the shielded cleanup task
    for _ in range(5):
        await asyncio.sleep(0)  # let the reclaim path reach its await while the worker is still parked
    task.cancel()  # cancel #2 -> lands on the reclaim await
    for _ in range(5):
        await asyncio.sleep(0)

    release.set()  # worker finishes; the drained cleanup reclaims and removes the dir
    with pytest.raises(asyncio.CancelledError):
        await task

    leftovers = await asyncio.to_thread(lambda: sorted(cache_root.glob("deerflow-workspace-changes-*")))
    assert leftovers == [], f"repeated-cancel capture leaked a text cache dir: {leftovers}"
