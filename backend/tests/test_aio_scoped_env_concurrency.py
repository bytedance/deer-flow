"""Scoped env commands run independently and drain before client teardown."""

import asyncio
import importlib
import json
import os
import shlex
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import httpx
import pytest
from agent_sandbox import Sandbox as SandboxClient
from support.shell import require_script_bash

from deerflow.runtime.secret_context import ACTIVE_SECRETS_CONTEXT_KEY
from deerflow.sandbox.command_scope import command_owner
from deerflow.sandbox.lease import run_sync_lifecycle_operation


@pytest.mark.parametrize("mode", ["plain", "active-skill-env", "lark-cli"])
def test_independent_subagent_commands_enter_distinct_sessions_concurrently(monkeypatch, tmp_path, mode):
    aio = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox")
    tools = importlib.import_module("deerflow.sandbox.tools")
    app_config = importlib.import_module("deerflow.config.app_config")
    native_bash = require_script_bash()
    shim_bin = tmp_path / "bin"
    shim_bin.mkdir()
    shim = shim_bin / "lark-cli"
    shim.write_text("#!/bin/sh\nsleep 0.4\nprintf done\n", encoding="utf-8")
    shim.chmod(0o755)
    bookkeeping = threading.Lock()
    sessions = {}
    in_flight = peak = 0
    entered = threading.Event()
    requests = []

    def complete(session):
        nonlocal in_flight
        if session.get("finished"):
            return
        try:
            # Keep each service-side operation admitted until all peers have
            # entered. Correctness must not depend on their sleep windows
            # overlapping on a busy host.
            assert entered.wait(5), "Independent commands did not all reach the service before any completion"
            stdout, stderr = session["process"].communicate(timeout=5)
            session.update(stdout=stdout, stderr=stderr, finished=True)
        finally:
            with bookkeeping:
                in_flight -= 1

    def transport(request):
        nonlocal in_flight, peak
        path = request.url.path
        payload = json.loads(request.content) if request.content else {}
        with bookkeeping:
            requests.append((request.method, path, payload))
        if path == "/v1/shell/sessions/create":
            return httpx.Response(200, json={"success": True, "data": {"session_id": payload["id"], "working_dir": "/mnt/user-data/workspace"}})
        if path == "/v1/bash/sessions/create":
            return httpx.Response(
                200, json={"success": True, "data": {"session_id": payload["session_id"], "status": "ready", "working_dir": "/mnt/user-data/workspace", "created_at": "2026-11-03T00:00:00Z", "last_used_at": "2026-11-03T00:00:00Z"}}
            )
        if path in ("/v1/shell/exec", "/v1/bash/exec"):
            session_id = payload.get("id") or payload.get("session_id")
            assert session_id is not None
            command = payload["command"].replace("cd /mnt/user-data/workspace;", f"cd {shlex.quote(tmp_path.as_posix())};")
            environment = {**os.environ, **payload.get("env", {})}
            if "PATH" in payload.get("env", {}):
                environment["PATH"] = environment["PATH"].replace("/mnt/integrations/lark-cli/runtime/bin", shim_bin.as_posix())
            process = subprocess.Popen([native_bash, "--noprofile", "--norc", "-c", command], cwd=tmp_path, env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
            session = {"process": process, "command": payload["command"], "id": session_id}
            with bookkeeping:
                sessions[session_id] = session
                in_flight += 1
                peak = max(peak, in_flight)
                if in_flight == 3:
                    entered.set()
            data = {"session_id": session_id, "command": payload["command"], "status": "running"}
            if path == "/v1/bash/exec":
                data["command_id"] = session_id
            return httpx.Response(200, json={"success": True, "data": data})
        if path == "/v1/shell/wait":
            complete(sessions[payload["id"]])
            return httpx.Response(200, json={"success": True, "data": {"status": "completed"}})
        if path == "/v1/shell/view":
            session = sessions[payload["id"]]
            assert session["finished"]
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "session_id": session["id"],
                        "status": "completed",
                        "command": session["command"],
                        "output": session["stdout"],
                        "exit_code": session["process"].returncode,
                        "console": [{"ps1": "$ ", "command": session["command"], "output": session["stdout"]}],
                    },
                },
            )
        if path == "/v1/bash/output":
            session = sessions[payload["session_id"]]
            complete(session)
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "session_id": session["id"],
                        "stdout": session["stdout"],
                        "stderr": session["stderr"],
                        "command": {"command_id": session["id"], "command": session["command"], "status": "completed", "exit_code": session["process"].returncode},
                    },
                },
            )
        assert path.startswith("/v1/shell/sessions/") or (path.startswith("/v1/bash/sessions/") and path.endswith("/close"))
        return httpx.Response(200, json={"success": True})

    with httpx.Client(transport=httpx.MockTransport(transport)) as http_client:
        sdk = SandboxClient(base_url="http://sandbox.invalid", httpx_client=http_client)
        monkeypatch.setattr(aio, "AioSandboxClient", lambda **_kwargs: sdk)
        monkeypatch.setattr(aio, "sandbox_http_trust_env", lambda _url: True)
        sandbox = aio.AioSandbox("parallel-public-tool", "http://sandbox.invalid", lark_cli_broker=False)
        monkeypatch.setattr(tools, "ensure_sandbox_initialized", lambda _runtime: sandbox)
        monkeypatch.setattr(tools, "is_local_sandbox", lambda _runtime: False)
        monkeypatch.setattr(app_config, "get_app_config", lambda: SimpleNamespace(sandbox=SimpleNamespace(bash_output_max_chars=20000, bash_command_timeout=30)))
        start = threading.Barrier(3)

        def worker(index):
            owner = f"subagent:{index}"
            context = {"user_id": "test-user", "sandbox_lease_owner_id": owner, "sandbox_command_scope_id": owner}
            if mode == "active-skill-env":
                context[ACTIVE_SECRETS_CONTEXT_KEY] = {"REQUEST_TEST_VALUE": "ordinary-test-value"}
            runtime = SimpleNamespace(context=context, state={})
            start.wait(timeout=5)
            command = "lark-cli audit-wait" if mode == "lark-cli" else "sleep 0.4; printf done"
            return tools.bash_tool.func(runtime, command)

        started = time.perf_counter()
        try:
            with ThreadPoolExecutor(max_workers=3) as executor:
                futures = [executor.submit(worker, index) for index in range(3)]
                results = [future.result(timeout=20) for future in futures]
            elapsed = time.perf_counter() - started
            assert results == ["done"] * 3
            assert len(sessions) == 3, "Each operation received its own real SDK session identity"
            print(
                "AIO_ADMISSION_REGRESSION "
                + json.dumps(
                    {
                        "mode": mode,
                        "commands": 3,
                        "sleep_seconds": 0.4,
                        # Diagnostic only: this includes the admission gate and
                        # is not the separate ungated audit benchmark.
                        "gated_elapsed_seconds": round(elapsed, 4),
                        "peak_admitted_commands": peak,
                        "all_entered_together": entered.is_set(),
                        "exec_requests": sum(path in ("/v1/shell/exec", "/v1/bash/exec") for _, path, _ in requests),
                    }
                )
            )
            assert entered.is_set() and peak == 3, "Independent fresh sessions were serialized before reaching the AIO service"
        finally:
            for session in sessions.values():
                if session["process"].poll() is None:
                    session["process"].terminate()
                session["process"].communicate(timeout=5)
            sandbox.close()


class _ObservedScopeLock:
    def __init__(self, lock):
        self.lock = lock
        self.queued = threading.Event()
        self.teardown = threading.Event()

    def acquire(self, *args, **kwargs):
        if threading.current_thread().name == "queued-env":
            self.queued.set()
        if threading.current_thread().name == "scope-teardown":
            self.teardown.set()
        return self.lock.acquire(*args, **kwargs)

    def release(self):
        self.lock.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *_args):
        self.release()


@pytest.fixture
def paused_env_command(monkeypatch, request):
    aio = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox")
    entered = threading.Event()
    resume = threading.Event()
    client_closed = threading.Event()
    requests = []
    executions = []
    control_sessions = set()
    request_lock = threading.Lock()

    def transport(request):
        assert not client_closed.is_set(), "Client closed while an admitted command still owned it"
        path = request.url.path
        payload = json.loads(request.content) if request.content else {}
        with request_lock:
            requests.append((request.method, path, payload))
        if path == "/v1/bash/sessions/create":
            return httpx.Response(200, json={"success": True, "data": {"session_id": payload["session_id"], "status": "ready", "working_dir": "/home/user", "created_at": "2026-11-03T00:00:00Z", "last_used_at": "2026-11-03T00:00:00Z"}})
        if path == "/v1/bash/exec":
            with request_lock:
                executions.append(payload)
            return httpx.Response(200, json={"success": True, "data": {"session_id": payload["session_id"], "command_id": payload["session_id"], "command": payload["command"], "status": "running"}})
        if path == "/v1/bash/output":
            execution = next(item for item in executions if item["session_id"] == payload["session_id"])
            if execution is executions[0]:
                entered.set()
                assert resume.wait(5), "Test never released the first command"
            assert not client_closed.is_set()
            return httpx.Response(
                200, json={"success": True, "data": {"session_id": payload["session_id"], "stdout": "done", "command": {"command_id": payload["session_id"], "command": execution["command"], "status": "completed", "exit_code": 0}}}
            )
        if path.startswith("/v1/bash/sessions/") and path.endswith("/close"):
            return httpx.Response(200, json={"success": True})
        if path == "/v1/shell/sessions/create":
            control_sessions.add(payload["id"])
            return httpx.Response(200, json={"success": True, "data": {"session_id": payload["id"], "working_dir": "/home/user"}})
        if path == "/v1/shell/exec":
            assert payload["id"] in control_sessions
            assert payload["command"].startswith("python3 -c ")
            return httpx.Response(200, json={"success": True, "data": {"session_id": payload["id"], "command": payload["command"], "status": "running"}})
        if path == "/v1/shell/view":
            assert payload["id"] in control_sessions
            return httpx.Response(200, json={"success": True, "data": {"session_id": payload["id"], "output": '{"remaining":0}', "status": "completed", "exit_code": 0}})
        assert request.method == "DELETE" and path.removeprefix("/v1/shell/sessions/") in control_sessions
        return httpx.Response(200, json={"success": True})

    http_transport = httpx.MockTransport(transport)
    real_close = http_transport.close

    def close():
        client_closed.set()
        real_close()

    monkeypatch.setattr(http_transport, "close", close)
    http_client = httpx.Client(transport=http_transport)
    sdk = SandboxClient(base_url="http://sandbox.invalid", httpx_client=http_client)
    monkeypatch.setattr(aio, "AioSandboxClient", lambda **_kwargs: sdk)
    monkeypatch.setattr(aio, "sandbox_http_trust_env", lambda _url: True)
    options = {"max_bash_sessions": request.param} if hasattr(request, "param") else {}
    sandbox = aio.AioSandbox("scoped-env-lifecycle", "http://sandbox.invalid", **options)

    def run(owner="first", value="one"):
        with command_owner(sandbox, owner):
            return sandbox.execute_command_in_scope("ordinary-command", env={"REQUEST_VALUE": value}, scope_id=owner)

    yield SimpleNamespace(sandbox=sandbox, entered=entered, resume=resume, client_closed=client_closed, http_client=http_client, requests=requests, executions=executions, controls=control_sessions, run=run)
    resume.set()
    sandbox.close()
    http_client.close()


def _start_observed_thread(function, *, name):
    results = []
    errors = []

    def run():
        try:
            results.append(function())
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=run, name=name)
    thread.start()
    return SimpleNamespace(thread=thread, results=results, errors=errors)


def _join_observed_thread(worker):
    worker.thread.join(5)
    assert not worker.thread.is_alive()
    assert not worker.errors


def test_env_commands_in_one_scope_remain_serialized(paused_env_command):
    case = paused_env_command
    first = _start_observed_thread(case.run, name="first-env")
    second = None
    try:
        assert case.entered.wait(5)
        scoped = case.sandbox._scoped_shell_sessions["first"]
        observed = _ObservedScopeLock(scoped.lock)
        scoped.lock = observed
        second = _start_observed_thread(lambda: case.run(value="two"), name="queued-env")
        assert observed.queued.wait(5)
        assert len(case.executions) == 1
        case.resume.set()
        _join_observed_thread(first)
        _join_observed_thread(second)
        assert first.results == second.results == ["done"]
        assert [item["env"] for item in case.executions] == [{"REQUEST_VALUE": "one"}, {"REQUEST_VALUE": "two"}]
        assert len({item["session_id"] for item in case.executions}) == 2
        assert not case.controls
    finally:
        case.resume.set()
        _join_observed_thread(first)
        if second is not None:
            _join_observed_thread(second)


@pytest.mark.parametrize("teardown", ["close", "release"])
def test_teardown_drains_env_and_rejects_already_queued_commands(paused_env_command, teardown):
    case = paused_env_command
    first = _start_observed_thread(case.run, name="first-env")
    queued = stopping = None
    try:
        assert case.entered.wait(5)
        scoped = case.sandbox._scoped_shell_sessions["first"]
        observed = _ObservedScopeLock(scoped.lock)
        scoped.lock = observed
        queued = _start_observed_thread(case.run, name="queued-env")
        assert observed.queued.wait(5)
        action = case.sandbox.close if teardown == "close" else lambda: case.sandbox.release_command_scope("first")
        stopping = _start_observed_thread(action, name="scope-teardown")
        assert observed.teardown.wait(5)
        assert not case.client_closed.is_set()
        assert stopping.thread.is_alive()
        if teardown == "close":
            assert case.run(owner="new") == "Error: sandbox client is closed"
        case.resume.set()
        for worker in (first, queued, stopping):
            _join_observed_thread(worker)
        assert first.results == ["done"]
        assert queued.results == ["Error: sandbox command scope is no longer active"]
        assert len(case.executions) == 1
        assert case.client_closed.is_set() is (teardown == "close")
        assert not case.sandbox._scoped_shell_sessions
    finally:
        case.resume.set()
        for worker in (first, queued, stopping):
            if worker is not None:
                _join_observed_thread(worker)


def test_cancelled_env_waiter_never_submits_a_command(paused_env_command):
    case = paused_env_command
    first = _start_observed_thread(case.run, name="first-env")
    queued = None
    try:
        assert case.entered.wait(5)
        scoped = case.sandbox._scoped_shell_sessions["first"]
        observed = _ObservedScopeLock(scoped.lock)
        scoped.lock = observed
        queued = _start_observed_thread(case.run, name="queued-env")
        assert observed.queued.wait(5)
        case.sandbox.request_command_cancel("first")
        _join_observed_thread(queued)
        assert "cancelled" in queued.results[0]
        assert len(case.executions) == 1
        assert not case.controls
    finally:
        case.resume.set()
        _join_observed_thread(first)
        if queued is not None:
            _join_observed_thread(queued)


@pytest.mark.parametrize("close_first", [False, True])
@pytest.mark.parametrize("release_count", [1, 2])
def test_cancel_reaches_env_command_while_scope_drains(paused_env_command, close_first, release_count):
    case = paused_env_command
    first = _start_observed_thread(case.run, name="first-env")
    workers = []
    progress = {name: threading.Event() for name in ["close", "release-0", "release-1"]}

    class DrainLock(_ObservedScopeLock):
        def acquire(self, *args, **kwargs):
            if event := progress.get(threading.current_thread().name):
                event.set()
            return super().acquire(*args, **kwargs)

    try:
        assert case.entered.wait(5)
        owner = case.sandbox._command_scopes.find("first")
        scoped = case.sandbox._scoped_shell_sessions["first"]
        scoped.lock = DrainLock(scoped.lock)
        if close_first:
            workers.append(_start_observed_thread(case.sandbox.close, name="close"))
            assert progress["close"].wait(5)
        for index in range(release_count):
            workers.append(_start_observed_thread(lambda: case.sandbox.release_command_scope("first"), name=f"release-{index}"))
            assert progress[f"release-{index}"].wait(5), "Release must join the scope even when close is already draining it"
        case.sandbox.request_command_cancel("first")
        assert owner.cancelled.is_set(), "Cancellation was routed to a replacement owner instead of the running command"
        assert case.sandbox._command_scopes.find("first") is owner
        case.resume.set()
        for worker in [first, *workers]:
            _join_observed_thread(worker)
        assert "cancelled" in first.results[0]
        assert owner.cleaned.is_set()
        assert len(case.controls) == 1
        assert sum(path.endswith("/close") for _, path, _ in case.requests) == 1
        assert case.sandbox._command_scopes.find("first") is None
        assert not case.sandbox._scoped_shell_sessions
    finally:
        case.resume.set()
        for worker in [first, *workers]:
            _join_observed_thread(worker)


def test_cancelling_one_env_scope_preserves_another_scopes_command(paused_env_command):
    case = paused_env_command
    first = _start_observed_thread(case.run, name="first-env")
    second = None
    try:
        assert case.entered.wait(5)
        second = _start_observed_thread(lambda: case.run(owner="second", value="two"), name="second-env")
        _join_observed_thread(second)
        assert second.results == ["done"]
        case.sandbox.request_command_cancel("first")
        case.resume.set()
        _join_observed_thread(first)
        assert "cancelled" in first.results[0]
        assert len(case.executions) == 2
        assert len(case.controls) == 1
        assert not case.sandbox.requires_container_recycle
    finally:
        case.resume.set()
        _join_observed_thread(first)
        if second is not None:
            _join_observed_thread(second)


@pytest.mark.asyncio
async def test_repeated_async_cancellation_drains_scoped_env_cleanup(paused_env_command):
    case = paused_env_command
    task = asyncio.create_task(run_sync_lifecycle_operation(case.run, _on_cancel=lambda: case.sandbox.request_command_cancel("first")))
    try:
        assert await asyncio.to_thread(case.entered.wait, 5)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        assert not task.done()
        assert not case.client_closed.is_set()
        case.resume.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(case.controls) == 1
        assert sum(path.startswith("/v1/bash/sessions/") and path.endswith("/close") for _, path, _ in case.requests) == 1
        assert case.run(owner="second", value="two") == "done"
        assert len(case.executions) == 2
        assert not case.sandbox.requires_container_recycle
    finally:
        case.resume.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("release_count", [1, 2])
def test_releasing_env_scope_stays_visible_to_concurrent_close(paused_env_command, monkeypatch, release_count):
    case = paused_env_command
    first = _start_observed_thread(case.run, name="first-env")
    queued = closing = other = None
    releases = []
    progress = {f"release-{index}": threading.Event() for index in range(release_count)}
    progress["close"] = threading.Event()

    class OverlapLock(_ObservedScopeLock):
        def acquire(self, *args, **kwargs):
            name = threading.current_thread().name
            if name in progress:
                progress[name].set()
            return super().acquire(*args, **kwargs)

    real_client_close = case.http_client.close

    def client_close():
        # On the unfixed path close skips the popped releasing scope, detaches
        # _client, and reaches this callback instead of waiting on its lock.
        progress["close"].set()
        real_client_close()

    monkeypatch.setattr(case.http_client, "close", client_close)
    try:
        assert case.entered.wait(5)
        scoped = case.sandbox._scoped_shell_sessions["first"]
        observed = OverlapLock(scoped.lock)
        scoped.lock = observed
        # A prior no-env call can leave a persistent shell in the same scope.
        scoped.session_id = "retained-shell"
        case.controls.add("retained-shell")
        queued = _start_observed_thread(case.run, name="queued-env")
        assert observed.queued.wait(5)
        for index in range(release_count):
            release = _start_observed_thread(lambda: case.sandbox.release_command_scope("first"), name=f"release-{index}")
            releases.append(release)
            assert progress[f"release-{index}"].wait(5)

        assert case.run() == "Error: sandbox command scope is no longer active"
        other = _start_observed_thread(lambda: case.run(owner="other", value="two"), name="other-env")
        _join_observed_thread(other)
        assert other.results == ["done"], "Releasing one scope must not serialize an independent scope"
        closing = _start_observed_thread(case.sandbox.close, name="close")
        assert progress["close"].wait(5)
        assert case.sandbox._client is not None, "close detached the client while a releasing scope still had an admitted command"
        assert not case.client_closed.is_set()
        assert closing.thread.is_alive()

        case.resume.set()
        for worker in (first, queued, *releases, closing):
            _join_observed_thread(worker)
        assert first.results == ["done"]
        assert queued.results == ["Error: sandbox command scope is no longer active"]
        assert len(case.executions) == 2
        assert sum(method == "DELETE" and path.endswith("/retained-shell") for method, path, _ in case.requests) == 1
        assert sum(path.endswith("/close") for _, path, _ in case.requests) == 2
        assert not case.sandbox._scoped_shell_sessions
        assert case.client_closed.is_set()
    finally:
        case.resume.set()
        for worker in (first, queued, other, *releases, closing):
            if worker is not None:
                _join_observed_thread(worker)
