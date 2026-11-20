"""Anchor: contended OpenSandbox acquire_async must not block the event loop.

Two concurrent acquire_async calls for the same scope serialize on the
AcquireSerializer; the loser's wait and both callers' creation path must stay
off the loop. The fake SDK boundary below performs REAL file IO inside
create(), so any regression that moves creation back onto the loop trips the
Blockbuster gate (FILE_IO rules give this anchor teeth).

Blockbuster's default rule set is blind to ``threading.Lock.acquire`` (verified
empirically under ``detect_blocking_io_strict``), so the serializer lock wait
itself cannot be pinned this way — the lock-wait placement is covered by Task
7's ExplodingExecutor contract test. What this anchor pins instead is the
provider creation path: under contention, no blocking IO may run on the loop.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from blockbuster import BlockingError
from test_opensandbox_provider import _FakeRemote, _FakeSandboxClass, _install

pytestmark = pytest.mark.asyncio


class _FileIOProbingSandboxClass(_FakeSandboxClass):
    """Fake SDK whose create() performs real blocking file IO at the boundary."""

    def __init__(self, probe_dir: Path) -> None:
        super().__init__()
        self._probe_dir = probe_dir

    def create(self, image: str, **kwargs) -> _FakeRemote:
        probe = self._probe_dir / f"create-{len(self.create_calls) + 1}.probe"
        probe.write_text("x" * 4096)  # real blocking file IO at the SDK boundary
        return super().create(image, **kwargs)


async def test_concurrent_acquire_async_stays_off_event_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    provider, _fake_sdk = _install(monkeypatch, sdk=_FileIOProbingSandboxClass(tmp_path))
    first, second = await asyncio.gather(
        provider.acquire_async("thread-anchor", user_id="u-anchor"),
        provider.acquire_async("thread-anchor", user_id="u-anchor"),
    )
    assert first == second  # same scope serialized, second caller reuses
    provider.shutdown()


async def test_sync_acquire_on_loop_trips_the_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Meta-check (teeth): a synchronous acquire on the loop MUST be caught."""
    provider, _fake_sdk = _install(monkeypatch, sdk=_FileIOProbingSandboxClass(tmp_path))
    with pytest.raises(BlockingError):
        provider.acquire("thread-anchor", user_id="u-anchor")
    provider.shutdown()
