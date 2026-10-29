"""Sandbox references are server-owned and restored from authenticated scope."""

from __future__ import annotations

import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi import HTTPException
from fastapi.testclient import TestClient
from langgraph.types import Overwrite

from app.gateway.routers import runs, thread_runs, threads
from app.gateway.services import normalize_input, strip_server_owned_state_metadata
from deerflow.community.aio_sandbox.aio_sandbox_provider import AioSandboxProvider
from deerflow.sandbox.exceptions import SandboxRuntimeError
from deerflow.sandbox.lease import SANDBOX_LEASE_OWNER_CONTEXT_KEY
from deerflow.sandbox.sandbox import Sandbox
from deerflow.sandbox.sandbox_provider import SandboxProvider, reset_sandbox_provider, set_sandbox_provider
from deerflow.sandbox.search import GrepMatch
from deerflow.sandbox.tools import ensure_sandbox_initialized, ensure_sandbox_initialized_async

FOREIGN_SANDBOX_ID = "sandbox-user-b-thread-b"
OWN_SANDBOX_ID = "sandbox-user-a-thread-a"


class _ScopedSandbox(Sandbox):
    def execute_command(self, command, env=None, timeout=None):
        return command

    def read_file(self, path, start_line=None, end_line=None):
        return self.id

    def download_file(self, path):
        return self.id.encode()

    def list_dir(self, path, max_depth=2):
        return []

    def write_file(self, path, content, append=False):
        return None

    def glob(self, path, pattern, *, include_dirs=False, max_results=200):
        return [], False

    def grep(
        self,
        path: str,
        pattern: str,
        *,
        glob: str | None = None,
        literal: bool = False,
        case_sensitive: bool = False,
        max_results: int = 100,
    ) -> tuple[list[GrepMatch], bool]:
        return [], False

    def update_file(self, path, content):
        return None


class _IdentityScopedProvider(SandboxProvider):
    """Models an active foreign sandbox plus canonical current-scope lookup."""

    def __init__(self) -> None:
        self.sandboxes = {
            FOREIGN_SANDBOX_ID: _ScopedSandbox(FOREIGN_SANDBOX_ID),
            OWN_SANDBOX_ID: _ScopedSandbox(OWN_SANDBOX_ID),
        }
        self.acquire_calls: list[tuple[str | None, str | None]] = []
        self.get_calls: list[str] = []
        self.scoped_get_calls: list[tuple[str, str, str]] = []

    def acquire(self, thread_id=None, *, user_id=None):
        self.acquire_calls.append((thread_id, user_id))
        assert (user_id, thread_id) == ("user-a", "thread-a")
        return OWN_SANDBOX_ID

    async def acquire_async(self, thread_id=None, *, user_id=None):
        return self.acquire(thread_id, user_id=user_id)

    def get(self, sandbox_id):
        self.get_calls.append(sandbox_id)
        return self.sandboxes.get(sandbox_id)

    def get_scoped(self, sandbox_id, *, thread_id, user_id):
        self.scoped_get_calls.append((sandbox_id, thread_id, user_id))
        if (sandbox_id, user_id, thread_id) == (OWN_SANDBOX_ID, "user-a", "thread-a"):
            return self.sandboxes[sandbox_id]
        return None

    def release(self, sandbox_id):
        return None


def _runtime_with_foreign_checkpoint():
    return SimpleNamespace(
        state={"sandbox": {"sandbox_id": FOREIGN_SANDBOX_ID}},
        context={
            SANDBOX_LEASE_OWNER_CONTEXT_KEY: "run-owner-a",
            "thread_id": "thread-a",
            "user_id": "user-a",
        },
        config={"configurable": {"thread_id": "thread-a"}},
    )


@pytest.mark.parametrize(
    ("boundary", "payload"),
    [
        (normalize_input, {"sandbox": {"sandbox_id": FOREIGN_SANDBOX_ID}}),
        (strip_server_owned_state_metadata, {"sandbox": {"sandbox_id": FOREIGN_SANDBOX_ID}}),
    ],
)
def test_external_sandbox_state_is_rejected_at_gateway_boundaries(boundary, payload):
    with pytest.raises(HTTPException) as error:
        boundary(payload)

    assert error.value.status_code == 400
    assert FOREIGN_SANDBOX_ID not in str(error.value.detail)


def test_trusted_internal_run_input_can_restore_server_owned_sandbox_state():
    payload = {"sandbox": {"sandbox_id": OWN_SANDBOX_ID}}
    assert normalize_input(payload, trusted_internal=True)["sandbox"] == payload["sandbox"]


@pytest.mark.parametrize(
    "path",
    [
        "/api/threads/sandbox-owner-http/runs",
        "/api/threads/sandbox-owner-http/runs/stream",
        "/api/threads/sandbox-owner-http/runs/wait",
        "/api/runs/stream",
        "/api/runs/wait",
    ],
)
def test_all_external_run_entrypoints_reject_sandbox_before_worker(monkeypatch, path):
    from app.gateway import services

    app = make_authed_test_app()
    app.include_router(runs.router)
    app.include_router(thread_runs.router)
    app.state.stream_bridge = SimpleNamespace()
    app.state.run_manager = SimpleNamespace(create_or_reject=AsyncMock())
    monkeypatch.setattr(services, "get_run_context", lambda _request: SimpleNamespace(thread_store=app.state.thread_store))
    monkeypatch.setattr(services, "resolve_agent_factory", lambda _assistant: object())
    worker = AsyncMock()
    monkeypatch.setattr(services, "run_agent", worker)

    with TestClient(app) as client:
        response = client.post(
            path,
            json={
                "input": {
                    "messages": [{"role": "user", "content": "synthetic"}],
                    "sandbox": {"sandbox_id": FOREIGN_SANDBOX_ID},
                }
            },
        )

    assert response.status_code == 400, response.text
    assert FOREIGN_SANDBOX_ID not in response.text
    app.state.run_manager.create_or_reject.assert_not_awaited()
    worker.assert_not_awaited()


def test_external_state_update_rejects_sandbox_before_checkpoint_access():
    app = make_authed_test_app()
    app.include_router(threads.router)

    with TestClient(app) as client:
        response = client.post(
            "/api/threads/sandbox-owner-http/state",
            json={"values": {"sandbox": {"sandbox_id": FOREIGN_SANDBOX_ID}}},
        )

    assert response.status_code == 400, response.text
    assert FOREIGN_SANDBOX_ID not in response.text


def test_checkpoint_sandbox_is_resolved_against_current_identity_before_sync_use():
    provider = _IdentityScopedProvider()
    set_sandbox_provider(provider)
    runtime = _runtime_with_foreign_checkpoint()
    try:
        sandbox = ensure_sandbox_initialized(runtime)
    finally:
        reset_sandbox_provider()

    assert sandbox.id == OWN_SANDBOX_ID
    assert runtime.state["sandbox"] == {"sandbox_id": OWN_SANDBOX_ID}
    assert provider.acquire_calls == [("thread-a", "user-a")]
    assert provider.scoped_get_calls == [(FOREIGN_SANDBOX_ID, "thread-a", "user-a")]
    assert FOREIGN_SANDBOX_ID not in provider.get_calls


@pytest.mark.asyncio
async def test_checkpoint_sandbox_is_resolved_against_current_identity_before_async_use():
    provider = _IdentityScopedProvider()
    set_sandbox_provider(provider)
    runtime = _runtime_with_foreign_checkpoint()
    try:
        sandbox = await ensure_sandbox_initialized_async(runtime)
    finally:
        reset_sandbox_provider()

    assert sandbox.id == OWN_SANDBOX_ID
    assert runtime.state["sandbox"] == {"sandbox_id": OWN_SANDBOX_ID}
    assert provider.acquire_calls == [("thread-a", "user-a")]
    assert provider.scoped_get_calls == [(FOREIGN_SANDBOX_ID, "thread-a", "user-a")]
    assert FOREIGN_SANDBOX_ID not in provider.get_calls


@pytest.mark.asyncio
@pytest.mark.parametrize("async_path", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("fork_restored", [False, True], ids=["checkpoint", "fork"])
@pytest.mark.parametrize("with_lease_owner", [False, True], ids=["unleased", "leased"])
async def test_checkpoint_sandbox_without_thread_id_fails_closed(async_path, fork_restored, with_lease_owner):
    provider = _IdentityScopedProvider()
    set_sandbox_provider(provider)
    runtime = _runtime_with_foreign_checkpoint()
    runtime.context.pop("thread_id")
    runtime.config = {}
    if not with_lease_owner:
        runtime.context.pop(SANDBOX_LEASE_OWNER_CONTEXT_KEY)
    if fork_restored:
        runtime.state["sandbox"] = Overwrite(runtime.state["sandbox"])
    original_state = runtime.state["sandbox"]
    try:
        with pytest.raises(SandboxRuntimeError, match="Thread ID not available"):
            if async_path:
                await ensure_sandbox_initialized_async(runtime)
            else:
                ensure_sandbox_initialized(runtime)
    finally:
        reset_sandbox_provider()

    assert provider.get_calls == []
    assert provider.scoped_get_calls == []
    assert provider.acquire_calls == []
    assert runtime.state["sandbox"] is original_state
    assert "sandbox_id" not in runtime.context


def test_matching_checkpoint_sandbox_is_reused_without_acquire():
    provider = _IdentityScopedProvider()
    set_sandbox_provider(provider)
    runtime = _runtime_with_foreign_checkpoint()
    runtime.state["sandbox"] = {"sandbox_id": OWN_SANDBOX_ID}
    try:
        sandbox = ensure_sandbox_initialized(runtime)
    finally:
        reset_sandbox_provider()

    assert sandbox.id == OWN_SANDBOX_ID
    assert provider.acquire_calls == []
    assert provider.scoped_get_calls == [(OWN_SANDBOX_ID, "thread-a", "user-a")]


def test_aio_cached_lookup_requires_matching_user_and_thread_identity():
    provider = object.__new__(AioSandboxProvider)
    provider._lock = threading.Lock()
    foreign = _ScopedSandbox(FOREIGN_SANDBOX_ID)
    provider._sandboxes = {FOREIGN_SANDBOX_ID: foreign}
    provider._thread_sandboxes = {("user-b", "thread-b"): FOREIGN_SANDBOX_ID}
    provider._active_sandbox_identity = {FOREIGN_SANDBOX_ID: ("user-b", "thread-b")}
    provider._last_activity = {}

    assert (
        provider.get_scoped(
            FOREIGN_SANDBOX_ID,
            thread_id="thread-a",
            user_id="user-a",
        )
        is None
    )
    assert (
        provider.get_scoped(
            FOREIGN_SANDBOX_ID,
            thread_id="thread-b",
            user_id="user-b",
        )
        is foreign
    )
    assert FOREIGN_SANDBOX_ID in provider._last_activity
