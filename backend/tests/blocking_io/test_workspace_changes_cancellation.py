"""Cancellation regressions for workspace snapshot scans.

Text snapshots own a temporary cache that must outlive an already-running scan,
so cancellation deliberately drains that worker before cleanup. Metadata-only
snapshots own no such resource and must propagate cancellation promptly while
still consuming/logging the worker's eventual outcome.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
import threading
from pathlib import Path
from typing import Any

import pytest

from deerflow.workspace_changes import recorder
from deerflow.workspace_changes.types import WorkspaceSnapshot

pytestmark = pytest.mark.asyncio


async def _reset_paths(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    import deerflow.config.paths as paths_mod

    monkeypatch.setattr(paths_mod, "_paths", None)


async def test_metadata_only_cancel_does_not_wait_for_scan_worker(tmp_path: Path, monkeypatch, caplog) -> None:
    """No text cache means cancellation must not wait for the worker scan."""
    await _reset_paths(tmp_path, monkeypatch)

    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def _blocking_scan(
        *_args: Any,
        text_cache_dir: str | Path | None = None,
        **_kwargs: Any,
    ) -> WorkspaceSnapshot:
        assert text_cache_dir is None
        entered.set()
        release.wait(timeout=5)
        finished.set()
        raise RuntimeError("late metadata scan failure")

    monkeypatch.setattr(recorder, "scan_workspace_roots", _blocking_scan)
    caplog.set_level(logging.INFO, logger=recorder.__name__)

    task = asyncio.create_task(recorder.capture_workspace_snapshot("t1", include_text=False))
    assert await asyncio.to_thread(entered.wait, 5), "metadata scan worker did not start"

    try:
        task.cancel()
        for _ in range(5):
            await asyncio.sleep(0)
        assert task.done(), "metadata-only cancellation waited for a scan with no cache resource to protect"
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()

    assert await asyncio.to_thread(finished.wait, 5), "metadata scan worker did not finish after release"
    for _ in range(100):
        if any("Workspace scan failed after snapshot cancellation" in record.getMessage() for record in caplog.records):
            break
        await asyncio.sleep(0.01)

    assert any("Workspace scan failed after snapshot cancellation" in record.getMessage() for record in caplog.records), "the detached metadata scan's late failure must be consumed and logged"


async def test_text_scan_cancel_logs_drain_and_late_failure(tmp_path: Path, monkeypatch, caplog) -> None:
    """A text-cache scan still drains, and that cancellation latency is observable."""
    await _reset_paths(tmp_path, monkeypatch)

    cache_root = tmp_path / "tmp"
    cache_root.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(cache_root))

    entered = threading.Event()
    release = threading.Event()

    def _blocking_scan(
        *_args: Any,
        text_cache_dir: str | Path | None = None,
        **_kwargs: Any,
    ) -> WorkspaceSnapshot:
        assert text_cache_dir is not None
        cache_dir = Path(text_cache_dir)
        assert cache_dir.exists()
        entered.set()
        release.wait(timeout=5)
        assert cache_dir.exists(), "text cache was removed while the scan worker was still running"
        raise RuntimeError("late text scan failure")

    monkeypatch.setattr(recorder, "scan_workspace_roots", _blocking_scan)
    caplog.set_level(logging.INFO, logger=recorder.__name__)

    task = asyncio.create_task(recorder.capture_workspace_snapshot("t1", include_text=True))
    assert await asyncio.to_thread(entered.wait, 5), "text scan worker did not start"

    task.cancel()
    for _ in range(5):
        await asyncio.sleep(0)

    assert not task.done(), "text-cache cancellation must keep ownership until the scan drains"
    assert any("Waiting for cancelled workspace snapshot scan to finish before text-cache cleanup" in record.getMessage() for record in caplog.records), "entering the cancellation drain should be observable"

    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    leftovers = await asyncio.to_thread(lambda: sorted(cache_root.glob("deerflow-workspace-changes-*")))
    assert leftovers == [], f"cancelled text scan leaked a cache dir: {leftovers}"
    assert any("Workspace scan failed after snapshot cancellation" in record.getMessage() for record in caplog.records), "a scan failure during cancellation drain must retain diagnostics"
