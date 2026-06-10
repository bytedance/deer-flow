"""Worker-side best-effort and TTL-keeper helper tests (problems L/N).

``_run_stream_ttl_keeper`` periodically refreshes a run's stream TTL so a
long-idle run does not lose its retained stream.  ``_safe_cleanup_bridge``
swallows cleanup failures so the worker's finally path never raises.
"""

from __future__ import annotations

import asyncio

import pytest

from deerflow.runtime.runs.worker import _run_stream_ttl_keeper, _safe_cleanup_bridge

RUN_ID = "11111111-2222-3333-4444-555555555555"


class _RecordingBridge:
    def __init__(self, *, cleanup_raises: bool = False):
        self.refresh_calls: list[str] = []
        self.cleanup_calls: list[tuple[str, float]] = []
        self._cleanup_raises = cleanup_raises

    async def refresh_ttl(self, run_id: str) -> None:
        self.refresh_calls.append(run_id)

    async def cleanup(self, run_id: str, *, delay: float = 0) -> None:
        if self._cleanup_raises:
            raise RuntimeError("cleanup failed")
        self.cleanup_calls.append((run_id, delay))


@pytest.mark.anyio
async def test_ttl_keeper_refreshes_periodically(monkeypatch):
    bridge = _RecordingBridge()
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        # Stop after a few iterations by cancelling the keeper.
        if len(sleeps) >= 3:
            raise asyncio.CancelledError

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        # ttl=86400 -> refresh_every clamps to 300 (max bound).
        await _run_stream_ttl_keeper(bridge, RUN_ID, 86400)

    assert sleeps == [300, 300, 300]
    assert bridge.refresh_calls == [RUN_ID, RUN_ID]  # one per completed sleep


@pytest.mark.anyio
async def test_ttl_keeper_refresh_every_lower_bound(monkeypatch):
    """A small ttl clamps the refresh interval to the 30s floor."""
    bridge = _RecordingBridge()
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        raise asyncio.CancelledError

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await _run_stream_ttl_keeper(bridge, RUN_ID, 60)  # 60 // 4 = 15 -> floor 30

    assert sleeps == [30]


@pytest.mark.anyio
async def test_ttl_keeper_propagates_cancellation():
    bridge = _RecordingBridge()
    task = asyncio.create_task(_run_stream_ttl_keeper(bridge, RUN_ID, 86400))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.anyio
async def test_safe_cleanup_swallows_errors():
    bridge = _RecordingBridge(cleanup_raises=True)
    # Must not raise.
    await _safe_cleanup_bridge(bridge, RUN_ID, delay=60)


@pytest.mark.anyio
async def test_safe_cleanup_forwards_delay():
    bridge = _RecordingBridge()
    await _safe_cleanup_bridge(bridge, RUN_ID, delay=60)
    assert bridge.cleanup_calls == [(RUN_ID, 60)]
