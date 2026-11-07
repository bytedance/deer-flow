"""Port reservations follow whether a local sandbox may have been started."""

import errno
import subprocess
from types import SimpleNamespace

import pytest

from deerflow.community.aio_sandbox import local_backend
from deerflow.utils import network

BASE_PORT = 38080


def make_backend(monkeypatch, runtime="docker", *, restricted=False):
    allocator = network.PortAllocator()
    # Exercise real allocation/release bookkeeping without binding host sockets.
    monkeypatch.setattr(
        allocator,
        "_is_port_available",
        lambda port: port not in allocator._reserved_ports,
    )
    monkeypatch.setattr(network, "_global_port_allocator", allocator)
    monkeypatch.setattr(local_backend.LocalContainerBackend, "_detect_runtime", lambda self: runtime)
    monkeypatch.setattr(local_backend, "_resolve_docker_bind_host", lambda: "127.0.0.1")
    monkeypatch.setenv("DEER_FLOW_SANDBOX_HOST", "localhost")
    monkeypatch.delenv("DEER_FLOW_SANDBOX_NETWORK", raising=False)
    if restricted:
        monkeypatch.setattr(
            local_backend.LocalContainerBackend,
            "_require_restricted_network_support",
            lambda self: None,
        )
        monkeypatch.setattr(
            local_backend.LocalContainerBackend,
            "_docker_server_is_desktop",
            lambda self: False,
        )
    backend = local_backend.LocalContainerBackend(
        image="offline-sandbox:unused",
        base_port=BASE_PORT,
        container_prefix="offline-sandbox",
        config_mounts=[],
        environment={},
        network_config={"mode": "allowlist" if restricted else "open"},
    )
    return backend, allocator


def published_port(cmd):
    return int(cmd[cmd.index("-p") + 1].split(":")[-2])


def assert_port_reserved(allocator):
    with pytest.raises(RuntimeError, match="No available port"):
        allocator.allocate(BASE_PORT, max_range=1)


@pytest.mark.parametrize("runtime", ["docker", "container"])
@pytest.mark.parametrize("error_type", [FileNotFoundError, PermissionError])
def test_unstarted_cli_releases_port_for_repeated_create_attempts(monkeypatch, runtime, error_type):
    backend, allocator = make_backend(monkeypatch, runtime)
    attempted_ports = []
    error = error_type("container executable could not start")

    def fail_spawn(cmd, **kwargs):
        assert cmd[:2] == [runtime, "run"]
        attempted_ports.append(published_port(cmd))
        raise error

    monkeypatch.setattr(local_backend.subprocess, "run", fail_spawn)
    for attempt in range(3):
        with pytest.raises(error_type) as raised:
            backend.create("thread", f"sandbox-{attempt}")
        assert raised.value is error

    assert attempted_ports == [BASE_PORT] * 3
    # Recovery can reuse the original port rather than consuming the range.
    assert allocator.allocate(BASE_PORT, max_range=1) == BASE_PORT


@pytest.mark.parametrize("runtime", ["docker", "container"])
@pytest.mark.parametrize("error_type", [FileNotFoundError, PermissionError])
def test_failed_create_does_not_release_a_successors_port(monkeypatch, runtime, error_type):
    backend, allocator = make_backend(monkeypatch, runtime)
    error = error_type("first executable could not start")
    attempted_ports = []
    released_ports = []
    successor_infos = []
    release_port = local_backend.release_port

    def run(cmd, **kwargs):
        assert cmd[:2] == [runtime, "run"]
        name = cmd[cmd.index("--name") + 1]
        attempted_ports.append((name, published_port(cmd)))
        if name == "offline-sandbox-first":
            raise error
        assert name == "offline-sandbox-successor"
        return SimpleNamespace(stdout="successor-container\n")

    def release_and_reassign(port):
        released_ports.append(port)
        release_port(port)
        if not successor_infos:
            # Interleave a real successful create after release but before the
            # failed create unwinds. A second release would free its new owner.
            successor_infos.append(backend.create("successor-thread", "successor"))

    monkeypatch.setattr(local_backend.subprocess, "run", run)
    monkeypatch.setattr(local_backend, "release_port", release_and_reassign)
    with pytest.raises(error_type) as raised:
        backend.create("first-thread", "first")

    assert raised.value is error
    assert attempted_ports == [
        ("offline-sandbox-first", BASE_PORT),
        ("offline-sandbox-successor", BASE_PORT),
    ]
    assert released_ports == [BASE_PORT]
    assert successor_infos[0].container_id == "successor-container"
    assert_port_reserved(allocator)


@pytest.mark.parametrize("runtime", ["docker", "container"])
def test_successful_create_keeps_its_port_reserved(monkeypatch, runtime):
    backend, allocator = make_backend(monkeypatch, runtime)

    def started(cmd, **kwargs):
        assert cmd[:2] == [runtime, "run"]
        assert published_port(cmd) == BASE_PORT
        return SimpleNamespace(stdout="started-container\n")

    monkeypatch.setattr(local_backend.subprocess, "run", started)
    info = backend.create("thread", "sandbox")

    assert info.container_id == "started-container"
    assert info.sandbox_url == f"http://localhost:{BASE_PORT}"
    assert_port_reserved(allocator)


@pytest.mark.parametrize("runtime", ["docker", "container"])
def test_rejected_run_keeps_existing_error_and_port_release(monkeypatch, runtime):
    backend, allocator = make_backend(monkeypatch, runtime)

    def rejected(cmd, **kwargs):
        assert cmd[:2] == [runtime, "run"]
        raise subprocess.CalledProcessError(1, cmd, stderr="daemon rejected start")

    monkeypatch.setattr(local_backend.subprocess, "run", rejected)
    with pytest.raises(RuntimeError, match="Failed to start sandbox container: daemon rejected start"):
        backend.create("thread", "sandbox")

    assert allocator.allocate(BASE_PORT, max_range=1) == BASE_PORT


@pytest.mark.parametrize("runtime", ["docker", "container"])
def test_uncertain_run_timeout_keeps_port_reserved(monkeypatch, runtime):
    backend, allocator = make_backend(monkeypatch, runtime)

    def timed_out(cmd, **kwargs):
        assert cmd[:2] == [runtime, "run"]
        raise subprocess.TimeoutExpired(cmd, timeout=1)

    monkeypatch.setattr(local_backend.subprocess, "run", timed_out)
    with pytest.raises(subprocess.TimeoutExpired):
        backend.create("thread", "sandbox")

    assert_port_reserved(allocator)


@pytest.mark.parametrize("runtime", ["docker", "container"])
def test_unknown_run_io_error_keeps_port_reserved(monkeypatch, runtime):
    backend, allocator = make_backend(monkeypatch, runtime)
    error = OSError(errno.EIO, "cannot confirm the run outcome")

    def failed_io(cmd, **kwargs):
        assert cmd[:2] == [runtime, "run"]
        raise error

    monkeypatch.setattr(local_backend.subprocess, "run", failed_io)
    with pytest.raises(OSError) as raised:
        backend.create("thread", "sandbox")

    assert raised.value is error
    assert_port_reserved(allocator)


@pytest.mark.parametrize("runtime", ["docker", "container"])
def test_post_start_logging_failure_keeps_port_reserved(monkeypatch, runtime):
    backend, allocator = make_backend(monkeypatch, runtime)
    started = []

    def successful_run(cmd, **kwargs):
        assert cmd[:2] == [runtime, "run"]
        started.append(published_port(cmd))
        return SimpleNamespace(stdout="started-container\n")

    def failing_log(message, *args, **kwargs):
        if message.startswith("Started container "):
            raise PermissionError("log sink became unwritable")

    monkeypatch.setattr(local_backend.subprocess, "run", successful_run)
    monkeypatch.setattr(local_backend.logger, "info", failing_log)
    with pytest.raises(PermissionError, match="log sink became unwritable"):
        backend.create("thread", "sandbox")

    assert started == [BASE_PORT]
    assert_port_reserved(allocator)


@pytest.mark.parametrize("error_type", [FileNotFoundError, PermissionError])
def test_restricted_spawn_failure_keeps_port_when_proxy_cleanup_is_uncertain(monkeypatch, error_type):
    backend, allocator = make_backend(monkeypatch, restricted=True)
    events = []
    monkeypatch.setattr(backend, "_restricted_resources_status", lambda sandbox_id: "missing")
    monkeypatch.setattr(backend, "_create_internal_network", lambda *args: None)
    monkeypatch.setattr(backend, "_create_egress_network", lambda *args: None)
    monkeypatch.setattr(backend, "_start_network_proxy", lambda *args: events.append("proxy started"))

    def fail_spawn(cmd, **kwargs):
        assert cmd[:2] == ["docker", "run"]
        events.append("sandbox spawn failed")
        raise error_type("sandbox executable could not start")

    def uncertain_cleanup(sandbox_id):
        events.append("cleanup unconfirmed")
        raise error_type("cannot confirm whether proxy stopped")

    monkeypatch.setattr(local_backend.subprocess, "run", fail_spawn)
    monkeypatch.setattr(backend, "_cleanup_restricted_resources", uncertain_cleanup)
    with pytest.raises(error_type):
        backend.create("thread", "sandbox")

    assert events == ["proxy started", "sandbox spawn failed", "cleanup unconfirmed"]
    assert_port_reserved(allocator)
