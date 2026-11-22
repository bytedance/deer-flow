"""Blocking-I/O anchors for ``VeFaaSSandboxProvider``.

1. ``get()`` and ``get_scoped()`` run directly on the LangGraph event loop for
   every tool call; they must never touch the ownership store or network.
2. Contended ``acquire_async()`` calls serialize on ``AcquireSerializer`` and
   must execute control-plane HTTP and ownership store I/O strictly off the
   event loop.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

import httpx
import pytest
from blockbuster import BlockingError
from test_vefaas_sandbox_provider import _FakeAioSandbox, _FakeVeFaaSServer, _install_provider, _make_app_config

from deerflow.community.aio_sandbox.ownership import RenewOutcome
from deerflow.community.vefaas_sandbox import VeFaaSClient, VeFaaSSandboxProvider
from deerflow.community.vefaas_sandbox import provider as provider_mod
from deerflow.sandbox.identity import derive_sandbox_scope_token
from deerflow.sandbox.sandbox_provider import hold_sandbox_shutdown_ownership

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


async def test_precache_on_startup_stays_off_event_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Constructing VeFaaSSandboxProvider with precache_on_startup=True must stay off-loop."""
    probing_server = _FileIOProbingVeFaaSServer(tmp_path)
    submitted = threading.Event()
    orig_handler = probing_server.handler

    def tracking_handler(request: httpx.Request) -> httpx.Response:
        resp = orig_handler(request)
        if request.url.params.get("Action") == "PrecacheSandboxImages":
            submitted.set()
        return resp

    probing_server.handler = tracking_handler  # type: ignore[method-assign]
    app_cfg = await asyncio.to_thread(
        lambda: _make_app_config(
            tmp_path,
            sandbox_overrides={
                "vefaas": {
                    "precache_images": ["cr.example.com/aio:latest"],
                    "precache_on_startup": True,
                }
            },
        )
    )
    monkeypatch.setattr(provider_mod, "get_app_config", lambda: app_cfg)
    mock_http = httpx.Client(transport=httpx.MockTransport(probing_server.handler))
    client = VeFaaSClient(
        endpoint="https://vefaas.ap-southeast-1.byteplusapi.com",
        region="ap-southeast-1",
        access_key="AK-TEST-KEY",
        secret_key="SK-TEST-SECRET",
        httpx_client=mock_http,
    )
    # Construct directly on the event loop: startup precache must run strictly on its daemon thread.
    with hold_sandbox_shutdown_ownership():
        provider = VeFaaSSandboxProvider(client=client)
    try:
        assert await asyncio.to_thread(submitted.wait, 5)
    finally:
        await asyncio.to_thread(provider.shutdown)
        await asyncio.to_thread(mock_http.close)


async def test_acquire_async_resume_paused_and_restore_snapshot_stay_off_event_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resuming a paused sandbox or restoring a snapshot via acquire_async must stay off-loop."""
    probing_server = _FileIOProbingVeFaaSServer(tmp_path)
    sid_paused = derive_sandbox_scope_token(user_id="u-bio", thread_id="t-bio-paused")
    sid_snap = derive_sandbox_scope_token(user_id="u-bio", thread_id="t-bio-snap")
    probing_server.sandboxes["vefaas-bio-paused"] = {
        "Id": "vefaas-bio-paused",
        "FunctionId": "fn-demo-app",
        "Status": "Paused",
        "Pending": False,
        "Metadata": {
            provider_mod.META_KEY_PROVIDER: provider_mod.META_VAL_PROVIDER,
            provider_mod.META_KEY_SANDBOX_ID: sid_paused,
        },
    }
    probing_server.snapshots["snap-bio-1"] = {
        "SnapshotId": "snap-bio-1",
        "SandboxId": "vefaas-old",
        "FunctionId": "fn-demo-app",
        "Status": "Ready",
        "SnapshotType": "disk",
        "CreatedAt": "2026-11-23T01:00:00Z",
        "Metadata": {
            provider_mod.META_KEY_PROVIDER: provider_mod.META_VAL_PROVIDER,
            provider_mod.META_KEY_SANDBOX_ID: sid_snap,
        },
    }

    provider, _, _ = await asyncio.to_thread(
        lambda: _install_provider(
            monkeypatch,
            tmp_path,
            server=probing_server,
            sandbox_overrides={"vefaas": {"snapshot_on_idle": True}},
        )
    )
    provider._ownership = await asyncio.to_thread(_BlockingProbeOwnershipStore, tmp_path / "ownership-probe-3")

    class _PreInitAio(_FakeAioSandbox):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self.uploaded_files[provider_mod._INIT_MARKER_PATH] = f"{self.id}\n".encode()

    monkeypatch.setattr(provider_mod, "AioSandbox", _PreInitAio)
    try:
        resumed = await provider.acquire_async("t-bio-paused", user_id="u-bio")
        assert resumed == sid_paused
        restored = await provider.acquire_async("t-bio-snap", user_id="u-bio")
        assert restored == sid_snap

        assert any(action == "ResumeSandbox" for action, _, _ in probing_server.requests)
        create_reqs = [payload for action, payload, _ in probing_server.requests if action == "CreateSandbox"]
        assert create_reqs and create_reqs[-1]["SnapshotId"] == "snap-bio-1"
    finally:
        await asyncio.to_thread(provider.shutdown)
