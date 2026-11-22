"""Bash admission includes creation, execution and cleanup, independently of PTYs."""

import threading
from types import SimpleNamespace

import httpx
import pytest
from test_aio_scoped_env_concurrency import (
    _join_observed_thread,
    _ObservedScopeLock,
    _start_observed_thread,
)
from test_aio_scoped_env_concurrency import (
    paused_env_command as _paused_env_command,
)

paused_env_command = _paused_env_command


@pytest.mark.parametrize("paused_env_command", [1], indirect=True)
@pytest.mark.parametrize("cancel", [False, True])
@pytest.mark.parametrize("direct", [False, True])
def test_bash_capacity_waiter_is_cancellable_and_wakes_after_cleanup(paused_env_command, monkeypatch, cancel, direct):
    from deerflow.sandbox.command_scope import CommandScopeCancelled, command_owner

    case = paused_env_command
    slots = _ObservedScopeLock(case.sandbox._bash_slots)
    case.sandbox._bash_slots = slots
    original = case.http_client._transport.handle_request
    cleanup_entered = threading.Event()
    cleanup_resume = threading.Event()
    live_sessions = set()

    def transport(request):
        path = request.url.path
        if path == "/v1/bash/sessions/create":
            assert not live_sessions, "Client exceeded the one-slot Bash pool"
            live_sessions.add("active")
        if path.startswith("/v1/bash/sessions/") and path.endswith("/close"):
            cleanup_entered.set()
            assert cleanup_resume.wait(5)
            live_sessions.clear()
        return original(request)

    monkeypatch.setattr(case.http_client._transport, "handle_request", transport)

    def run_second():
        if direct:
            with command_owner(case.sandbox, "second"):
                if cancel:
                    with pytest.raises(CommandScopeCancelled, match="cancelled"):
                        case.sandbox.execute_command("ordinary-command", env={"REQUEST_VALUE": "two"})
                    return "cancelled"
                return case.sandbox.execute_command("ordinary-command", env={"REQUEST_VALUE": "two"})
        return case.run(owner="second", value="two")

    first = _start_observed_thread(case.run, name="first-env")
    queued = None
    try:
        assert case.entered.wait(5)
        queued = _start_observed_thread(run_second, name="queued-env")
        assert slots.queued.wait(5)
        assert len(case.executions) == 1
        if cancel:
            case.sandbox.request_command_cancel("second")
            _join_observed_thread(queued)
            assert "cancelled" in queued.results[0]
        case.resume.set()
        assert cleanup_entered.wait(5)
        assert len(case.executions) == 1, "A permit must cover session cleanup"
        cleanup_resume.set()
        _join_observed_thread(first)
        _join_observed_thread(queued)
        assert first.results == ["done"]
        if not cancel:
            assert queued.results == ["done"]
            assert len(case.executions) == 2
        assert case.run(owner="third") == "done", "Cancellation must not leak a permit"
        assert not live_sessions
    finally:
        case.resume.set()
        cleanup_resume.set()
        for worker in (first, queued):
            if worker is not None:
                _join_observed_thread(worker)


@pytest.mark.parametrize("capacity", [0, -1, True, 1.5, "2"])
def test_invalid_bash_capacity_rejected_before_client_creation(capacity):
    from deerflow.community.aio_sandbox.aio_sandbox import AioSandbox

    with pytest.raises(ValueError, match="max_bash_sessions"):
        AioSandbox("invalid", "http://sandbox.invalid", max_bash_sessions=capacity)


@pytest.mark.parametrize("configured,expected", [(None, 50), ("1", 1), ("72", 72)])
def test_provider_configures_bash_budget_independently_of_shell(monkeypatch, configured, expected):
    from deerflow.community.aio_sandbox import aio_sandbox_provider as module
    from deerflow.config.sandbox_config import SandboxConfig

    config = SimpleNamespace(
        sandbox=SandboxConfig(use="deerflow.community.aio_sandbox:AioSandboxProvider", environment={} if configured is None else {"AIO_BASH_MAX_SESSIONS": configured}),
        subagent_runtime=SimpleNamespace(max_running=64),
        stream_bridge=None,
    )
    monkeypatch.setattr(module, "get_app_config", lambda: config)
    provider = module.AioSandboxProvider.__new__(module.AioSandboxProvider)
    loaded = provider._load_config()
    assert loaded["max_bash_sessions"] == expected
    assert loaded["environment"]["AIO_BASH_MAX_SESSIONS"] == str(expected)
    assert loaded["max_shell_sessions"] == 65


@pytest.mark.parametrize("configured", ["0", "-1", "1.5", "invalid"])
def test_provider_rejects_invalid_bash_budget(monkeypatch, configured):
    from deerflow.community.aio_sandbox import aio_sandbox_provider as module
    from deerflow.config.sandbox_config import SandboxConfig

    monkeypatch.setattr(module, "get_app_config", lambda: SimpleNamespace(sandbox=SandboxConfig(use="test", environment={"AIO_BASH_MAX_SESSIONS": configured})))
    with pytest.raises(ValueError, match="AIO_BASH_MAX_SESSIONS"):
        module.AioSandboxProvider.__new__(module.AioSandboxProvider)._load_config()


@pytest.mark.parametrize("actual,compatible", [("1", False), ("50", True), ("72", True), ("invalid", False), ("0", False), (None, True)])
def test_local_reuse_validates_persisted_bash_budget(actual, compatible):
    from deerflow.community.aio_sandbox.local_backend import LocalContainerBackend, _parse_bash_capacity

    backend = LocalContainerBackend.__new__(LocalContainerBackend)
    backend._environment = {"AIO_BASH_MAX_SESSIONS": "50"}
    backend._required_shell_sessions = 1
    inspection = SimpleNamespace(max_shell_sessions=10, max_bash_sessions=_parse_bash_capacity({"Env": [] if actual is None else [f"AIO_BASH_MAX_SESSIONS={actual}"]}))
    assert backend._has_compatible_shell_capacity(inspection) is compatible


@pytest.mark.parametrize("actual", [None, "50", 0, -1, True])
def test_remote_unknown_capacity_is_not_assumed_or_replaced(actual):
    from deerflow.community.aio_sandbox.remote_backend import RemoteSandboxBackend

    backend = RemoteSandboxBackend("http://provisioner", max_bash_sessions=50)
    with pytest.raises(RuntimeError, match="max_bash_sessions"):
        backend._sandbox_info({"sandbox_url": "http://sandbox", "max_bash_sessions": actual}, "test")


@pytest.mark.parametrize("actual,replacement", [(1, True), (50, False), (72, False)])
def test_remote_reuse_validates_attested_bash_budget(actual, replacement):
    from deerflow.community.aio_sandbox.remote_backend import RemoteSandboxBackend

    backend = RemoteSandboxBackend("http://provisioner", max_bash_sessions=50)
    assert backend._sandbox_info({"sandbox_url": "http://sandbox", "max_bash_sessions": actual}, "test").requires_replacement is replacement


@pytest.mark.parametrize("paused_env_command", [1], indirect=True)
@pytest.mark.parametrize("teardown", ["close", "release"])
def test_capacity_waiter_rechecks_teardown_before_creation(paused_env_command, teardown):
    case = paused_env_command
    slots = _ObservedScopeLock(case.sandbox._bash_slots)
    case.sandbox._bash_slots = slots
    first = _start_observed_thread(case.run, name="first-env")
    queued = stopping = None
    try:
        assert case.entered.wait(5)
        queued = _start_observed_thread(lambda: case.run(owner="second"), name="queued-env")
        assert slots.queued.wait(5)
        scope = case.sandbox._scoped_shell_sessions["first" if teardown == "close" else "second"]
        observed = _ObservedScopeLock(scope.lock)
        scope.lock = observed
        action = case.sandbox.close if teardown == "close" else lambda: case.sandbox.release_command_scope("second")
        stopping = _start_observed_thread(action, name="scope-teardown")
        assert observed.teardown.wait(5)
        case.resume.set()
        for worker in (first, queued, stopping):
            _join_observed_thread(worker)
        assert "no longer active" in queued.results[0]
        assert len(case.executions) == 1
    finally:
        case.resume.set()
        for worker in (first, queued, stopping):
            if worker is not None:
                _join_observed_thread(worker)


@pytest.mark.parametrize("paused_env_command", [1], indirect=True)
@pytest.mark.parametrize("failed_path", ["/v1/bash/sessions/create", "/v1/bash/exec"])
def test_failed_bash_request_returns_capacity(paused_env_command, monkeypatch, failed_path):
    case = paused_env_command
    original = case.http_client._transport.handle_request
    rejected = False

    def transport(request):
        nonlocal rejected
        if request.url.path == failed_path and not rejected:
            rejected = True
            return httpx.Response(400, json={"message": "Invalid request"})
        return original(request)

    monkeypatch.setattr(case.http_client._transport, "handle_request", transport)
    case.resume.set()
    assert "400" in case.run()
    assert case.run(owner="second") == "done"


@pytest.mark.parametrize("reported", [1, 50, None])
def test_remote_create_transmits_and_verifies_bash_budget(monkeypatch, reported):
    from deerflow.community.aio_sandbox import remote_backend as module
    from deerflow.community.aio_sandbox.backend import SandboxCreationError

    backend = module.RemoteSandboxBackend("http://provisioner", max_bash_sessions=50)
    monkeypatch.setattr(module, "user_should_see_legacy_skills", lambda _user: False)
    requests = []

    def post(url, **kwargs):
        requests.append(kwargs["json"])
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"sandbox_url": "http://sandbox", "max_bash_sessions": reported, "container_id": "pod-uid"})

    monkeypatch.setattr(module.requests, "post", post)
    if reported == 50:
        assert backend._provisioner_create("thread", "sandbox").container_id == "pod-uid"
    else:
        with pytest.raises(SandboxCreationError) as error:
            backend._provisioner_create("thread", "sandbox")
        assert error.value.info.container_id == "pod-uid"
    assert requests[0]["max_bash_sessions"] == 50
