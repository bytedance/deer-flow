"""An unconfirmed transient-bash stop must fence reuse after transport loss."""

import importlib
import json
import os
import subprocess
import threading
from types import SimpleNamespace

import httpx
import pytest
from agent_sandbox import Sandbox as SandboxClient
from support.shell import require_script_bash

from deerflow.community.aio_sandbox.ownership import MemoryOwnershipStore
from deerflow.community.aio_sandbox.quarantine import SandboxQuarantine
from deerflow.config.sandbox_config import SandboxOwnershipConfig
from deerflow.sandbox.command_scope import command_owner
from deerflow.sandbox.lease import discard_sandbox_lease_manager, get_sandbox_lease_manager


@pytest.mark.parametrize("command_path", ["sync-exec", "owned-exec", "owned-output"])
@pytest.mark.parametrize("cleanup_outcome", ["closed", "transport-error", "rejected"])
def test_transient_bash_transport_loss_requires_confirmed_cleanup(monkeypatch, command_path, cleanup_outcome):
    aio = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox")
    session_id = None
    command_id = "accepted-command"
    command_running = False
    requests = []

    def transport(request):
        nonlocal session_id, command_running
        requests.append((request.method, request.url.path))
        assert request.method == "POST"
        if request.url.path == "/v1/bash/sessions/create":
            session_id = json.loads(request.content)["session_id"]
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "session_id": session_id,
                        "status": "ready",
                        "working_dir": "/home/user",
                        "created_at": "2026-11-03T00:00:00Z",
                        "last_used_at": "2026-11-03T00:00:00Z",
                    },
                },
            )
        if request.url.path == "/v1/bash/exec":
            payload = json.loads(request.content)
            assert payload["session_id"] == session_id
            assert payload["env"] == {"REQUEST_VALUE": "ordinary-test-value"}
            assert payload.get("async_mode", False) is (command_path != "sync-exec")
            command_running = True  # The service accepted/spawned the command.
            if command_path != "owned-output":
                raise httpx.ReadTimeout("response lost after execution started", request=request)
            return httpx.Response(200, json={"success": True, "data": {"session_id": session_id, "command_id": command_id, "command": payload["command"], "status": "running"}})
        if request.url.path == "/v1/bash/output":
            payload = json.loads(request.content)
            assert payload["session_id"] == session_id and payload["command_id"] == command_id
            raise httpx.ReadError("output connection lost", request=request)
        assert request.url.path == f"/v1/bash/sessions/{session_id}/close"
        if cleanup_outcome == "transport-error":
            raise httpx.ConnectError("service remains unavailable during cleanup", request=request)
        if cleanup_outcome == "rejected":
            return httpx.Response(200, json={"success": False, "message": "Close failed"})
        command_running = False
        return httpx.Response(200, json={"success": True, "message": "Session closed"})

    with httpx.Client(transport=httpx.MockTransport(transport)) as http_client:
        sdk = SandboxClient(base_url="http://sandbox.invalid", httpx_client=http_client)
        monkeypatch.setattr(aio, "AioSandboxClient", lambda **_kwargs: sdk)
        monkeypatch.setattr(aio, "sandbox_http_trust_env", lambda _url: True)
        sandbox = aio.AioSandbox("transient-bash-cleanup", "http://sandbox.invalid")
        with command_owner(sandbox, "execution" if command_path != "sync-exec" else None):
            result = sandbox.execute_command("sleep 60; printf finished", env={"REQUEST_VALUE": "ordinary-test-value"})

        assert result.startswith("Error:")
        assert requests.count(("POST", "/v1/bash/exec")) == 1, "Never repeat accepted execution after response loss"
        assert requests.count(("POST", f"/v1/bash/sessions/{session_id}/close")) == 1
        assert not sandbox.has_pending_session_creates, "Session creation was confirmed before command submission"
        assert command_running is (cleanup_outcome != "closed")
        assert sandbox.requires_container_recycle is (cleanup_outcome != "closed"), "A failed cleanup left the command running but allowed warm reuse"


@pytest.mark.parametrize("scope_id", [None, "execution"])
@pytest.mark.parametrize("status", ["completed", "timed_out", "killed"])
def test_confirmed_terminal_command_keeps_its_result_when_session_cleanup_fails(monkeypatch, scope_id, status):
    aio = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox")
    closed = []

    def transport(request):
        payload = json.loads(request.content) if request.content else {}
        if request.url.path == "/v1/bash/sessions/create":
            return httpx.Response(200, json={"success": True, "data": {"session_id": payload["session_id"], "status": "ready", "working_dir": "/home/user", "created_at": "2026-11-03T00:00:00Z", "last_used_at": "2026-11-03T00:00:00Z"}})
        command = {"command_id": "terminal-command", "command": "printf finished", "status": status, "exit_code": 17 if status == "completed" else 124}
        if request.url.path == "/v1/bash/exec":
            return httpx.Response(200, json={"success": True, "data": {**command, "session_id": payload["session_id"], "status": "running" if scope_id else status, "stdout": "finished"}})
        if request.url.path == "/v1/bash/output":
            return httpx.Response(200, json={"success": True, "data": {"session_id": payload["session_id"], "command": command, "stdout": "finished"}})
        assert request.url.path.endswith("/close")
        closed.append(request.url.path)
        raise httpx.ConnectError("cleanup connection unavailable after confirmed completion", request=request)

    with httpx.Client(transport=httpx.MockTransport(transport)) as http_client:
        sdk = SandboxClient(base_url="http://sandbox.invalid", httpx_client=http_client)
        monkeypatch.setattr(aio, "AioSandboxClient", lambda **_kwargs: sdk)
        monkeypatch.setattr(aio, "sandbox_http_trust_env", lambda _url: True)
        sandbox = aio.AioSandbox("terminal-bash-cleanup", "http://sandbox.invalid")
        with command_owner(sandbox, scope_id):
            result = sandbox.execute_command("printf finished", env={"REQUEST_VALUE": "ordinary-test-value"})
        assert result.startswith("finished")
        assert "cleanup connection" not in result
        assert len(closed) == 1
        assert not sandbox.requires_container_recycle


@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_normal_execution_release_does_not_reuse_a_runtime_with_an_unstopped_bash(monkeypatch, tmp_path, cleanup_fails):
    aio = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox")
    provider_module = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    shell = require_script_bash()
    process = None
    close_requests = []
    clients = []
    runtime_stops = []

    def stop_process():
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait(5)

    def transport(request):
        nonlocal process
        payload = json.loads(request.content) if request.content else {}
        assert request.method == "POST"
        if request.url.path == "/v1/bash/sessions/create":
            return httpx.Response(200, json={"success": True, "data": {"session_id": payload["session_id"], "status": "ready", "working_dir": "/home/user", "created_at": "2026-11-03T00:00:00Z", "last_used_at": "2026-11-03T00:00:00Z"}})
        if request.url.path == "/v1/bash/exec":
            assert process is None, "The original command must never be replayed"
            process = subprocess.Popen(
                [shell, "--noprofile", "--norc", "-c", payload["command"]],
                cwd=tmp_path,
                env={**os.environ, **payload["env"]},
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return httpx.Response(200, json={"success": True, "data": {"session_id": payload["session_id"], "command_id": "running-command", "command": payload["command"], "status": "running"}})
        if request.url.path == "/v1/bash/output":
            raise httpx.ReadError("output connection lost", request=request)
        assert request.url.path.endswith("/close")
        close_requests.append(request.url.path)
        if cleanup_fails:
            raise httpx.ConnectError("service remains unavailable during cleanup", request=request)
        stop_process()
        return httpx.Response(200, json={"success": True})

    def make_sdk(**_kwargs):
        client = httpx.Client(transport=httpx.MockTransport(transport))
        clients.append(client)
        return SandboxClient(base_url="http://sandbox.invalid", httpx_client=client)

    monkeypatch.setattr(aio, "AioSandboxClient", make_sdk)
    monkeypatch.setattr(aio, "sandbox_http_trust_env", lambda _url: True)
    sandbox = aio.AioSandbox("runtime", "http://sandbox.invalid")
    info = provider_module.SandboxInfo(sandbox.id, sandbox.base_url, container_id="runtime-generation")
    provider = provider_module.AioSandboxProvider.__new__(provider_module.AioSandboxProvider)
    provider._lock = threading.Lock()
    provider._config = {"idle_timeout": 600, "command_timeout": 600}
    provider._sandboxes = {sandbox.id: sandbox}
    provider._sandbox_infos = {sandbox.id: info}
    provider._thread_sandboxes = {("user", "thread"): sandbox.id}
    provider._last_activity = {sandbox.id: 0.0}
    provider._active_sandbox_identity = {sandbox.id: ("user", "thread")}
    provider._warm_pool = {}
    provider._warm_pool_identity = {}
    provider._local_teardown = set()
    provider._acquire_epoch = {}
    provider._acquire_epoch_counter = 0
    provider._acquire_inflight = {}
    provider._cleanup_retry_ids = set()
    provider._admission_closed = False
    provider._owner_id = "worker"
    provider._ownership_config = SandboxOwnershipConfig()
    provider._ownership = MemoryOwnershipStore(owner_id="worker", ttl_seconds=600)
    provider._quarantine = SandboxQuarantine(tmp_path / "quarantine", "worker")

    def destroy(runtime):
        runtime_stops.append(runtime)
        stop_process()

    provider._backend = SimpleNamespace(destroy=destroy, is_alive=lambda _info: True)
    monkeypatch.setattr(provider, "_check_sandbox_reuse_policy", lambda *_args: None)
    manager = get_sandbox_lease_manager(provider)
    try:
        manager.retain("execution", sandbox.id, thread_id="thread", user_id="user")
        with command_owner(sandbox, "execution"):
            result = sandbox.execute_command("while [ ! -f continue ]; do sleep 0.02; done; printf late-write > output.txt", env={"REQUEST_VALUE": "ordinary-test-value"})
        assert result == "Error: output connection lost"
        assert process is not None
        assert not (tmp_path / "output.txt").exists()

        # An Error string is a normal tool result. Normal completion releases
        # its execution holder without taking the run-cancellation path.
        manager.release("execution")
        assert manager.binding_for("execution") is None
        assert len(close_requests) == 1
        parked = sandbox.id in provider._warm_pool
        reacquired = provider._reclaim_warm_pool_sandbox("thread", sandbox.id, user_id="user") if parked else None
        (tmp_path / "continue").touch()
        process.wait(5)
        late_write = (tmp_path / "output.txt").exists()

        assert not (cleanup_fails and parked and reacquired and late_write), "The old command wrote into the runtime after normal release and warm reuse"
        assert len(runtime_stops) == int(cleanup_fails)
        if not cleanup_fails:
            assert parked and reacquired == sandbox.id
            assert not late_write
    finally:
        (tmp_path / "continue").touch()
        stop_process()
        discard_sandbox_lease_manager(provider)
        for client in clients:
            client.close()
        provider._ownership.close()
