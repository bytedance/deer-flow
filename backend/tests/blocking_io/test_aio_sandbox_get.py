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

import asyncio
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
    from deerflow.sandbox.acquire_serialization import AcquireSerializer

    provider = AioSandboxProvider.__new__(AioSandboxProvider)
    provider._lock = threading.Lock()
    provider._sandboxes = {}
    provider._sandbox_infos = {}
    provider._thread_sandboxes = {}
    provider._acquire_serializer = AcquireSerializer(thread_name_prefix="aio-sandbox-lock-wait")
    provider._last_activity = {}
    provider._warm_pool = {}
    provider._active_sandbox_identity = {}
    provider._warm_pool_identity = {}
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
    from deerflow.community.aio_sandbox.sandbox_info import SandboxInfo

    provider = _make_provider(tmp_path)
    info = SandboxInfo(
        sandbox_id="sb-async",
        sandbox_url="http://localhost:8080",
        container_name="deer-flow-sandbox-sb-async",
        created_at=1.0,
    )
    provider._backend.discover = MagicMock(return_value=info)

    # The lock path is resolved in a worker thread, so the real `Paths` object can
    # stay in place; DEER_FLOW_HOME keeps the thread directories and the lock file
    # inside the test's own tmp_path.
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)

    sandbox_id = await provider._discover_or_create_with_lock_async("t-async", "sb-async", user_id="u1")

    assert sandbox_id == "sb-async"


async def test_async_lock_path_resolution_stays_off_the_loop(tmp_path, monkeypatch) -> None:
    """The async acquire resolves its lock path from ``Paths.base_dir``, which syscalls.

    The sibling anchor used to stub the path layer out and documented why — "a
    pre-existing blocking call in this coroutine". The resolution now runs in a
    worker thread, so that stub is gone; this anchor keeps it from coming back.
    """
    import deerflow.community.aio_sandbox.aio_sandbox_provider as aio_mod

    provider = _make_provider(tmp_path)
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)

    class _ReachedLockFile(Exception):
        pass

    def _stop_at_lock_file(_lock_path):
        raise _ReachedLockFile

    monkeypatch.setattr(aio_mod, "_open_lock_file", _stop_at_lock_file)

    # Red before the fix: the gate raises BlockingError from the inline
    # ``paths.thread_dir(...)`` before the sentinel is ever reached.
    with pytest.raises(_ReachedLockFile):
        await provider._discover_or_create_with_lock_async("t-lock", "sb-lock", user_id="u1")


async def test_blocking_probe_thread_dir_actually_trips_the_gate(tmp_path, monkeypatch) -> None:
    """Meta-check: prove the gate still catches an inline ``thread_dir`` call.

    The anchor above only asserts execution reached the lock file, so if the gate
    went blind to the syscalls behind ``Path.resolve()`` the anchor would pass with
    the inline call restored. Calling ``thread_dir`` straight from the event loop
    pins that the same isolation is armed and blocking here.
    """
    from blockbuster import BlockingError

    from deerflow.config.paths import get_paths

    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)

    with pytest.raises(BlockingError):
        get_paths().thread_dir("aio-sandbox-lock-wait")


@pytest.mark.parametrize("skills_view", [False, True], ids=["default-id", "policy-scoped-id"])
async def test_async_acquire_derives_sandbox_id_off_the_loop(tmp_path, monkeypatch, skills_view) -> None:
    """Deriving the sandbox ID checks the thread's skills_view on disk.

    ``_sandbox_id_for_thread`` stats ``skills_view`` through ``Paths.base_dir``
    to pick the policy-scoped or the historic deterministic ID. Every layer
    around it in ``_acquire_internal_async`` already runs in a worker; the ID
    derivation ran inline and blocked the loop on each thread acquire.
    """
    from concurrent.futures import ThreadPoolExecutor

    from deerflow.config.paths import get_paths

    provider = _make_provider(tmp_path)
    provider._acquire_worker_executor = ThreadPoolExecutor(thread_name_prefix="aio-sandbox-owned-worker")
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    # Already offloaded with asyncio.to_thread; stubbed so the anchor does not
    # build a real skills projection.
    monkeypatch.setattr(provider, "_ensure_skills_projection", lambda user_id: None)
    if skills_view:
        await asyncio.to_thread(lambda: get_paths().thread_skills_view_dir("t-id", user_id="u1").mkdir(parents=True))
    expected_id = await asyncio.to_thread(provider._sandbox_id_for_thread, "t-id", "u1")

    reclaimed: list[str] = []

    class _ReachedWarmPool(Exception):
        pass

    def _stop_at_warm_pool(thread_id, sandbox_id, *, user_id=None):
        reclaimed.append(sandbox_id)
        raise _ReachedWarmPool

    monkeypatch.setattr(provider, "_reclaim_warm_pool_sandbox", _stop_at_warm_pool)

    try:
        # Red before the fix: the gate raises BlockingError from the inline
        # ``_sandbox_id_for_thread`` before the warm-pool layer is reached.
        with pytest.raises(_ReachedWarmPool):
            await provider._acquire_internal_async("t-id", user_id="u1")
    finally:
        provider._acquire_worker_executor.shutdown(wait=True)

    assert reclaimed == [expected_id]


async def test_blocking_probe_sandbox_id_actually_trips_the_gate(tmp_path, monkeypatch) -> None:
    """Meta-check: deriving a thread's sandbox ID inline on the loop is blocking.

    Keeps the anchor above honest: if the gate stopped seeing the syscalls
    behind ``thread_skills_view_dir(...).exists()``, the anchor would pass with
    the inline call restored.
    """
    from blockbuster import BlockingError

    provider = _make_provider(tmp_path)
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)

    with pytest.raises(BlockingError):
        provider._sandbox_id_for_thread("t-id", "u1")
