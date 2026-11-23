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
import threading
from pathlib import Path

import pytest
from blockbuster import BlockingError
from test_opensandbox_provider import _FakeRemote, _FakeSandboxClass, _install

from deerflow.config.paths import Paths
from deerflow.skills.projection import SkillProjectionPaths

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


async def test_agent_skill_upload_is_off_loop_and_drains_before_cancellation(tmp_path, monkeypatch):
    provider, sdk = _install(monkeypatch)
    paths = await asyncio.to_thread(Paths, base_dir=tmp_path)
    monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: paths)
    root = paths.thread_skills_view_dir("thread-anchor", user_id="u-anchor")
    projection = SkillProjectionPaths(root / "public", root / "custom", root / "legacy", root / "integrations")

    def prepare():
        for path in (projection.public, projection.custom, projection.legacy, projection.integrations):
            path.mkdir(parents=True)
        (projection.public / "SKILL.md").write_bytes(b"example")

    await asyncio.to_thread(prepare)
    sandbox_id = await provider.acquire_async("thread-anchor", user_id="u-anchor")
    remote = sdk.remotes[0]
    loop = asyncio.get_running_loop()
    started = asyncio.Event()
    proceed = threading.Event()
    owner = threading.get_ident()
    calls = []

    def write(path, data, *, mode):
        calls.append(threading.get_ident())
        loop.call_soon_threadsafe(started.set)
        if not proceed.wait(timeout=5):
            raise TimeoutError("upload test did not open its gate")
        (tmp_path / "uploaded").write_bytes(data)

    monkeypatch.setattr(remote.files, "write_file", write)
    upload = asyncio.create_task(provider.sync_agent_skills_async(sandbox_id, thread_id="thread-anchor", user_id="u-anchor", projection=projection))
    entered = asyncio.create_task(started.wait())
    try:
        await asyncio.wait({upload, entered}, timeout=5, return_when=asyncio.FIRST_COMPLETED)
        if upload.done():
            upload.result()
        assert started.is_set(), "upload did not start"
        upload.cancel()
        await asyncio.sleep(0)
        assert not upload.done()
    finally:
        proceed.set()
        entered.cancel()
        result, _ = await asyncio.gather(upload, entered, return_exceptions=True)
        await asyncio.to_thread(provider.shutdown)
    assert isinstance(result, asyncio.CancelledError)
    assert calls and owner not in calls
    assert (tmp_path / "uploaded").read_bytes() == b"example"
