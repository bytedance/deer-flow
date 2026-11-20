"""Batch checklist IO runs off-loop and drains before its sandbox holder closes."""

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deerflow.config.paths import Paths
from deerflow.subagents import batch_acceptance
from deerflow.subagents.acceptance_checks import check_acceptance_criteria

pytestmark = pytest.mark.asyncio


async def _setup(monkeypatch, tmp_path):
    paths = await asyncio.to_thread(Paths, str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", paths)
    probe = tmp_path / "probe.txt"
    probe.write_text("actual output")
    lease = SimpleNamespace(sandbox_id="local", owner_id="check-lease", release=AsyncMock())
    monkeypatch.setattr("deerflow.sandbox.sandbox_provider.get_sandbox_provider", lambda: object())
    monkeypatch.setattr("deerflow.sandbox.lease.acquire_sandbox_client_lease", AsyncMock(return_value=lease))
    return probe, lease


def _check(reader):
    def check(criteria, **kwargs):
        return check_acceptance_criteria(criteria, **kwargs, size_prober=lambda *args: 10, content_reader=reader)

    return check


def _kwargs():
    return dict(batch={"thread_id": "t", "user_id": "u", "execution_spec": {}}, app_config=SimpleNamespace(), bash_executions=None)


async def test_real_blocking_file_read_is_offloaded(monkeypatch, tmp_path):
    probe, lease = await _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(batch_acceptance, "check_acceptance_criteria", _check(lambda *args: probe.read_text()))
    verdict = await batch_acceptance.check_batch_acceptance(["file:../outputs/report.md exists"], **_kwargs())
    assert verdict["leaves"][0]["checked"] is True
    assert verdict["leaves"][0]["holds"] is True
    lease.release.assert_awaited_once()


async def test_same_blocking_reader_trips_the_gate_on_loop(monkeypatch, tmp_path):
    from blockbuster import BlockingError

    probe, _ = await _setup(monkeypatch, tmp_path)
    with pytest.raises(BlockingError):
        check_acceptance_criteria(
            ["file:../outputs/report.md exists"], thread_data={"workspace_path": str(tmp_path / "workspace"), "outputs_path": str(tmp_path / "outputs")}, size_prober=lambda *args: 10, content_reader=lambda *args: probe.read_text()
        )


async def test_repeated_cancellation_drains_read_before_releasing_lease(monkeypatch, tmp_path):
    probe, lease = await _setup(monkeypatch, tmp_path)
    started = asyncio.Event()
    unblock = threading.Event()
    loop = asyncio.get_running_loop()

    def reader(*args):
        loop.call_soon_threadsafe(started.set)
        assert unblock.wait(timeout=5)
        return probe.read_text()

    monkeypatch.setattr(batch_acceptance, "check_acceptance_criteria", _check(reader))
    task = asyncio.create_task(batch_acceptance.check_batch_acceptance(["file:../outputs/report.md exists"], **_kwargs()))
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        lease.release.assert_not_awaited()
    finally:
        unblock.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    lease.release.assert_awaited_once()
