"""Blocking-I/O anchors for ``VeFaaSSandboxProvider``.

1. ``get()`` and ``get_scoped()`` run directly on the LangGraph event loop for
   every tool call; they must never touch the ownership store or network.
2. Contended ``acquire_async()`` calls serialize on ``AcquireSerializer`` and
   must execute control-plane HTTP and ownership store I/O strictly off the
   event loop.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
from blockbuster import BlockingError
from test_vefaas_sandbox_provider import _FakeVeFaaSServer, _install_provider

from deerflow.community.aio_sandbox.ownership import RenewOutcome
from deerflow.community.vefaas_sandbox import VeFaaSClient

pytestmark = pytest.mark.asyncio


class _BlockingProbeOwnershipStore:
    """Ownership store whose every method executes real blocking file I/O."""

    supports_cross_process = True

    def __init__(self, probe_path: Path) -> None:
        self._probe_path = probe_path
        self._probe_path.write_text("owner", encoding="utf-8")
        self.calls: list[str] = []

    @property
    def owner_id(self) -> str:
        return "worker-vefaas-blockingio"

    def _touch(self, op: str) -> str:
        self.calls.append(op)
        return self._probe_path.read_text(encoding="utf-8")

    def take(self, sandbox_id: str) -> bool:
        self._touch("take")
        return True

    def claim(self, sandbox_id: str, *, for_destroy: bool = False) -> bool:
        self._touch("claim")
        return True

    def renew(self, sandbox_id: str) -> RenewOutcome:
        self._touch("renew")
        return RenewOutcome.RENEWED

    def release(self, sandbox_id: str) -> None:
        self._touch("release")

    def owner(self, sandbox_id: str) -> str | None:
        return self._touch("owner")

    def close(self) -> None:
        pass


class _FileIOProbingVeFaaSServer(_FakeVeFaaSServer):
    """Fake veFaaS control plane that performs real blocking file I/O on every request."""

    def __init__(self, probe_dir: Path) -> None:
        super().__init__()
        self._probe_dir = probe_dir

    def handler(self, request: httpx.Request) -> httpx.Response:
        probe = self._probe_dir / f"req-{len(self.requests) + 1}.probe"
        probe.write_text("x" * 2048, encoding="utf-8")
        return super().handler(request)


async def test_get_and_get_scoped_do_no_blocking_io_on_event_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    provider, _server, _aio = _install_provider(monkeypatch, tmp_path)
    probe_store = await asyncio.to_thread(_BlockingProbeOwnershipStore, tmp_path / "ownership-probe")
    provider._ownership = probe_store
    try:
        sandbox_id = await provider.acquire_async("t-get", user_id="u-get")
        probe_store.calls.clear()
        assert provider.get(sandbox_id) is not None
        assert provider.get_scoped(sandbox_id, thread_id="t-get", user_id="u-get") is not None
        assert provider.get_scoped(sandbox_id, thread_id="t-get", user_id="other") is None
        assert probe_store.calls == []

        # Meta-check (teeth): hitting the probe store via provider code on the loop trips Blockbuster.
        with pytest.raises(BlockingError):
            provider._renew_leases_once()
    finally:
        await asyncio.to_thread(provider.shutdown)


async def test_contended_acquire_async_stays_off_event_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    probing_server = _FileIOProbingVeFaaSServer(tmp_path)
    provider, _server, _aio = _install_provider(monkeypatch, tmp_path, server=probing_server)
    provider._ownership = await asyncio.to_thread(_BlockingProbeOwnershipStore, tmp_path / "ownership-probe-2")
    try:
        first, second = await asyncio.gather(
            provider.acquire_async("t-contend", user_id="u-contend"),
            provider.acquire_async("t-contend", user_id="u-contend"),
        )
        assert first == second

        # Meta-check (teeth): calling sync acquire directly on the event loop trips Blockbuster.
        with pytest.raises(BlockingError):
            provider.acquire("t-sync-fail", user_id="u-contend")
    finally:
        await asyncio.to_thread(provider.shutdown)


async def test_client_construction_is_non_blocking_on_event_loop() -> None:
    """Constructing VeFaaSClient must defer httpx.Client TLS setup off the event loop."""
    client = VeFaaSClient(
        endpoint="https://vefaas.ap-southeast-1.byteplusapi.com",
        region="ap-southeast-1",
        access_key="ak",
        secret_key="sk",
    )
    assert client._client is None
    client.close()
