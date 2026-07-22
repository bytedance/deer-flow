"""Regression: ``AioSandboxProvider.get()`` must not do blocking IO.

``ensure_sandbox_initialized_async`` (``sandbox/tools.py``) calls
``provider.get()`` directly on the LangGraph event loop for every sandbox tool
lookup. A prior change renewed the cross-process lease inside ``get()``
(``mkdir`` + temp-file write + ``fsync`` + ``os.replace``), which blocks the loop
— reported on PR #4221.

Under the strict Blockbuster context (this directory's conftest), any blocking IO
reached from ``deerflow.*`` while on the event loop raises ``BlockingError``.

The ownership store is injected here as a **blocking probe**: every store method
does real file IO. That keeps the anchor honest across backends — the configured
store may be in-memory (no IO to catch), but the redis store does network IO and a
future store could do anything, so what must be pinned is that ``get()`` performs
*no store call at all*, not merely that today's default store happens to be cheap.
If ownership work is put back on this path, this test fails.
"""

from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.asyncio


class _BlockingProbeStore:
    """Ownership store whose every operation does real blocking file IO."""

    supports_cross_process = True

    def __init__(self, probe_path: Path):
        self._probe_path = probe_path
        self._probe_path.write_text("owner", encoding="utf-8")

    @property
    def owner_id(self) -> str:
        return "worker-blockingio"

    def _blocking_touch(self) -> str:
        # Mirrors what a real store does on this call: sync IO the strict gate sees.
        return self._probe_path.read_text(encoding="utf-8")

    def take(self, sandbox_id: str) -> bool:
        self._blocking_touch()
        return True

    def claim(self, sandbox_id: str, *, for_destroy: bool = False) -> bool:
        self._blocking_touch()
        return True

    def renew(self, sandbox_id: str):
        from deerflow.community.aio_sandbox.ownership import RenewOutcome

        self._blocking_touch()
        return RenewOutcome.RENEWED

    def release(self, sandbox_id: str) -> None:
        self._blocking_touch()

    def owner(self, sandbox_id: str) -> str | None:
        return self._blocking_touch()

    def close(self) -> None:
        pass


def _make_provider(tmp_path: Path):
    """Build an ``AioSandboxProvider`` without ``__init__`` (no Docker, no threads)."""
    from deerflow.community.aio_sandbox.aio_sandbox_provider import AioSandboxProvider
    from deerflow.config.sandbox_config import SandboxOwnershipConfig

    provider = AioSandboxProvider.__new__(AioSandboxProvider)
    provider._lock = threading.Lock()
    provider._sandboxes = {}
    provider._sandbox_infos = {}
    provider._thread_sandboxes = {}
    provider._thread_locks = {}
    provider._last_activity = {}
    provider._warm_pool = {}
    provider._local_teardown = set()
    provider._acquire_epoch = {}
    provider._acquire_epoch_counter = 0
    provider._acquire_inflight = {}
    provider._shutdown_called = False
    provider._idle_checker_stop = threading.Event()
    provider._idle_checker_thread = None
    provider._renewal_stop = threading.Event()
    provider._renewal_thread = None
    provider._config = {"idle_timeout": 600, "replicas": 3}
    provider._backend = MagicMock()
    provider._owner_id = "worker-blockingio"
    provider._ownership_config = SandboxOwnershipConfig()
    provider._ownership = _BlockingProbeStore(tmp_path / "ownership-probe")
    return provider


async def test_get_does_no_blocking_io_on_event_loop(tmp_path):
    provider = _make_provider(tmp_path)
    provider._sandboxes["sb-blockingio"] = MagicMock()

    # If get() touches the ownership store, the probe's file read trips the gate.
    assert provider.get("sb-blockingio") is not None


async def test_blocking_probe_store_actually_trips_the_gate(tmp_path):
    """Meta-check: prove the probe has teeth, so the test above is not vacuous.

    Without this, a store that silently stopped doing IO would make the anchor
    pass for the wrong reason.
    """
    from blockbuster import BlockingError

    provider = _make_provider(tmp_path)

    with pytest.raises(BlockingError):
        provider._publish_ownership("sb-blockingio")


async def test_async_acquire_offloads_ownership_publish(tmp_path, monkeypatch):
    """The async acquire paths must offload registration, not just discovery.

    ``_register_discovered_sandbox`` / ``_register_created_sandbox`` publish
    ownership, which is blocking store IO. Every other blocking step in
    ``_discover_or_create_with_lock_async`` is wrapped in ``asyncio.to_thread``;
    these two were called directly, putting a Redis round trip on the event loop
    for every discover/create.
    """
    import deerflow.community.aio_sandbox.aio_sandbox_provider as aio_mod
    from deerflow.community.aio_sandbox.sandbox_info import SandboxInfo

    provider = _make_provider(tmp_path)
    info = SandboxInfo(
        sandbox_id="sb-async",
        sandbox_url="http://localhost:8080",
        container_name="deer-flow-sandbox-sb-async",
        created_at=1.0,
    )
    provider._backend.discover = MagicMock(return_value=info)

    # Stub the path layer: `get_paths()` resolves the base dir via os.getcwd on
    # the event loop, which is a pre-existing blocking call in this coroutine and
    # not what this anchor is about. Scoping it out keeps the test pinned to the
    # ownership publish this diff added.
    fake_paths = MagicMock()
    fake_paths.thread_dir.return_value = tmp_path
    monkeypatch.setattr(aio_mod, "get_paths", lambda: fake_paths)

    sandbox_id = await provider._discover_or_create_with_lock_async("t-async", "sb-async", user_id="u1")

    assert sandbox_id == "sb-async"
