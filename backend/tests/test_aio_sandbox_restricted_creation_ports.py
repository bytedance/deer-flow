"""Restricted creation keeps a reservation until its port owner is absent.

Only Docker CLI responses, readiness HTTP, and host-runtime detection are replaced. Creation,
rollback, absence checks, deferred teardown, and PortAllocator are production
implementations. The CLI double retains resources across commands so a failed
proxy stop remains observable during later reconciliation.
"""

import json
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from threading import Event, get_ident
from types import SimpleNamespace

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
            name = next((name for name, entry in self.containers.items() if entry["Id"] == target), target)
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


@pytest.fixture
def restricted_backend(monkeypatch):
    """Give each scenario its own allocator and an unused local host port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("0.0.0.0", 0))
        base_port = probe.getsockname()[1]
    allocator = network.PortAllocator()
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
        return backend, allocator, base_port, docker

    return scenario


def assert_reserved(allocator, port):
    with pytest.raises(RuntimeError, match="No available port"):
        allocator.allocate(port, max_range=1)


def rejected_start(message="daemon rejected sandbox start"):
    return subprocess.CalledProcessError(1, ["docker", "run"], stderr=message)


def test_runtime_error_with_failed_proxy_cleanup_preserves_port(restricted_backend):
    backend, allocator, port, docker = restricted_backend(rejected_start(), fail_proxy_stop=True)

    with pytest.raises(RuntimeError, match="daemon rejected sandbox start"):
        backend.create("thread", "sandbox")

    assert docker.published_ports == [port]
    assert docker.proxy_names[0] in docker.containers
    assert_reserved(allocator, port)


@pytest.mark.parametrize("error_type", [FileNotFoundError, PermissionError])
def test_unstarted_main_cli_releases_port_after_proxy_is_removed(restricted_backend, error_type):
    original = error_type("sandbox executable cannot start")
    backend, allocator, port, docker = restricted_backend(original)

    with pytest.raises(error_type) as caught:
        backend.create("thread", "sandbox")

    assert caught.value is original
    assert docker.published_ports == [port]
    assert docker.proxy_names[0] not in docker.containers
    assert allocator.allocate(port, max_range=1) == port


def test_network_cleanup_timeout_releases_proxy_port_and_preserves_start_error(
    restricted_backend,
):
    original = FileNotFoundError("sandbox executable cannot start")
    backend, allocator, port, docker = restricted_backend(original, fail_network_remove=True)

    with pytest.raises(FileNotFoundError) as caught:
        backend.create("thread", "sandbox")

    assert caught.value is original
    assert docker.proxy_names[0] not in docker.containers
    assert any(cmd[:3] == ("docker", "network", "rm") for cmd in docker.calls)
    assert allocator.allocate(port, max_range=1) == port


def test_preflight_failure_releases_port_before_any_proxy_attempt(restricted_backend):
    original = FileNotFoundError("runtime unavailable during preflight")
    backend, allocator, port, docker = restricted_backend(rejected_start(), inspect_error=original)

    with pytest.raises(RuntimeError, match="Failed to inspect containers") as caught:
        backend.create("thread", "sandbox")

    assert caught.value.__cause__ is original
    assert docker.published_ports == []
    assert all(cmd[:2] != ("docker", "create") for cmd in docker.calls)
    assert allocator.allocate(port, max_range=1) == port


def test_uncertain_proxy_cleanup_does_not_retry_port_collision(restricted_backend):
    backend, allocator, port, docker = restricted_backend(rejected_start("address already in use"), fail_proxy_stop=True)

    with pytest.raises(RuntimeError, match="address already in use"):
        backend.create("thread", "sandbox")

    # A new port attempt would first repeat the real restricted-resource probe.
    preflight_calls = [cmd for cmd in docker.calls if cmd[:2] == ("docker", "inspect") and len(cmd) == 4]
    assert len(preflight_calls) == 1
    assert docker.published_ports == [port]
    assert_reserved(allocator, port)


def test_confirmed_absence_releases_failed_creation_port_once(restricted_backend):
    original = FileNotFoundError("sandbox executable cannot start")
    backend, allocator, port, docker = restricted_backend(original, fail_proxy_stop=True)

    with pytest.raises(FileNotFoundError) as caught:
        backend.create("thread", "sandbox")
    assert caught.value is original
    assert_reserved(allocator, port)

    # Main-container absence is attested by the real inspect parser. The real
    # deferred teardown still has to remove the proxy and network leftovers.
    docker.fail_proxy_stop = False
    assert backend.is_absent("sandbox") is True
    backend.complete_absent_teardown("sandbox")
    assert docker.containers == {}
    assert allocator.allocate(port, max_range=1) == port

    # A later cleanup must not release a reservation now owned by a successor.
    backend.complete_absent_teardown("sandbox")
    assert_reserved(allocator, port)


@pytest.mark.parametrize("error_type", [FileNotFoundError, PermissionError])
def test_proxy_cli_spawn_failure_returns_its_unused_port(restricted_backend, error_type):
    original = error_type("proxy executable cannot start")
    backend, allocator, port, docker = restricted_backend(rejected_start(), proxy_create_error=original)

    with pytest.raises(error_type) as caught:
        backend.create("thread", "sandbox")

    assert caught.value is original
    assert any(cmd[:2] == ("docker", "create") for cmd in docker.calls)
    assert docker.containers == {}
    assert allocator.allocate(port, max_range=1) == port


def test_retry_waits_for_proxy_absence_before_allocating_again(restricted_backend, monkeypatch):
    backend, allocator, port, docker = restricted_backend(rejected_start(), fail_proxy_stop=True)
    allocated_ports = []
    allocate = allocator.allocate

    def record_allocation(*args, **kwargs):
        allocated = allocate(*args, **kwargs)
        allocated_ports.append(allocated)
        return allocated

    monkeypatch.setattr(allocator, "allocate", record_allocation)
    with pytest.raises(RuntimeError, match="daemon rejected sandbox start"):
        backend.create("thread", "sandbox")

    calls_before_retry = len(docker.calls)
    with pytest.raises(RuntimeError, match="unconfirmed creation"):
        backend.create("thread", "sandbox")

    assert allocated_ports == [port]
    assert all(cmd[:2] == ("docker", "inspect") for cmd in docker.calls[calls_before_retry:])
    assert_reserved(allocator, port)

    # An external cleanup removes the proxy and its leftover networks. The
    # next ordinary create must recover the original process-local reservation.
    docker.containers.clear()
    docker.networks.clear()
    docker.start_error = None
    info = backend.create("thread", "sandbox")

    assert allocated_ports == [port, port]
    assert info.sandbox_url == f"http://localhost:{port}"
    assert docker.published_ports == [port, port]
    assert_reserved(allocator, port)


def test_stale_absence_probe_cannot_release_a_successors_reservation(restricted_backend, monkeypatch):
    backend, allocator, port, docker = restricted_backend(rejected_start(), fail_proxy_stop=True)
    with pytest.raises(RuntimeError, match="daemon rejected sandbox start"):
        backend.create("thread", "sandbox")

    proxy_name = docker.proxy_names[0]
    del docker.containers[proxy_name]
    docker.fail_proxy_stop = False
    docker.start_error = None
    successors = []
    interleaved = False

    def inspect_then_transfer(cmd, **kwargs):
        nonlocal interleaved
        response = docker.run(cmd, **kwargs)
        if not interleaved and cmd == ["docker", "inspect", proxy_name]:
            interleaved = True
            # Pause after the real CLI parser's input observes absence. Another
            # cleanup releases the old reservation, then a real create owns it.
            backend.complete_absent_teardown("sandbox")
            successors.append(backend.create("successor-thread", "successor"))
        return response

    monkeypatch.setattr(local_backend.subprocess, "run", inspect_then_transfer)
    info = backend.create("thread", "sandbox")

    assert interleaved
    assert successors[0].sandbox_url == f"http://localhost:{port}"
    assert info.sandbox_url != successors[0].sandbox_url
    assert_reserved(allocator, port)


def test_first_failure_probe_cannot_release_a_successors_reservation(restricted_backend, monkeypatch):
    backend, allocator, port, docker = restricted_backend(rejected_start(), fail_proxy_stop=True)
    successors = []
    interleaved = False

    def first_probe_then_transfer(cmd, **kwargs):
        nonlocal interleaved
        if not interleaved and docker.proxy_names and cmd == ["docker", "inspect", docker.proxy_names[0]]:
            interleaved = True
            # The previously failed proxy removal finishes externally just
            # before settlement observes absence. Preserve that probe response
            # while another cleanup and create transfer ownership of the port.
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
    assert successors[0].sandbox_url == f"http://localhost:{port}"
    assert docker.published_ports == [port, port]
    assert_reserved(allocator, port)


class CleanupInterrupted(BaseException):
    """Model a lifecycle interruption without stopping the pytest session."""


@pytest.mark.parametrize("interrupted_stage", ["rollback", "settlement"])
def test_cleanup_interruption_keeps_the_reservation_recoverable(restricted_backend, monkeypatch, interrupted_stage):
    backend, allocator, port, docker = restricted_backend(rejected_start(), fail_proxy_stop=True)
    interruption = CleanupInterrupted("cleanup interrupted")
    interrupted = False

    def interrupt_cleanup(cmd, **kwargs):
        nonlocal interrupted
        is_rollback = cmd[1] == "stop"
        is_settlement = docker.proxy_names and cmd == ["docker", "inspect", docker.proxy_names[0]]
        if not interrupted and ((interrupted_stage == "rollback" and is_rollback) or (interrupted_stage == "settlement" and is_settlement)):
            interrupted = True
            raise interruption
        return docker.run(cmd, **kwargs)

    monkeypatch.setattr(local_backend.subprocess, "run", interrupt_cleanup)
    with pytest.raises(CleanupInterrupted) as caught:
        backend.create("thread", "sandbox")

    assert caught.value is interruption
    assert_reserved(allocator, port)
    docker.fail_proxy_stop = False
    assert backend.is_absent("sandbox") is True
    backend.complete_absent_teardown("sandbox")
    assert allocator.allocate(port, max_range=1) == port


def allow_readiness_http(monkeypatch):
    requests = []

    def healthy_response(session, url, **kwargs):
        requests.append(url)
        return SimpleNamespace(status_code=200)

    monkeypatch.setattr(sandbox_backend.requests.Session, "get", healthy_response)
    return requests


def test_destroying_discovered_failed_creation_clears_its_reservation(restricted_backend, monkeypatch):
    backend, allocator, port, docker = restricted_backend(rejected_start(), fail_proxy_stop=True)
    with pytest.raises(RuntimeError, match="daemon rejected sandbox start"):
        backend.create("thread", "sandbox")

    # The daemon later exposes a healthy main container using the same proxy.
    # Exercise real discovery and destruction against that recovered metadata.
    main_command = list(next(cmd for cmd in docker.calls if cmd[:2] == ("docker", "run")))
    docker.record_main_container(main_command)
    readiness_requests = allow_readiness_http(monkeypatch)
    info = backend.discover("sandbox")
    assert info is not None
    assert info.requires_replacement is False
    assert readiness_requests == [f"http://localhost:{port}/v1/sandbox"]
    assert_reserved(allocator, port)

    docker.fail_proxy_stop = False
    backend.destroy(info)
    assert docker.containers == {}
    assert allocator.allocate(port, max_range=1) == port

    backend.complete_absent_teardown("sandbox")
    assert_reserved(allocator, port)


@pytest.mark.parametrize("conflict_stage", ["proxy", "main"])
@pytest.mark.parametrize("inspection_fails", [False, True])
def test_name_conflict_only_retains_a_port_from_this_attempts_proxy(restricted_backend, monkeypatch, conflict_stage, inspection_fails):
    conflict = 'Conflict. The container name is already in use by container "peer"'
    backend, allocator, port, docker = restricted_backend(rejected_start(conflict))
    peer_ports = []

    def conflicting_runtime(cmd, **kwargs):
        if conflict_stage == "proxy" and cmd[1] == "create":
            # A peer's proxy wins the name after preflight. Its binding belongs
            # to a different reservation, while this attempt's port is unused.
            docker.run(cmd, **kwargs)
            name = cmd[cmd.index("--name") + 1]
            peer_port = allocator.allocate(port + 1)
            peer_ports.append(peer_port)
            entry = docker.containers[name]
            for bindings in (entry["HostConfig"]["PortBindings"], entry["NetworkSettings"]["Ports"]):
                bindings["8080/tcp"][0]["HostPort"] = str(peer_port)
            if inspection_fails:
                docker.inspect_error = PermissionError("daemon unavailable after conflict")
            return docker._response(cmd, kwargs, stderr=conflict, returncode=1)
        if conflict_stage == "main" and cmd[1] == "run":
            # This attempt has already created its proxy. An incompatible main
            # container wins the other name, so the set cannot be adopted.
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
    if conflict_stage == "proxy":
        assert allocator.allocate(port, max_range=1) == port
        assert_reserved(allocator, peer_ports[0])
    else:
        assert_reserved(allocator, port)


def test_main_name_conflict_adoption_transfers_port_until_destroy(restricted_backend, monkeypatch):
    conflict = 'Conflict. The container name is already in use by container "peer"'
    backend, allocator, port, docker = restricted_backend(rejected_start(conflict))

    def compatible_main_wins_name(cmd, **kwargs):
        if cmd[1] == "run":
            docker.record_main_container(cmd)
        return docker.run(cmd, **kwargs)

    monkeypatch.setattr(local_backend.subprocess, "run", compatible_main_wins_name)
    readiness_requests = allow_readiness_http(monkeypatch)
    info = backend.create("thread", "sandbox")

    assert info.sandbox_url == f"http://localhost:{port}"
    assert readiness_requests == [f"http://localhost:{port}/v1/sandbox"]
    assert_reserved(allocator, port)
    backend.destroy(info)
    assert allocator.allocate(port, max_range=1) == port
    backend.complete_absent_teardown("sandbox")
    assert_reserved(allocator, port)


def test_recovery_waits_for_an_adopted_containers_destroy_to_finish(restricted_backend, monkeypatch):
    backend, allocator, port, docker = restricted_backend(rejected_start(), fail_proxy_stop=True)
    with pytest.raises(RuntimeError, match="daemon rejected sandbox start"):
        backend.create("thread", "sandbox")

    main_command = list(next(cmd for cmd in docker.calls if cmd[:2] == ("docker", "run")))
    docker.record_main_container(main_command)
    allow_readiness_http(monkeypatch)
    info = backend.discover("sandbox")
    assert info is not None
    docker.fail_proxy_stop = False
    interleaved = False

    def retry_before_main_stop_completes(cmd, **kwargs):
        nonlocal interleaved
        if cmd[1] == "stop" and cmd[-1] == info.container_id:
            interleaved = True
            assert docker.proxy_names[0] not in docker.containers
            # Proxy absence is visible, but the in-progress destroy still owns
            # the release. A new create must wait for that cleanup to finish.
            with pytest.raises(RuntimeError, match="unconfirmed creation"):
                backend.create("thread", "sandbox")
            assert_reserved(allocator, port)
        return docker.run(cmd, **kwargs)

    monkeypatch.setattr(local_backend.subprocess, "run", retry_before_main_stop_completes)
    backend.destroy(info)

    assert interleaved
    assert allocator.allocate(port, max_range=1) == port
    backend.complete_absent_teardown("sandbox")
    assert_reserved(allocator, port)


@pytest.mark.parametrize("outcome", ["timeout", "rejected"])
def test_late_creation_failure_cannot_release_a_destroyed_instances_successor(restricted_backend, monkeypatch, outcome):
    delayed_failure = subprocess.TimeoutExpired(["docker", "run"], timeout=1) if outcome == "timeout" else rejected_start("daemon rejected late sandbox start")
    expected_error = subprocess.TimeoutExpired if outcome == "timeout" else RuntimeError
    backend, allocator, port, docker = restricted_backend(None)
    readiness_requests = allow_readiness_http(monkeypatch)
    successors = []
    interleaved = False

    def destroy_before_create_returns(cmd, **kwargs):
        nonlocal interleaved
        if not interleaved and cmd[1] == "run":
            interleaved = True
            # The daemon publishes the main container while its original CLI
            # invocation is still waiting to return a success/error receipt.
            docker.calls.append(tuple(cmd))
            docker.record_main_container(cmd)
            info = backend.discover("sandbox")
            assert info is not None and not info.requires_replacement
            assert info.sandbox_url == f"http://localhost:{port}"
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
    assert readiness_requests == [f"http://localhost:{port}/v1/sandbox"]
    assert successors[0].sandbox_url == f"http://localhost:{port}"
    assert docker.published_ports == [port, port]
    assert_reserved(allocator, port)
    backend.complete_absent_teardown("sandbox")
    assert_reserved(allocator, port)


@pytest.mark.parametrize("reenter_create", [False, True])
def test_destroy_with_empty_url_releases_failed_creation_port_once(restricted_backend, monkeypatch, reenter_create):
    backend, allocator, port, docker = restricted_backend(rejected_start(), fail_proxy_stop=True)
    with pytest.raises(RuntimeError, match="daemon rejected sandbox start"):
        backend.create("thread", "sandbox")

    main_command = list(next(cmd for cmd in docker.calls if cmd[:2] == ("docker", "run")))
    docker.record_main_container(main_command)
    proxy = docker.containers[docker.proxy_names[0]]
    proxy["Config"]["Labels"]["deerflow.network_policy_digest"] = "older-policy"
    info = backend.discover("sandbox")
    assert info is not None and info.requires_replacement
    assert info.sandbox_url == ""
    assert_reserved(allocator, port)
    docker.fail_proxy_stop = False
    reentered = False

    def retry_while_main_stop_is_pending(cmd, **kwargs):
        nonlocal reentered
        if reenter_create and cmd[1] == "stop" and cmd[-1] == info.container_id:
            reentered = True
            assert docker.proxy_names[0] not in docker.containers
            calls_before_retry = len(docker.calls)
            with pytest.raises(RuntimeError):
                backend.create("thread", "sandbox")
            assert all(call[:2] != ("docker", "create") for call in docker.calls[calls_before_retry:])
            assert_reserved(allocator, port)
        return docker.run(cmd, **kwargs)

    monkeypatch.setattr(local_backend.subprocess, "run", retry_while_main_stop_is_pending)
    backend.destroy(info)

    assert reentered is reenter_create
    assert docker.containers == {}
    assert allocator.allocate(port, max_range=1) == port
    backend.complete_absent_teardown("sandbox")
    assert_reserved(allocator, port)


def test_empty_url_destroy_owns_release_while_creation_settles_absence(restricted_backend, monkeypatch):
    backend, allocator, port, docker = restricted_backend(rejected_start(), fail_proxy_stop=True)
    settlement_waiting = Event()
    resume_settlement = Event()
    destroy_waiting = Event()
    resume_destroy = Event()
    creation_thread = None
    main_generation = None

    def interleave_settlement_and_destroy(cmd, **kwargs):
        nonlocal main_generation
        if cmd[1] == "run":
            entry = docker.record_main_container(cmd)
            main_generation = entry["Id"]
            docker.containers[docker.proxy_names[0]]["Config"]["Labels"]["deerflow.network_policy_digest"] = "older-policy"
        if cmd[1] == "stop" and cmd[-1] == "offline-restricted-sandbox":
            # Rollback cannot remove the main or proxy. Both remain visible
            # when the failed create reaches its first port-owner probe.
            return docker._response(cmd, kwargs, stderr="daemon denied main stop", returncode=1)
        if get_ident() == creation_thread and docker.proxy_names and cmd == ["docker", "inspect", docker.proxy_names[0]]:
            settlement_waiting.set()
            assert resume_settlement.wait(5), "creation settlement was not resumed"
        if cmd[1] == "stop" and cmd[-1] == main_generation:
            assert docker.proxy_names[0] not in docker.containers
            destroy_waiting.set()
            assert resume_destroy.wait(5), "main destruction was not resumed"
        return docker.run(cmd, **kwargs)

    def create_and_expect_failure():
        nonlocal creation_thread
        creation_thread = get_ident()
        with pytest.raises(RuntimeError, match="daemon rejected sandbox start"):
            backend.create("thread", "sandbox")

    monkeypatch.setattr(local_backend.subprocess, "run", interleave_settlement_and_destroy)
    with ThreadPoolExecutor(max_workers=2) as workers:
        creation = workers.submit(create_and_expect_failure)
        destruction = None
        try:
            assert settlement_waiting.wait(5), "creation never reached port settlement"
            info = backend.discover("sandbox")
            assert info is not None and info.requires_replacement
            assert info.sandbox_url == ""
            docker.fail_proxy_stop = False
            destruction = workers.submit(backend.destroy, info)
            assert destroy_waiting.wait(5), "destroy never reached the main stop"
            resume_settlement.set()
            creation.result(timeout=5)
            assert_reserved(allocator, port)
        finally:
            resume_settlement.set()
            resume_destroy.set()
            creation.result(timeout=5)
            if destruction is not None:
                destruction.result(timeout=5)

    assert docker.containers == {}
    assert allocator.allocate(port, max_range=1) == port
    backend.complete_absent_teardown("sandbox")
    assert_reserved(allocator, port)


def test_same_id_create_preserves_an_active_pre_proxy_reservation(restricted_backend, monkeypatch):
    backend, allocator, port, docker = restricted_backend(None)
    allow_readiness_http(monkeypatch)
    interleaved = False

    def retry_before_proxy_creation(cmd, **kwargs):
        nonlocal interleaved
        if not interleaved and cmd[:3] == ["docker", "network", "create"]:
            interleaved = True
            # The outer create has reserved its port and completed preflight.
            # Proxy absence cannot justify reclaiming this active reservation.
            with pytest.raises(RuntimeError):
                backend.create("thread", "sandbox")
            assert_reserved(allocator, port)
        return docker.run(cmd, **kwargs)

    monkeypatch.setattr(local_backend.subprocess, "run", retry_before_proxy_creation)
    info = backend.create("thread", "sandbox")

    assert interleaved
    assert info.sandbox_url == f"http://localhost:{port}"
    assert_reserved(allocator, port)
    # Successful creation must retire its active-attempt marker so an ordinary
    # later call can discover and adopt the healthy runtime.
    adopted = backend.create("thread", "sandbox")
    assert adopted.container_id == info.container_id
    assert adopted.sandbox_url == info.sandbox_url
    assert docker.published_ports == [port]
    assert_reserved(allocator, port)


def test_old_empty_url_destroy_preserves_a_new_pre_proxy_reservation(restricted_backend, monkeypatch):
    backend, allocator, port, docker = restricted_backend(rejected_start(), fail_proxy_stop=True)
    with pytest.raises(RuntimeError, match="daemon rejected sandbox start"):
        backend.create("thread", "sandbox")

    main_command = list(next(cmd for cmd in docker.calls if cmd[:2] == ("docker", "run")))
    docker.record_main_container(main_command)
    docker.containers[docker.proxy_names[0]]["Config"]["Labels"]["deerflow.network_policy_digest"] = "older-policy"
    old_info = backend.discover("sandbox")
    assert old_info is not None and old_info.requires_replacement
    assert old_info.sandbox_url == ""

    # External removal leaves a stale replacement snapshot. The next create
    # reclaims the old failed reservation and starts a new attempt on its port.
    docker.containers.clear()
    docker.networks.clear()
    docker.fail_proxy_stop = False
    docker.start_error = None
    interleaved = False

    def destroy_old_snapshot_before_new_proxy(cmd, **kwargs):
        nonlocal interleaved
        if not interleaved and cmd[:3] == ["docker", "network", "create"]:
            interleaved = True
            backend.destroy(old_info)
            assert_reserved(allocator, port)
        return docker.run(cmd, **kwargs)

    monkeypatch.setattr(local_backend.subprocess, "run", destroy_old_snapshot_before_new_proxy)
    info = backend.create("thread", "sandbox")

    assert interleaved
    assert info.sandbox_url == f"http://localhost:{port}"
    assert docker.published_ports == [port, port]
    assert_reserved(allocator, port)
    backend.destroy(info)
    assert allocator.allocate(port, max_range=1) == port
    backend.complete_absent_teardown("sandbox")
    assert_reserved(allocator, port)


def test_nested_same_generation_destroy_releases_an_empty_url_attempt_once(restricted_backend, monkeypatch):
    backend, allocator, port, docker = restricted_backend(rejected_start(), fail_proxy_stop=True)
    with pytest.raises(RuntimeError, match="daemon rejected sandbox start"):
        backend.create("thread", "sandbox")

    main_command = list(next(cmd for cmd in docker.calls if cmd[:2] == ("docker", "run")))
    docker.record_main_container(main_command)
    docker.containers[docker.proxy_names[0]]["Config"]["Labels"]["deerflow.network_policy_digest"] = "older-policy"
    empty_url_info = backend.discover("sandbox")
    known_url_info = backend.inspect_runtime("sandbox")
    assert empty_url_info is not None and empty_url_info.requires_replacement
    assert empty_url_info.sandbox_url == ""
    assert known_url_info is not None
    assert known_url_info.sandbox_url == f"http://localhost:{port}"
    assert known_url_info.container_id == empty_url_info.container_id
    docker.fail_proxy_stop = False
    interleaved = False

    def destroy_known_metadata_inside_empty_url_destroy(cmd, **kwargs):
        nonlocal interleaved
        if not interleaved and cmd[1] == "stop" and cmd[-1] == empty_url_info.container_id:
            interleaved = True
            # The outer destroy has already removed the proxy. A concurrent
            # caller has retained this generation's earlier port-bearing view.
            backend.destroy(known_url_info)
            assert backend.is_absent("sandbox") is True
            assert_reserved(allocator, port)
        return docker.run(cmd, **kwargs)

    monkeypatch.setattr(local_backend.subprocess, "run", destroy_known_metadata_inside_empty_url_destroy)
    backend.destroy(empty_url_info)

    assert interleaved
    assert docker.containers == {}
    docker.start_error = None
    successor = backend.create("successor-thread", "successor")
    assert successor.sandbox_url == f"http://localhost:{port}"
    assert_reserved(allocator, port)
    backend.complete_absent_teardown("sandbox")
    assert_reserved(allocator, port)


def test_absent_teardown_preserves_a_port_until_its_destroy_returns(restricted_backend, monkeypatch):
    backend, allocator, port, docker = restricted_backend(rejected_start(), fail_proxy_stop=True)
    with pytest.raises(RuntimeError, match="daemon rejected sandbox start"):
        backend.create("thread", "sandbox")

    main_command = list(next(cmd for cmd in docker.calls if cmd[:2] == ("docker", "run")))
    docker.record_main_container(main_command)
    allow_readiness_http(monkeypatch)
    info = backend.discover("sandbox")
    assert info is not None and not info.requires_replacement
    assert info.sandbox_url == f"http://localhost:{port}"
    docker.fail_proxy_stop = False
    interleaved = False

    def settle_absence_before_stop_receipt_returns(cmd, **kwargs):
        nonlocal interleaved
        response = docker.run(cmd, **kwargs)
        if not interleaved and cmd[1] == "stop" and cmd[-1] == info.container_id:
            interleaved = True
            # Docker has removed the main, but destroy still owns this attempt
            # until the outstanding stop receipt returns to its caller.
            assert backend.is_absent("sandbox") is True
            backend.complete_absent_teardown("sandbox")
            assert_reserved(allocator, port)
        return response

    monkeypatch.setattr(local_backend.subprocess, "run", settle_absence_before_stop_receipt_returns)
    backend.destroy(info)

    assert interleaved
    assert docker.containers == {}
    docker.start_error = None
    successor = backend.create("successor-thread", "successor")
    assert successor.sandbox_url == f"http://localhost:{port}"
    assert_reserved(allocator, port)
    backend.complete_absent_teardown("sandbox")
    assert_reserved(allocator, port)
