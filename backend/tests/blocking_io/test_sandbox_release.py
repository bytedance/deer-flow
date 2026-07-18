"""Regression anchor: sandbox release must not block the event loop.

``AioSandboxProvider.release()`` refreshes the ownership lease
(``_refresh_ownership`` -> store ``renew``/``claim``), which is blocking
filesystem or network IO depending on the backend. It runs from
``SandboxMiddleware`` at the end of every turn: the async gateway path
(``aafter_agent``) offloads it with ``asyncio.to_thread``, so the store round
trip stays off the loop. This pins that offload — a refactor that dropped it
(or wired ``aafter_agent`` to call ``release`` directly) would put a Redis round
trip on the event loop for sync graph execution, as flagged in review of
PR #4221.

The ownership store is injected as a **blocking probe** whose every method does
real file IO, so the anchor keeps its teeth regardless of the configured backend
(the default ``memory`` store does no IO to catch; redis does network IO).
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


def _make_provider_with_active_sandbox(tmp_path: Path, sandbox_id: str):
    """A real provider (no ``__init__``) holding one active sandbox to release."""
    from deerflow.community.aio_sandbox.aio_sandbox_provider import AioSandboxProvider
    from deerflow.community.aio_sandbox.sandbox_info import SandboxInfo
    from deerflow.config.sandbox_config import SandboxOwnershipConfig

    provider = AioSandboxProvider.__new__(AioSandboxProvider)
    provider._lock = threading.Lock()
    provider._sandboxes = {sandbox_id: MagicMock()}
    provider._sandbox_infos = {
        sandbox_id: SandboxInfo(
            sandbox_id=sandbox_id,
            sandbox_url="http://localhost:8080",
            container_name=f"deer-flow-sandbox-{sandbox_id}",
            created_at=1.0,
        )
    }
    provider._thread_sandboxes = {}
    provider._thread_locks = {}
    provider._last_activity = {sandbox_id: 1.0}
    provider._warm_pool = {}
    provider._unowned_since = {}
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


async def test_aafter_agent_offloads_release_off_the_event_loop(tmp_path, monkeypatch):
    """The async release hook must keep the ownership-store round trip off-loop.

    If it regresses to calling ``release`` directly, the probe's file IO trips
    the strict Blockbuster gate.
    """
    import deerflow.sandbox.middleware as mw_mod

    provider = _make_provider_with_active_sandbox(tmp_path, "sb-release")
    monkeypatch.setattr(mw_mod, "get_sandbox_provider", lambda: provider)

    mw = mw_mod.SandboxMiddleware()
    state = {"sandbox": {"sandbox_id": "sb-release"}}

    # Offloaded via asyncio.to_thread, so no BlockingError under the strict gate.
    await mw.aafter_agent(state, MagicMock())

    # The release actually happened (parked in the warm pool), so the anchor is
    # exercising the real path, not a no-op.
    assert "sb-release" in provider._warm_pool


async def test_release_on_loop_trips_the_gate(tmp_path):
    """Meta-check: prove the probe has teeth, so the test above is not vacuous.

    Calling ``release`` directly on the event loop must raise, otherwise the
    offload anchor could pass because the store quietly stopped doing IO.
    """
    from blockbuster import BlockingError

    provider = _make_provider_with_active_sandbox(tmp_path, "sb-onloop")

    with pytest.raises(BlockingError):
        provider.release("sb-onloop")
