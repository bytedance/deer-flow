"""Restricted creation releases only reservations whose proxy is known absent.

Docker CLI responses and readiness HTTP are offline. Creation, rollback, discovery,
cleanup and PortAllocator remain real. Ownership assertions use recorded allocation
and release events, so another process occupying the requested base port is harmless.
"""

import json
import logging
import socket
import subprocess
from dataclasses import dataclass, field
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest

from deerflow.community.aio_sandbox import backend as sandbox_backend
from deerflow.community.aio_sandbox import local_backend
from deerflow.utils import network


@dataclass
class DockerCLI:
    start_error: BaseException | None
    proxy_create_error: BaseException | None = None
    fail_proxy_stop: bool = False
    fail_network_remove: bool = False
    inspect_error: BaseException | None = None
    containers: dict = field(default_factory=dict)
    networks: dict = field(default_factory=dict)
    calls: list = field(default_factory=list)
    proxy_names: list = field(default_factory=list)
    published_ports: list = field(default_factory=list)

    @staticmethod
    def _options(cmd, flag):
        return [cmd[index + 1] for index, value in enumerate(cmd) if value == flag]

    @staticmethod
    def _response(cmd, kwargs, *, stdout="", stderr="", returncode=0):
        if kwargs.get("check") and returncode:
            raise subprocess.CalledProcessError(returncode, cmd, output=stdout, stderr=stderr)
        return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)

    def record_main_container(self, cmd):
        name = cmd[cmd.index("--name") + 1]
        entry = {
            "Name": f"/{name}",
            "Id": f"generation-{name}",
            "State": {"Running": True},
            "Config": {
                "Labels": dict(item.split("=", 1) for item in self._options(cmd, "--label")),
                "Env": self._options(cmd, "-e"),
                "Image": cmd[-1],
            },
            "HostConfig": {"PortBindings": {}},
            "NetworkSettings": {
                "Networks": {cmd[cmd.index("--network") + 1]: {}},
                "Ports": {},
            },
        }
        self.containers[name] = entry
        return entry

    def run(self, cmd, **kwargs):
        self.calls.append(tuple(cmd))
        assert cmd[0] == "docker", cmd
        if cmd[1] == "inspect":
            if self.inspect_error is not None:
                raise self.inspect_error
            if cmd[2:4] == ["-f", "{{.State.Running}}"]:
                entry = self.containers.get(cmd[-1])
                return self._response(
                    cmd,
                    kwargs,
                    stdout=str(entry["State"]["Running"]).lower() if entry else "",
                    stderr="" if entry else f"Error: No such container: {cmd[-1]}",
                    returncode=0 if entry else 1,
                )
            names = cmd[2:]
            found = [self.containers[name] for name in names if name in self.containers]
            missing = [f"Error: No such object: {name}" for name in names if name not in self.containers]
            return self._response(
                cmd,
                kwargs,
                stdout=json.dumps(found),
                stderr="\n".join(missing),
                returncode=int(bool(missing)),
            )
        if cmd[1:3] == ["network", "inspect"]:
            name = cmd[-1]
            if name in self.networks:
                return self._response(cmd, kwargs, stdout=json.dumps([self.networks[name]]))
            return self._response(
                cmd,
                kwargs,
                stdout="[]",
                stderr=f"Error: No such network: {name}",
                returncode=1,
            )
        if cmd[1:3] == ["network", "create"]:
            self.networks[cmd[-1]] = {
                "Driver": "bridge",
                "Internal": "--internal" in cmd,
                "Labels": dict(item.split("=", 1) for item in self._options(cmd, "--label")),
                "Options": dict(item.split("=", 1) for item in self._options(cmd, "--opt")),
            }
            return self._response(cmd, kwargs, stdout="network-id\n")
        if cmd[1] == "create":
            if self.proxy_create_error is not None:
                raise self.proxy_create_error
            name = cmd[cmd.index("--name") + 1]
            port = int(cmd[cmd.index("-p") + 1].split(":")[-2])
            self.proxy_names.append(name)
            self.published_ports.append(port)
            self.containers[name] = {
                "Name": f"/{name}",
                "Id": f"generation-{name}",
                "State": {"Running": False},
                "Config": {
                    "Labels": dict(item.split("=", 1) for item in self._options(cmd, "--label")),
                    "Env": self._options(cmd, "-e"),
                    "Image": cmd[-4],
                },
                "HostConfig": {"PortBindings": {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(port)}]}},
                "NetworkSettings": {
                    "Networks": {cmd[cmd.index("--network") + 1]: {}},
                    "Ports": {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(port)}]},
                },
            }
            return self._response(cmd, kwargs, stdout=f"generation-{name}\n")
        if cmd[1:3] == ["network", "connect"]:
            self.containers[cmd[-1]]["NetworkSettings"]["Networks"][cmd[-2]] = {}
            return self._response(cmd, kwargs)
        if cmd[1] == "start":
            self.containers[cmd[-1]]["State"]["Running"] = True
            return self._response(cmd, kwargs, stdout=f"{cmd[-1]}\n")
        if cmd[1] == "exec":
            assert cmd[2] == "-i" and cmd[3] in self.containers
            assert kwargs.get("input"), "Proxy installation must use its actual script bytes"
            return self._response(cmd, kwargs, stdout=b"", stderr=b"")
        if cmd[1] == "run":
            assert "-p" not in cmd, "Only the proxy publishes the host port"
            if self.start_error is not None:
                raise self.start_error
            entry = self.record_main_container(cmd)
            return self._response(cmd, kwargs, stdout=f"{entry['Id']}\n")
        if cmd[1] == "stop":
            target = cmd[-1]
            name = next(
                (name for name, entry in self.containers.items() if entry["Id"] == target),
                target,
            )
            if name in self.proxy_names and self.fail_proxy_stop:
                return self._response(cmd, kwargs, stderr="daemon denied proxy stop", returncode=1)
            if self.containers.pop(name, None) is None:
                return self._response(
                    cmd,
                    kwargs,
                    stderr=f"Error: No such container: {name}",
                    returncode=1,
                )
            return self._response(cmd, kwargs, stdout=f"{name}\n")
        if cmd[1:3] == ["rm", "-f"]:
            name = cmd[-1]
            if self.containers.pop(name, None) is None:
                return self._response(
                    cmd,
                    kwargs,
                    stderr=f"Error: No such container: {name}",
                    returncode=1,
                )
            return self._response(cmd, kwargs, stdout=f"{name}\n")
        if cmd[1:3] == ["network", "rm"]:
            if self.fail_network_remove:
                raise subprocess.TimeoutExpired(cmd, timeout=15)
            name = cmd[-1]
            if any(name in entry["NetworkSettings"]["Networks"] for entry in self.containers.values()):
                return self._response(cmd, kwargs, stderr="network has active endpoints", returncode=1)
            if self.networks.pop(name, None) is None:
                return self._response(cmd, kwargs, stderr=f"Error: No such network: {name}", returncode=1)
            return self._response(cmd, kwargs, stdout=f"{name}\n")
        raise AssertionError(f"Unexpected Docker command: {cmd!r}")


@dataclass
class PortHistory:
    allocated: list[int] = field(default_factory=list)
    released: list[int] = field(default_factory=list)


@pytest.fixture(params=[False, True], ids=["available-base", "occupied-base"])
def restricted_backend(monkeypatch, request):
    """Record real allocations; also exercise a base port occupied by a socket."""
    occupied = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    occupied.bind(("0.0.0.0", 0))
    base_port = occupied.getsockname()[1]
    if not request.param:
        occupied.close()
    allocator = network.PortAllocator()
    history = PortHistory()
    allocate, release = allocator.allocate, allocator.release

    def record_allocation(*args, **kwargs):
        port = allocate(*args, **kwargs)
        history.allocated.append(port)
        if request.param:
            assert port != base_port
        return port

    def record_release(port):
        history.released.append(port)
        release(port)

    monkeypatch.setattr(allocator, "allocate", record_allocation)
    monkeypatch.setattr(allocator, "release", record_release)
    monkeypatch.setattr(network, "_global_port_allocator", allocator)
    monkeypatch.setattr(local_backend.LocalContainerBackend, "_detect_runtime", lambda self: "docker")
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
    monkeypatch.setattr(local_backend, "_resolve_docker_bind_host", lambda: "127.0.0.1")
    monkeypatch.setenv("DEER_FLOW_SANDBOX_HOST", "localhost")
    monkeypatch.delenv("DEER_FLOW_SANDBOX_NETWORK", raising=False)
    backend = local_backend.LocalContainerBackend(
        image="offline-sandbox:unused",
        base_port=base_port,
        container_prefix="offline-restricted",
        config_mounts=[],
        environment={},
        network_config={"mode": "allowlist"},
    )

    def scenario(start_error, **options):
        docker = DockerCLI(start_error, **options)
        monkeypatch.setattr(local_backend.subprocess, "run", docker.run)
        return backend, allocator, history, docker

    try:
        yield scenario
    finally:
        occupied.close()


def assert_reserved(allocator, *ports):
    assert set(ports) <= allocator._reserved_ports


def assert_released_once(allocator, history, port):
    assert port not in allocator._reserved_ports
    assert history.released.count(port) == 1


def rejected_start(message="daemon rejected sandbox start"):
    return subprocess.CalledProcessError(1, ["docker", "run"], stderr=message)


def allow_readiness_http(monkeypatch):
    requests = []

    def healthy_response(session, url, **kwargs):
        requests.append(url)
        return SimpleNamespace(status_code=200)

    monkeypatch.setattr(sandbox_backend.requests.Session, "get", healthy_response)
    return requests


def test_runtime_error_with_failed_proxy_cleanup_preserves_port(restricted_backend):
    backend, allocator, history, docker = restricted_backend(rejected_start(), fail_proxy_stop=True)
    with pytest.raises(RuntimeError, match="daemon rejected sandbox start"):
        backend.create("thread", "sandbox")
    assert docker.published_ports == history.allocated
    assert docker.proxy_names[0] in docker.containers
    assert_reserved(allocator, history.allocated[0])
    assert history.released == []


@pytest.mark.parametrize("error_type", [FileNotFoundError, PermissionError])
def test_unstarted_main_cli_releases_port_after_proxy_is_removed(restricted_backend, error_type):
    original = error_type("sandbox executable cannot start")
    backend, allocator, history, docker = restricted_backend(original)
    with pytest.raises(error_type) as caught:
        backend.create("thread", "sandbox")
    assert caught.value is original
    assert docker.published_ports == history.allocated
    assert docker.proxy_names[0] not in docker.containers
    assert_released_once(allocator, history, history.allocated[0])


def test_network_cleanup_timeout_releases_proxy_port_and_preserves_start_error(restricted_backend, caplog):
    original = FileNotFoundError("sandbox executable cannot start")
    backend, allocator, history, docker = restricted_backend(original, fail_network_remove=True)
    with (
        caplog.at_level(logging.WARNING, logger=local_backend.__name__),
        pytest.raises(FileNotFoundError) as caught,
    ):
        backend.create("thread", "sandbox")
    assert caught.value is original
    assert docker.proxy_names[0] not in docker.containers
    assert any(cmd[:3] == ("docker", "network", "rm") for cmd in docker.calls)
    warnings = [record for record in caplog.records if record.name == local_backend.__name__ and record.levelno >= logging.WARNING]
    assert any("rollback" in record.getMessage().lower() and "sandbox" in record.getMessage() and record.exc_info is not None for record in warnings)
    assert_released_once(allocator, history, history.allocated[0])


def test_preflight_failure_releases_port_before_any_proxy_attempt(restricted_backend):
    original = FileNotFoundError("runtime unavailable during preflight")
    backend, allocator, history, docker = restricted_backend(rejected_start(), inspect_error=original)
    with pytest.raises(RuntimeError, match="Failed to inspect containers") as caught:
        backend.create("thread", "sandbox")
    assert caught.value.__cause__ is original
    assert docker.published_ports == []
    assert all(cmd[:2] != ("docker", "create") for cmd in docker.calls)
    assert_released_once(allocator, history, history.allocated[0])


def test_uncertain_proxy_cleanup_does_not_retry_port_collision(restricted_backend):
    backend, allocator, history, docker = restricted_backend(rejected_start("address already in use"), fail_proxy_stop=True)
    with pytest.raises(RuntimeError, match="address already in use"):
        backend.create("thread", "sandbox")
    assert len(history.allocated) == 1
    assert docker.published_ports == history.allocated
    assert_reserved(allocator, history.allocated[0])
    assert history.released == []


def test_confirmed_absence_releases_failed_creation_port_once(restricted_backend):
    original = FileNotFoundError("sandbox executable cannot start")
    backend, allocator, history, docker = restricted_backend(original, fail_proxy_stop=True)
    with pytest.raises(FileNotFoundError) as caught:
        backend.create("thread", "sandbox")
    assert caught.value is original
    port = history.allocated[0]
    assert_reserved(allocator, port)

    # The caller supplies the provider's teardown fences and authoritative
    # absence proof; cleanup must also remove the proxy/network leftovers.
    docker.fail_proxy_stop = False
    assert backend.is_absent("sandbox") is True
    backend.complete_absent_teardown("sandbox")
    assert docker.containers == {}
    assert_released_once(allocator, history, port)
    backend.complete_absent_teardown("sandbox")
    assert_released_once(allocator, history, port)


@pytest.mark.parametrize("error_type", [FileNotFoundError, PermissionError])
def test_proxy_cli_spawn_failure_returns_its_unused_port(restricted_backend, error_type):
    original = error_type("proxy executable cannot start")
    backend, allocator, history, docker = restricted_backend(rejected_start(), proxy_create_error=original)
    with pytest.raises(error_type) as caught:
        backend.create("thread", "sandbox")
    assert caught.value is original
    assert any(cmd[:2] == ("docker", "create") for cmd in docker.calls)
    assert docker.containers == {}
    assert_released_once(allocator, history, history.allocated[0])


def test_same_id_create_does_not_reclaim_an_earlier_uncertain_reservation(
    restricted_backend,
):
    backend, allocator, history, docker = restricted_backend(rejected_start(), fail_proxy_stop=True)
    with pytest.raises(RuntimeError, match="daemon rejected sandbox start"):
        backend.create("thread", "sandbox")
    old_port = history.allocated[0]

    # External removal is not the provider's fenced absence-cleanup path.
    # A later create must not silently reclaim the earlier reservation.
    docker.containers.clear()
    docker.networks.clear()
    docker.fail_proxy_stop = False
    docker.start_error = None
    replacement = backend.create("thread", "sandbox")
    replacement_port = urlparse(replacement.sandbox_url).port
    assert replacement_port != old_port
    assert_reserved(allocator, old_port, replacement_port)
    assert history.released == []

    backend.destroy(replacement)
    assert_released_once(allocator, history, replacement_port)
    assert_reserved(allocator, old_port)
    assert backend.is_absent("sandbox") is True
    backend.complete_absent_teardown("sandbox")
    assert_released_once(allocator, history, old_port)


def test_first_failure_probe_cannot_release_a_successors_reservation(restricted_backend, monkeypatch):
    backend, allocator, history, docker = restricted_backend(rejected_start(), fail_proxy_stop=True)
    successors = []
    interleaved = False

    def first_probe_then_transfer(cmd, **kwargs):
        nonlocal interleaved
        if not interleaved and docker.proxy_names and cmd == ["docker", "inspect", docker.proxy_names[0]]:
            interleaved = True
            # Keep a stale absence result while a fenced cleanup retires the
            # original reservation and a new create obtains its own port.
            del docker.containers[docker.proxy_names[0]]
            response = docker.run(cmd, **kwargs)
            docker.fail_proxy_stop = False
            assert backend.is_absent("sandbox") is True
            backend.complete_absent_teardown("sandbox")
            docker.start_error = None
            successors.append(backend.create("successor-thread", "successor"))
            return response
        return docker.run(cmd, **kwargs)

    monkeypatch.setattr(local_backend.subprocess, "run", first_probe_then_transfer)
    with pytest.raises(RuntimeError, match="daemon rejected sandbox start"):
        backend.create("thread", "sandbox")
    assert interleaved
    assert len(history.allocated) == 2
    assert history.released == history.allocated[:1]
    successor_port = urlparse(successors[0].sandbox_url).port
    assert allocator._reserved_ports == {successor_port}


class CleanupInterrupted(BaseException):
    """Model a lifecycle interruption without stopping the pytest session."""


@pytest.mark.parametrize("interrupted_stage", ["rollback", "settlement"])
def test_cleanup_interruption_keeps_the_reservation_recoverable(restricted_backend, monkeypatch, interrupted_stage):
    backend, allocator, history, docker = restricted_backend(rejected_start(), fail_proxy_stop=True)
    interruption = CleanupInterrupted("cleanup interrupted")
    interrupted = False

    def interrupt_cleanup(cmd, **kwargs):
        nonlocal interrupted
        is_rollback = cmd[1] == "stop"
        is_settlement = docker.proxy_names and cmd == [
            "docker",
            "inspect",
            docker.proxy_names[0],
        ]
        if not interrupted and ((interrupted_stage == "rollback" and is_rollback) or (interrupted_stage == "settlement" and is_settlement)):
            interrupted = True
            raise interruption
        return docker.run(cmd, **kwargs)

    monkeypatch.setattr(local_backend.subprocess, "run", interrupt_cleanup)
    with pytest.raises(CleanupInterrupted) as caught:
        backend.create("thread", "sandbox")
    assert caught.value is interruption
    port = history.allocated[0]
    assert_reserved(allocator, port)
    docker.fail_proxy_stop = False
    assert backend.is_absent("sandbox") is True
    backend.complete_absent_teardown("sandbox")
    assert_released_once(allocator, history, port)


def test_destroying_discovered_failed_creation_clears_its_reservation(restricted_backend, monkeypatch):
    backend, allocator, history, docker = restricted_backend(rejected_start(), fail_proxy_stop=True)
    with pytest.raises(RuntimeError, match="daemon rejected sandbox start"):
        backend.create("thread", "sandbox")
    port = history.allocated[0]
    main_command = list(next(cmd for cmd in docker.calls if cmd[:2] == ("docker", "run")))
    docker.record_main_container(main_command)
    readiness_requests = allow_readiness_http(monkeypatch)
    info = backend.discover("sandbox")
    assert info is not None and not info.requires_replacement
    assert readiness_requests == [f"http://localhost:{port}/v1/sandbox"]
    docker.fail_proxy_stop = False
    backend.destroy(info)
    assert docker.containers == {}
    assert_released_once(allocator, history, port)
    backend.complete_absent_teardown("sandbox")
    assert_released_once(allocator, history, port)


@pytest.mark.parametrize("conflict_stage", ["proxy", "main"])
@pytest.mark.parametrize("inspection_fails", [False, True])
def test_name_conflict_only_retains_a_port_from_this_attempts_proxy(restricted_backend, monkeypatch, caplog, conflict_stage, inspection_fails):
    conflict = 'Conflict. The container name is already in use by container "peer"'
    backend, allocator, history, docker = restricted_backend(rejected_start(conflict))
    peer_ports = []

    def conflicting_runtime(cmd, **kwargs):
        if conflict_stage == "proxy" and cmd[1] == "create":
            docker.run(cmd, **kwargs)
            name = cmd[cmd.index("--name") + 1]
            peer_port = allocator.allocate(history.allocated[0] + 1)
            peer_ports.append(peer_port)
            entry = docker.containers[name]
            for bindings in (
                entry["HostConfig"]["PortBindings"],
                entry["NetworkSettings"]["Ports"],
            ):
                bindings["8080/tcp"][0]["HostPort"] = str(peer_port)
            if inspection_fails:
                docker.inspect_error = PermissionError("daemon unavailable after conflict")
            return docker._response(cmd, kwargs, stderr=conflict, returncode=1)
        if conflict_stage == "main" and cmd[1] == "run":
            entry = docker.record_main_container(cmd)
            entry["Config"]["Labels"]["deerflow.sandbox_id"] = "peer"
            if inspection_fails:
                docker.inspect_error = PermissionError("daemon unavailable after conflict")
        return docker.run(cmd, **kwargs)

    monkeypatch.setattr(local_backend.subprocess, "run", conflicting_runtime)
    with pytest.raises(RuntimeError, match="already in use"):
        backend.create("thread", "sandbox")
    assert docker.proxy_names[0] in docker.containers
    assert all(cmd[1] not in {"stop", "rm"} for cmd in docker.calls)
    if inspection_fails:
        assert any("Could not probe conflicting sandbox sandbox" in record.getMessage() and record.exc_info is not None for record in caplog.records)
    if conflict_stage == "proxy":
        assert_released_once(allocator, history, history.allocated[0])
        assert_reserved(allocator, peer_ports[0])
    else:
        assert_reserved(allocator, history.allocated[0])
        assert history.released == []


def test_main_name_conflict_adoption_keeps_proxy_port_until_destroy(restricted_backend, monkeypatch):
    conflict = 'Conflict. The container name is already in use by container "peer"'
    backend, allocator, history, docker = restricted_backend(rejected_start(conflict))

    def compatible_main_wins_name(cmd, **kwargs):
        if cmd[1] == "run":
            docker.record_main_container(cmd)
        return docker.run(cmd, **kwargs)

    monkeypatch.setattr(local_backend.subprocess, "run", compatible_main_wins_name)
    readiness_requests = allow_readiness_http(monkeypatch)
    info = backend.create("thread", "sandbox")
    port = history.allocated[0]
    assert info.sandbox_url == f"http://localhost:{port}"
    assert readiness_requests == [f"http://localhost:{port}/v1/sandbox"]
    assert_reserved(allocator, port)
    assert history.released == []
    backend.destroy(info)
    assert_released_once(allocator, history, port)
    backend.complete_absent_teardown("sandbox")
    assert_released_once(allocator, history, port)


@pytest.mark.parametrize("outcome", ["timeout", "rejected"])
def test_late_creation_failure_cannot_release_a_destroyed_instances_successor(restricted_backend, monkeypatch, outcome):
    delayed_failure = subprocess.TimeoutExpired(["docker", "run"], timeout=1) if outcome == "timeout" else rejected_start("daemon rejected late sandbox start")
    expected_error = subprocess.TimeoutExpired if outcome == "timeout" else RuntimeError
    backend, allocator, history, docker = restricted_backend(None)
    allow_readiness_http(monkeypatch)
    successors = []
    interleaved = False

    def destroy_before_create_returns(cmd, **kwargs):
        nonlocal interleaved
        if not interleaved and cmd[1] == "run":
            interleaved = True
            docker.calls.append(tuple(cmd))
            docker.record_main_container(cmd)
            info = backend.discover("sandbox")
            assert info is not None and not info.requires_replacement
            backend.destroy(info)
            successors.append(backend.create("successor-thread", "successor"))
            raise delayed_failure
        return docker.run(cmd, **kwargs)

    monkeypatch.setattr(local_backend.subprocess, "run", destroy_before_create_returns)
    with pytest.raises(expected_error) as caught:
        backend.create("thread", "sandbox")
    if outcome == "timeout":
        assert caught.value is delayed_failure
    else:
        assert "daemon rejected late sandbox start" in str(caught.value)
    assert interleaved
    assert len(history.allocated) == 2
    assert history.released == history.allocated[:1]
    successor_port = urlparse(successors[0].sandbox_url).port
    assert allocator._reserved_ports == {successor_port}
    backend.complete_absent_teardown("sandbox")
    assert allocator._reserved_ports == {successor_port}
    assert history.released == history.allocated[:1]


def test_empty_url_destroy_keeps_unknown_port_until_fenced_absent_cleanup(restricted_backend, monkeypatch):
    backend, allocator, history, docker = restricted_backend(rejected_start(), fail_proxy_stop=True)
    with pytest.raises(RuntimeError, match="daemon rejected sandbox start"):
        backend.create("thread", "sandbox")
    port = history.allocated[0]
    main_command = list(next(cmd for cmd in docker.calls if cmd[:2] == ("docker", "run")))
    docker.record_main_container(main_command)
    docker.containers[docker.proxy_names[0]]["Config"]["Labels"]["deerflow.network_policy_digest"] = "older-policy"
    info = backend.discover("sandbox")
    assert info is not None and info.requires_replacement
    assert info.sandbox_url == ""
    docker.fail_proxy_stop = False
    backend.destroy(info)
    assert docker.containers == {}
    assert_reserved(allocator, port)
    assert history.released == []
    assert backend.is_absent("sandbox") is True
    backend.complete_absent_teardown("sandbox")
    assert_released_once(allocator, history, port)
    backend.complete_absent_teardown("sandbox")
    assert_released_once(allocator, history, port)


def test_failed_proxy_probe_logs_its_error_without_replacing_creation_error(restricted_backend, monkeypatch, caplog):
    original = FileNotFoundError("sandbox executable cannot start")
    backend, allocator, history, docker = restricted_backend(original, fail_proxy_stop=True)
    probe_error = PermissionError("proxy inspection denied")

    def failed_proxy_probe(cmd, **kwargs):
        if docker.proxy_names and cmd == ["docker", "inspect", docker.proxy_names[0]]:
            raise probe_error
        return docker.run(cmd, **kwargs)

    monkeypatch.setattr(local_backend.subprocess, "run", failed_proxy_probe)
    with (
        caplog.at_level(logging.WARNING, logger=local_backend.__name__),
        pytest.raises(FileNotFoundError) as caught,
    ):
        backend.create("thread", "sandbox")
    assert caught.value is original
    warnings = [record for record in caplog.records if record.name == local_backend.__name__ and record.levelno >= logging.WARNING]
    assert any("proxy" in record.getMessage().lower() and record.exc_info and probe_error in (record.exc_info[1], record.exc_info[1].__cause__) for record in warnings)
    assert_reserved(allocator, history.allocated[0])
    assert history.released == []


def test_known_destroy_keeps_release_ownership_when_unknown_destroy_overlaps(restricted_backend, monkeypatch):
    backend, allocator, history, docker = restricted_backend(None)
    info = backend.create("thread", "sandbox")
    port = history.allocated[0]
    unknown_info = local_backend.SandboxInfo(
        sandbox_id=info.sandbox_id,
        sandbox_url=info.sandbox_url,
        container_name=info.container_name,
        container_id=None,
    )
    successors = []
    interleaved = False

    def unknown_destroy_before_known_stop_returns(cmd, **kwargs):
        nonlocal interleaved
        if not interleaved and cmd[1] == "stop" and cmd[-1] == info.container_id:
            interleaved = True
            backend.destroy(unknown_info)
            # The known-generation owner still waits for its stop receipt.
            assert_reserved(allocator, port)
            assert history.released == []
            successors.append(backend.create("successor-thread", "successor"))
        return docker.run(cmd, **kwargs)

    monkeypatch.setattr(local_backend.subprocess, "run", unknown_destroy_before_known_stop_returns)
    backend.destroy(info)
    assert interleaved
    assert_released_once(allocator, history, port)
    successor_port = urlparse(successors[0].sandbox_url).port
    assert allocator._reserved_ports == {successor_port}
    backend.complete_absent_teardown("sandbox")
    assert allocator._reserved_ports == {successor_port}
    assert history.released == [port]
