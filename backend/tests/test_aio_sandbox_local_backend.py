import logging
import os
import subprocess
from types import SimpleNamespace

import pytest

from deerflow.community.aio_sandbox.local_backend import (
    LocalContainerBackend,
    _format_container_command_for_log,
    _format_container_mount,
    _redact_container_command_for_log,
    _resolve_docker_bind_host,
)


def test_format_container_mount_uses_mount_syntax_for_docker_windows_paths():
    args = _format_container_mount("docker", "D:/deer-flow/backend/.deer-flow/threads", "/mnt/threads", False)

    assert args == [
        "--mount",
        "type=bind,src=D:/deer-flow/backend/.deer-flow/threads,dst=/mnt/threads",
    ]


def test_format_container_mount_marks_docker_readonly_mounts():
    args = _format_container_mount("docker", "/host/path", "/mnt/path", True)

    assert args == [
        "--mount",
        "type=bind,src=/host/path,dst=/mnt/path,readonly",
    ]


def test_format_container_mount_keeps_volume_syntax_for_apple_container():
    args = _format_container_mount("container", "/host/path", "/mnt/path", True)

    assert args == [
        "-v",
        "/host/path:/mnt/path:ro",
    ]


def test_redact_container_command_for_log_redacts_env_values():
    redacted = _redact_container_command_for_log(
        [
            "docker",
            "run",
            "-e",
            "API_KEY=secret-value",
            "--env=TOKEN=token-value",
            "--name",
            "sandbox",
            "image",
        ]
    )

    assert "API_KEY=<redacted>" in redacted
    assert "--env=TOKEN=<redacted>" in redacted
    assert "secret-value" not in " ".join(redacted)
    assert "token-value" not in " ".join(redacted)


def test_redact_container_command_for_log_keeps_inherited_env_names():
    redacted = _redact_container_command_for_log(
        [
            "docker",
            "run",
            "-e",
            "API_KEY",
            "--env=TOKEN",
            "--name",
            "sandbox",
            "image",
        ]
    )

    assert redacted == [
        "docker",
        "run",
        "-e",
        "API_KEY",
        "--env=TOKEN",
        "--name",
        "sandbox",
        "image",
    ]


def test_format_container_command_for_log_uses_windows_quoting(monkeypatch):
    monkeypatch.setattr(os, "name", "nt")

    command = _format_container_command_for_log(["docker", "run", "--name", "sandbox one", "image"])

    assert command == 'docker run --name "sandbox one" image'


def test_start_container_logs_redacted_env_values(monkeypatch, caplog):
    backend = LocalContainerBackend(
        image="sandbox:latest",
        base_port=8080,
        container_prefix="sandbox",
        config_mounts=[],
        environment={"API_KEY": "secret-value", "NORMAL": "visible-value"},
    )
    monkeypatch.setattr(backend, "_runtime", "docker")

    captured_cmd: list[str] = []

    def fake_run(cmd, **kwargs):
        captured_cmd.extend(cmd)
        return SimpleNamespace(stdout="container-id\n", stderr="", returncode=0)

    monkeypatch.setattr("subprocess.run", fake_run)

    with caplog.at_level(logging.INFO, logger="deerflow.community.aio_sandbox.local_backend"):
        backend._start_container("sandbox-test", 18080)

    joined_cmd = " ".join(captured_cmd)
    assert "API_KEY=secret-value" in joined_cmd
    assert "NORMAL=visible-value" in joined_cmd

    log_output = "\n".join(record.getMessage() for record in caplog.records)
    assert "API_KEY=<redacted>" in log_output
    assert "NORMAL=<redacted>" in log_output
    assert "secret-value" not in log_output
    assert "visible-value" not in log_output


def _capture_start_container_command(monkeypatch, backend: LocalContainerBackend, runtime: str = "docker") -> list[str]:
    monkeypatch.setattr(backend, "_runtime", runtime)
    captured_cmd: list[str] = []

    def fake_run(cmd, **kwargs):
        captured_cmd.extend(cmd)
        return SimpleNamespace(stdout="container-id\n", stderr="", returncode=0)

    monkeypatch.setattr("subprocess.run", fake_run)
    backend._start_container("sandbox-test", 18080)
    return captured_cmd


def test_resolve_docker_bind_host_defaults_loopback_for_localhost(monkeypatch):
    monkeypatch.delenv("DEER_FLOW_SANDBOX_BIND_HOST", raising=False)
    monkeypatch.delenv("DEER_FLOW_SANDBOX_HOST", raising=False)

    assert _resolve_docker_bind_host() == "127.0.0.1"


def test_resolve_docker_bind_host_follows_host_gateway_mapping_for_dood(monkeypatch):
    """The bind follows what host.docker.internal actually resolves to."""
    monkeypatch.delenv("DEER_FLOW_SANDBOX_BIND_HOST", raising=False)
    monkeypatch.setenv("DEER_FLOW_SANDBOX_HOST", "host.docker.internal")
    monkeypatch.setattr(
        "deerflow.community.aio_sandbox.local_backend._resolve_sandbox_host_address",
        lambda host: "192.168.64.1",
    )

    assert _resolve_docker_bind_host() == "192.168.64.1"


def test_resolve_docker_bind_host_brackets_ipv6_host_gateway(monkeypatch):
    """An IPv6 host-gateway mapping binds the bracketed IPv6 address."""
    monkeypatch.delenv("DEER_FLOW_SANDBOX_BIND_HOST", raising=False)
    monkeypatch.setenv("DEER_FLOW_SANDBOX_HOST", "host.docker.internal")
    monkeypatch.setattr(
        "deerflow.community.aio_sandbox.local_backend._resolve_sandbox_host_address",
        lambda host: "[fd00::1]",
    )

    assert _resolve_docker_bind_host() == "[fd00::1]"


def test_resolve_docker_bind_host_brackets_bare_ipv6_override(monkeypatch):
    """A bare IPv6 literal in the override becomes a valid Docker publish host.

    Docker's ``-p`` syntax requires bracketed IPv6 literals
    (``[fd00::1]:port:8080``); operators writing the escape hatch naturally
    give the bare address, so it must be normalized before use.
    """
    monkeypatch.setenv("DEER_FLOW_SANDBOX_BIND_HOST", "fd00::1")
    assert _resolve_docker_bind_host() == "[fd00::1]"

    monkeypatch.setenv("DEER_FLOW_SANDBOX_BIND_HOST", "[fd00::1]")
    assert _resolve_docker_bind_host() == "[fd00::1]"

    # IPv4 and hostnames pass through unchanged.
    monkeypatch.setenv("DEER_FLOW_SANDBOX_BIND_HOST", "192.168.64.1")
    assert _resolve_docker_bind_host() == "192.168.64.1"
    monkeypatch.setenv("DEER_FLOW_SANDBOX_BIND_HOST", "0.0.0.0")
    assert _resolve_docker_bind_host() == "0.0.0.0"
    monkeypatch.setenv("DEER_FLOW_SANDBOX_BIND_HOST", "host.docker.internal")
    assert _resolve_docker_bind_host() == "host.docker.internal"


def test_resolve_docker_bind_host_uses_discovered_bridge_gateway_when_resolution_fails(monkeypatch):
    monkeypatch.delenv("DEER_FLOW_SANDBOX_BIND_HOST", raising=False)
    monkeypatch.setenv("DEER_FLOW_SANDBOX_HOST", "host.docker.internal")
    monkeypatch.setattr(
        "deerflow.community.aio_sandbox.local_backend._resolve_sandbox_host_address",
        lambda host: None,
    )
    monkeypatch.setattr(
        "deerflow.community.aio_sandbox.local_backend._docker_bridge_gateway_ip",
        lambda: "192.168.64.1",
    )

    assert _resolve_docker_bind_host() == "192.168.64.1"


def test_resolve_docker_bind_host_falls_back_to_static_bridge_gateway(monkeypatch):
    monkeypatch.delenv("DEER_FLOW_SANDBOX_BIND_HOST", raising=False)
    monkeypatch.setenv("DEER_FLOW_SANDBOX_HOST", "host.docker.internal")
    monkeypatch.setattr(
        "deerflow.community.aio_sandbox.local_backend._resolve_sandbox_host_address",
        lambda host: None,
    )
    monkeypatch.setattr(
        "deerflow.community.aio_sandbox.local_backend._docker_bridge_gateway_ip",
        lambda: None,
    )

    assert _resolve_docker_bind_host() == "172.17.0.1"


def test_resolve_docker_bind_host_uses_ipv6_loopback_for_ipv6_sandbox_host(monkeypatch):
    monkeypatch.delenv("DEER_FLOW_SANDBOX_BIND_HOST", raising=False)
    monkeypatch.setenv("DEER_FLOW_SANDBOX_HOST", "[::1]")

    assert _resolve_docker_bind_host() == "[::1]"


def test_resolve_docker_bind_host_logs_selected_bind_reason(caplog):
    with caplog.at_level(logging.DEBUG, logger="deerflow.community.aio_sandbox.local_backend"):
        assert _resolve_docker_bind_host(sandbox_host="localhost", bind_host="") == "127.0.0.1"

    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "Docker sandbox bind: 127.0.0.1 (loopback default)" in messages


def test_resolve_docker_bind_host_allows_explicit_override(monkeypatch):
    monkeypatch.setenv("DEER_FLOW_SANDBOX_HOST", "localhost")
    monkeypatch.setenv("DEER_FLOW_SANDBOX_BIND_HOST", "192.0.2.10")

    assert _resolve_docker_bind_host() == "192.0.2.10"


def test_resolve_docker_bind_host_allows_restoring_legacy_broad_bind(monkeypatch):
    """DEER_FLOW_SANDBOX_BIND_HOST=0.0.0.0 restores the pre-hardening bind."""
    monkeypatch.setenv("DEER_FLOW_SANDBOX_HOST", "host.docker.internal")
    monkeypatch.setenv("DEER_FLOW_SANDBOX_BIND_HOST", "0.0.0.0")

    assert _resolve_docker_bind_host() == "0.0.0.0"


def _clear_hardening_env(monkeypatch):
    for var in (
        "DEER_FLOW_SANDBOX_HOST",
        "DEER_FLOW_SANDBOX_BIND_HOST",
        "DEER_FLOW_SANDBOX_SECCOMP_UNCONFINED",
        "DEER_FLOW_SANDBOX_SECCOMP_PROFILE",
        "DEER_FLOW_SANDBOX_MEMORY",
        "DEER_FLOW_SANDBOX_CPUS",
        "DEER_FLOW_SANDBOX_PIDS_LIMIT",
        "DEER_FLOW_SANDBOX_CONTAINER_USER",
        "DEER_FLOW_SANDBOX_NETWORK",
    ):
        monkeypatch.delenv(var, raising=False)


def test_start_container_binds_local_docker_port_to_loopback_by_default(monkeypatch):
    backend = LocalContainerBackend(
        image="sandbox:latest",
        base_port=8080,
        container_prefix="sandbox",
        config_mounts=[],
        environment={},
    )
    monkeypatch.delenv("DEER_FLOW_SANDBOX_HOST", raising=False)
    monkeypatch.delenv("DEER_FLOW_SANDBOX_BIND_HOST", raising=False)

    captured_cmd = _capture_start_container_command(monkeypatch, backend)

    assert captured_cmd[captured_cmd.index("-p") + 1] == "127.0.0.1:18080:8080"


def test_start_container_brackets_bare_ipv6_bind_override(monkeypatch):
    """A bare IPv6 override reaches -p as a bracketed, valid publish host."""
    backend = LocalContainerBackend(
        image="sandbox:latest",
        base_port=8080,
        container_prefix="sandbox",
        config_mounts=[],
        environment={},
    )
    monkeypatch.setenv("DEER_FLOW_SANDBOX_HOST", "host.docker.internal")
    monkeypatch.setenv("DEER_FLOW_SANDBOX_BIND_HOST", "fd00::1")

    captured_cmd = _capture_start_container_command(monkeypatch, backend)

    assert captured_cmd[captured_cmd.index("-p") + 1] == "[fd00::1]:18080:8080"


def test_start_container_binds_dood_port_to_bridge_gateway(monkeypatch):
    backend = LocalContainerBackend(
        image="sandbox:latest",
        base_port=8080,
        container_prefix="sandbox",
        config_mounts=[],
        environment={},
    )
    monkeypatch.setenv("DEER_FLOW_SANDBOX_HOST", "host.docker.internal")
    monkeypatch.delenv("DEER_FLOW_SANDBOX_BIND_HOST", raising=False)
    monkeypatch.setattr(
        "deerflow.community.aio_sandbox.local_backend._docker_bridge_gateway_ip",
        lambda: "172.17.0.1",
    )

    captured_cmd = _capture_start_container_command(monkeypatch, backend)

    assert captured_cmd[captured_cmd.index("-p") + 1] == "172.17.0.1:18080:8080"


def test_start_container_binds_ipv6_sandbox_host_to_ipv6_loopback(monkeypatch):
    backend = LocalContainerBackend(
        image="sandbox:latest",
        base_port=8080,
        container_prefix="sandbox",
        config_mounts=[],
        environment={},
    )
    monkeypatch.setenv("DEER_FLOW_SANDBOX_HOST", "[::1]")
    monkeypatch.delenv("DEER_FLOW_SANDBOX_BIND_HOST", raising=False)

    captured_cmd = _capture_start_container_command(monkeypatch, backend)

    assert captured_cmd[captured_cmd.index("-p") + 1] == "[::1]:18080:8080"


def test_start_container_keeps_apple_container_port_format(monkeypatch):
    backend = LocalContainerBackend(
        image="sandbox:latest",
        base_port=8080,
        container_prefix="sandbox",
        config_mounts=[],
        environment={},
    )
    monkeypatch.setenv("DEER_FLOW_SANDBOX_BIND_HOST", "127.0.0.1")

    captured_cmd = _capture_start_container_command(monkeypatch, backend, runtime="container")

    assert captured_cmd[captured_cmd.index("-p") + 1] == "18080:8080"


def test_start_container_hardens_docker_run_by_default(monkeypatch):
    backend = LocalContainerBackend(
        image="sandbox:latest",
        base_port=8080,
        container_prefix="sandbox",
        config_mounts=[],
        environment={},
    )
    _clear_hardening_env(monkeypatch)

    captured_cmd = _capture_start_container_command(monkeypatch, backend)

    assert "--cap-drop=ALL" in captured_cmd
    security_opts = [captured_cmd[i + 1] for i, arg in enumerate(captured_cmd) if arg == "--security-opt"]
    assert "no-new-privileges" in security_opts
    # The shipped AIO image needs seccomp=unconfined for its Chromium
    # browser (upstream FAQ), so that option stays the default; the
    # hardening that does not break the shipped image is kept.
    assert "seccomp=unconfined" in security_opts
    assert captured_cmd[captured_cmd.index("--memory") + 1] == "2g"
    assert captured_cmd[captured_cmd.index("--cpus") + 1] == "2"
    assert captured_cmd[captured_cmd.index("--pids-limit") + 1] == "512"
    # Opt-in-only knobs stay absent unless explicitly configured.
    assert "--user" not in captured_cmd
    assert "--network" not in captured_cmd


def test_start_container_seccomp_can_opt_out_to_default_profile(monkeypatch):
    backend = LocalContainerBackend(
        image="sandbox:latest",
        base_port=8080,
        container_prefix="sandbox",
        config_mounts=[],
        environment={},
    )
    _clear_hardening_env(monkeypatch)
    monkeypatch.setenv("DEER_FLOW_SANDBOX_SECCOMP_UNCONFINED", "0")

    captured_cmd = _capture_start_container_command(monkeypatch, backend)

    security_opts = [captured_cmd[i + 1] for i, arg in enumerate(captured_cmd) if arg == "--security-opt"]
    assert "seccomp=unconfined" not in security_opts
    assert "no-new-privileges" in security_opts


def test_start_container_seccomp_profile_env_selects_custom_profile(monkeypatch):
    backend = LocalContainerBackend(
        image="sandbox:latest",
        base_port=8080,
        container_prefix="sandbox",
        config_mounts=[],
        environment={},
    )
    _clear_hardening_env(monkeypatch)
    monkeypatch.setenv("DEER_FLOW_SANDBOX_SECCOMP_PROFILE", "/etc/docker/chromium-seccomp.json")

    captured_cmd = _capture_start_container_command(monkeypatch, backend)

    security_opts = [captured_cmd[i + 1] for i, arg in enumerate(captured_cmd) if arg == "--security-opt"]
    assert "seccomp=/etc/docker/chromium-seccomp.json" in security_opts
    assert "seccomp=unconfined" not in security_opts
    assert "no-new-privileges" in security_opts


def test_resolve_sandbox_host_address_formats_and_filters(monkeypatch):
    import socket as socket_module

    def fake_getaddrinfo(host, port):
        if host == "v4host":
            return [(socket_module.AF_INET, None, None, "", ("203.0.113.7", 0))]
        if host == "v6host":
            return [(socket_module.AF_INET6, None, None, "", ("fd00::1%eth0", 0, 0, 0))]
        if host == "wildcard":
            return [(socket_module.AF_INET, None, None, "", ("0.0.0.0", 0))]
        raise OSError("no such host")

    monkeypatch.setattr("deerflow.community.aio_sandbox.local_backend.socket.getaddrinfo", fake_getaddrinfo)

    from deerflow.community.aio_sandbox.local_backend import _resolve_sandbox_host_address

    assert _resolve_sandbox_host_address("v4host") == "203.0.113.7"
    # zone ids are stripped and IPv6 is bracketed for docker -p syntax
    assert _resolve_sandbox_host_address("v6host") == "[fd00::1]"
    # wildcard resolutions are not bindable choices
    assert _resolve_sandbox_host_address("wildcard") is None
    assert _resolve_sandbox_host_address("unknown.invalid") is None


def test_start_container_resource_limits_env_override(monkeypatch):
    backend = LocalContainerBackend(
        image="sandbox:latest",
        base_port=8080,
        container_prefix="sandbox",
        config_mounts=[],
        environment={},
    )
    _clear_hardening_env(monkeypatch)
    monkeypatch.setenv("DEER_FLOW_SANDBOX_MEMORY", "4g")
    monkeypatch.setenv("DEER_FLOW_SANDBOX_CPUS", "4")
    monkeypatch.setenv("DEER_FLOW_SANDBOX_PIDS_LIMIT", "1024")

    captured_cmd = _capture_start_container_command(monkeypatch, backend)

    assert captured_cmd[captured_cmd.index("--memory") + 1] == "4g"
    assert captured_cmd[captured_cmd.index("--cpus") + 1] == "4"
    assert captured_cmd[captured_cmd.index("--pids-limit") + 1] == "1024"


def test_start_container_resource_limits_can_be_disabled(monkeypatch):
    backend = LocalContainerBackend(
        image="sandbox:latest",
        base_port=8080,
        container_prefix="sandbox",
        config_mounts=[],
        environment={},
    )
    _clear_hardening_env(monkeypatch)
    monkeypatch.setenv("DEER_FLOW_SANDBOX_MEMORY", "0")
    monkeypatch.setenv("DEER_FLOW_SANDBOX_CPUS", "none")
    monkeypatch.setenv("DEER_FLOW_SANDBOX_PIDS_LIMIT", "0")

    captured_cmd = _capture_start_container_command(monkeypatch, backend)

    assert "--memory" not in captured_cmd
    assert "--cpus" not in captured_cmd
    assert "--pids-limit" not in captured_cmd


def test_start_container_passes_through_user_and_network(monkeypatch):
    backend = LocalContainerBackend(
        image="sandbox:latest",
        base_port=8080,
        container_prefix="sandbox",
        config_mounts=[],
        environment={},
    )
    _clear_hardening_env(monkeypatch)
    monkeypatch.setenv("DEER_FLOW_SANDBOX_CONTAINER_USER", "1000:1000")
    monkeypatch.setenv("DEER_FLOW_SANDBOX_NETWORK", "deer-flow-sandbox-egress")

    captured_cmd = _capture_start_container_command(monkeypatch, backend)

    assert captured_cmd[captured_cmd.index("--user") + 1] == "1000:1000"
    assert captured_cmd[captured_cmd.index("--network") + 1] == "deer-flow-sandbox-egress"


def test_start_container_does_not_add_docker_hardening_to_apple_container(monkeypatch):
    """Apple Container's CLI does not support the Docker hardening flags."""
    backend = LocalContainerBackend(
        image="sandbox:latest",
        base_port=8080,
        container_prefix="sandbox",
        config_mounts=[],
        environment={},
    )
    _clear_hardening_env(monkeypatch)
    monkeypatch.setenv("DEER_FLOW_SANDBOX_BIND_HOST", "127.0.0.1")

    captured_cmd = _capture_start_container_command(monkeypatch, backend, runtime="container")

    assert "--cap-drop=ALL" not in captured_cmd
    assert "--security-opt" not in captured_cmd
    assert "--memory" not in captured_cmd
    assert "--cpus" not in captured_cmd
    assert "--pids-limit" not in captured_cmd


def _backend_for_inspect_tests() -> LocalContainerBackend:
    backend = LocalContainerBackend(
        image="sandbox:latest",
        base_port=8080,
        container_prefix="sandbox",
        config_mounts=[],
        environment={},
    )
    backend._runtime = "docker"
    return backend


def test_is_container_running_false_when_container_missing(monkeypatch):
    backend = _backend_for_inspect_tests()

    def fake_run(cmd, **kwargs):
        return SimpleNamespace(stdout="", stderr="Error: No such object: sandbox-missing", returncode=1)

    monkeypatch.setattr("subprocess.run", fake_run)

    assert backend._is_container_running("sandbox-missing") is False


def test_is_container_running_raises_on_runtime_error(monkeypatch):
    backend = _backend_for_inspect_tests()

    def fake_run(cmd, **kwargs):
        return SimpleNamespace(stdout="", stderr="Cannot connect to the Docker daemon", returncode=1)

    monkeypatch.setattr("subprocess.run", fake_run)

    with pytest.raises(RuntimeError, match="Failed to inspect container sandbox-busy"):
        backend._is_container_running("sandbox-busy")


def test_is_container_running_raises_on_timeout(monkeypatch):
    backend = _backend_for_inspect_tests()

    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs["timeout"])

    monkeypatch.setattr("subprocess.run", fake_run)

    with pytest.raises(RuntimeError, match="Timed out checking container sandbox-timeout"):
        backend._is_container_running("sandbox-timeout")


def test_discover_returns_none_when_runtime_check_fails(monkeypatch):
    """A transient daemon error during discovery must fall through to create, not fail acquire."""
    backend = _backend_for_inspect_tests()

    def fake_run(cmd, **kwargs):
        return SimpleNamespace(stdout="", stderr="Cannot connect to the Docker daemon", returncode=1)

    monkeypatch.setattr("subprocess.run", fake_run)

    assert backend.discover("sandbox-blip") is None


def test_discover_returns_none_when_runtime_check_times_out(monkeypatch):
    """An inspect timeout during discovery must not propagate out of discover()."""
    backend = _backend_for_inspect_tests()

    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs["timeout"])

    monkeypatch.setattr("subprocess.run", fake_run)

    assert backend.discover("sandbox-timeout") is None


def test_is_container_running_false_on_apple_container_not_found(monkeypatch):
    """Apple Container's generic "not found" is trusted when it names the container."""
    backend = _backend_for_inspect_tests()

    def fake_run(cmd, **kwargs):
        return SimpleNamespace(stdout="", stderr='Error: not found: "sandbox-apple"', returncode=1)

    monkeypatch.setattr("subprocess.run", fake_run)

    assert backend._is_container_running("sandbox-apple") is False


def test_is_container_running_raises_on_unrelated_not_found_error(monkeypatch):
    """Transient errors whose text contains "not found" must not be misread as a dead container."""
    backend = _backend_for_inspect_tests()

    def fake_run(cmd, **kwargs):
        return SimpleNamespace(stdout="", stderr="Error: credential helper not found in $PATH", returncode=1)

    monkeypatch.setattr("subprocess.run", fake_run)

    with pytest.raises(RuntimeError, match="Failed to inspect container sandbox-busy"):
        backend._is_container_running("sandbox-busy")


def test_stop_container_passes_a_timeout(monkeypatch):
    """An unbounded `stop` can outlive the teardown lease that guards it.

    The `del:` marker keeps a peer from re-acquiring the container during the
    stop, but a lease can lapse (a store outage longer than the TTL) while a
    wedged daemon leaves `docker stop` blocked forever — and the stop then lands
    on a container the peer has since been handed. Bounding the call caps that
    exposure independently of the ownership layer.
    """
    backend = _backend_for_inspect_tests()
    seen = {}

    def fake_run(cmd, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(stdout="", stderr="", returncode=0)

    monkeypatch.setattr("subprocess.run", fake_run)
    backend._stop_container("sandbox-slow")

    assert seen.get("timeout") == backend._STOP_TIMEOUT_SECONDS


def test_stop_container_propagates_a_timeout_instead_of_reporting_success(monkeypatch):
    """A timed-out stop must not be swallowed like a failed one.

    `CalledProcessError` means the runtime answered "I could not stop it"; a
    timeout means we do not know, and the container is probably still running.
    Returning normally would let `_destroy_warm_entry` report a clean stop and
    drop the warm entry, leaking a running container nothing tracks.
    """
    backend = _backend_for_inspect_tests()

    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs["timeout"])

    monkeypatch.setattr("subprocess.run", fake_run)

    with pytest.raises(subprocess.TimeoutExpired):
        backend._stop_container("sandbox-wedged")
