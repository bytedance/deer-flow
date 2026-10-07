import ast
import json
import logging
import os
import socket
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from deerflow.community.aio_sandbox import local_backend as local_backend_module
from deerflow.community.aio_sandbox.local_backend import (
    LocalContainerBackend,
    _ContainerInspection,
    _docker_server_is_desktop,
    _format_container_command_for_log,
    _format_container_mount,
    _NetworkInspection,
    _redact_container_command_for_log,
    _resolve_docker_bind_host,
)
from deerflow.community.aio_sandbox.sandbox_info import SandboxInfo
from deerflow.utils.network import get_free_port, release_port


def test_sandbox_info_does_not_serialize_or_repr_relay_credentials():
    info = SandboxInfo(
        sandbox_id="sandbox-id",
        sandbox_url="http://localhost:8080",
        request_headers={"X-DeerFlow-Relay-Token": "secret-token"},
        requires_replacement=True,
    )

    assert "request_headers" not in info.to_dict()
    assert "requires_replacement" not in info.to_dict()
    assert "secret-token" not in repr(info)


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


def test_restricted_network_requires_docker_engine_28(monkeypatch):
    monkeypatch.setattr(LocalContainerBackend, "_detect_runtime", lambda _self: "docker")
    monkeypatch.setattr(
        "subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout="27.5.1\n", stderr="", returncode=0),
    )

    with pytest.raises(RuntimeError, match="Docker Engine 28 or newer"):
        LocalContainerBackend(
            image="sandbox:latest",
            base_port=8080,
            container_prefix="sandbox",
            config_mounts=[],
            environment={},
            network_config={"mode": "isolated"},
        )


@pytest.mark.parametrize(
    ("operating_system", "expected"),
    [
        ('"Docker Desktop"', True),
        ('"Ubuntu 24.04.3 LTS"', False),
    ],
)
def test_docker_desktop_detection_uses_daemon_operating_system(monkeypatch, operating_system, expected):
    backend = LocalContainerBackend(
        image="sandbox:latest",
        base_port=8080,
        container_prefix="sandbox",
        config_mounts=[],
        environment={},
    )

    def fake_run(cmd, **_kwargs):
        assert cmd == ["docker", "info", "--format", "{{json .OperatingSystem}}"]
        return SimpleNamespace(stdout=operating_system, stderr="", returncode=0)

    _docker_server_is_desktop.cache_clear()
    monkeypatch.setattr("subprocess.run", fake_run)

    try:
        assert backend._docker_server_is_desktop() is expected
    finally:
        _docker_server_is_desktop.cache_clear()


def test_docker_desktop_detection_retries_after_transient_failure(monkeypatch):
    """A transient probe failure is not cached; subsequent call can detect Desktop."""
    attempts = 0

    def fake_run(cmd, **_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return SimpleNamespace(stdout="", stderr="daemon starting", returncode=1)
        return SimpleNamespace(stdout='"Docker Desktop"', stderr="", returncode=0)

    _docker_server_is_desktop.cache_clear()
    monkeypatch.setattr("subprocess.run", fake_run)

    try:
        assert _docker_server_is_desktop() is False
        assert _docker_server_is_desktop() is True
        assert _docker_server_is_desktop() is True
        assert attempts == 2
    finally:
        _docker_server_is_desktop.cache_clear()


def test_darwin_open_keeps_docker_to_reconcile_restricted_sandbox(monkeypatch):
    commands: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        commands.append(cmd)
        if cmd[:2] == ["docker", "ps"]:
            return SimpleNamespace(stdout="sandbox-transition\n", stderr="", returncode=0)
        if cmd == ["container", "--version"]:
            return SimpleNamespace(stdout="container 0.7.0\n", stderr="", returncode=0)
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr("deerflow.community.aio_sandbox.local_backend.platform.system", lambda: "Darwin")
    monkeypatch.setattr("subprocess.run", fake_run)

    backend = LocalContainerBackend(
        image="sandbox:latest",
        base_port=8080,
        container_prefix="sandbox",
        config_mounts=[],
        environment={},
        network_config={"mode": "open"},
    )
    monkeypatch.setattr(
        backend,
        "_batch_inspect",
        lambda _names, **_kwargs: {
            "sandbox-transition": _ContainerInspection(
                1.0,
                None,
                {
                    "deerflow.role": "sandbox",
                    "deerflow.sandbox_id": "transition",
                    "deerflow.network_mode": "allowlist",
                },
                "sandbox:latest",
                frozenset({"deer-flow-sandbox-net-old"}),
            )
        },
    )

    infos = backend.list_running()

    assert backend.runtime == "docker"
    assert [info.sandbox_id for info in infos] == ["transition"]
    assert infos[0].requires_replacement is True
    assert ["container", "--version"] in commands
    assert any("label=deerflow.role=sandbox" in command for command in commands)


def test_darwin_open_uses_apple_container_without_managed_docker_sandboxes(monkeypatch):
    commands: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        commands.append(cmd)
        if cmd == ["container", "--version"]:
            return SimpleNamespace(stdout="container 0.7.0\n", stderr="", returncode=0)
        if cmd[:2] == ["docker", "ps"]:
            return SimpleNamespace(stdout="other-sandbox-collision\n", stderr="", returncode=0)
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr("deerflow.community.aio_sandbox.local_backend.platform.system", lambda: "Darwin")
    monkeypatch.setattr("subprocess.run", fake_run)

    backend = LocalContainerBackend(
        image="sandbox:latest",
        base_port=8080,
        container_prefix="sandbox",
        config_mounts=[],
        environment={},
        network_config={"mode": "open"},
    )

    assert backend.runtime == "container"
    assert any("label=deerflow.role=sandbox" in command for command in commands)


def _restricted_backend() -> LocalContainerBackend:
    backend = LocalContainerBackend(
        image="sandbox:latest",
        base_port=8080,
        container_prefix="sandbox",
        config_mounts=[],
        environment={},
    )
    backend._runtime = "docker"
    backend._network_mode = "allowlist"
    backend._network_config = {
        "mode": "allowlist",
        "allow_domains": ["pypi.org", "files.pythonhosted.org"],
        "approval": "prompt",
        "temporary_grant_ttl": 300,
        "proxy_image": "proxy:latest",
    }
    return backend


def test_network_policy_digest_is_canonical_and_covers_effective_policy():
    backend = _restricted_backend()
    original = backend._network_policy_digest()

    backend._network_config["allow_domains"] = ["files.pythonhosted.org", "pypi.org"]
    assert backend._network_policy_digest() == original

    backend._network_config["allow_domains"] = ["pypi.org"]
    assert backend._network_policy_digest() != original


def test_open_create_labels_sandbox_identity_and_mode(monkeypatch):
    backend = _backend_for_inspect_tests()
    captured: dict[str, object] = {}

    def fake_start(*_args, **kwargs):
        captured.update(kwargs)
        return "container-id"

    monkeypatch.setattr(backend, "_start_container", fake_start)
    monkeypatch.setattr("deerflow.community.aio_sandbox.local_backend.get_free_port", lambda start_port=None: 18080)

    backend.create(thread_id="thread", sandbox_id="labelled-open")

    assert captured["labels"] == {
        "deerflow.sandbox_id": "labelled-open",
        "deerflow.role": "sandbox",
        "deerflow.network_mode": "open",
    }


def test_create_internal_network_isolates_both_gateway_families_and_labels_policy(monkeypatch):
    backend = _restricted_backend()
    commands: list[list[str]] = []
    monkeypatch.setattr(backend, "_inspect_network", lambda _name: None)

    def fake_run(cmd, **_kwargs):
        commands.append(cmd)
        return SimpleNamespace(stdout="network-id\n", stderr="", returncode=0)

    monkeypatch.setattr("subprocess.run", fake_run)
    backend._create_internal_network("sandbox-network", "sandbox-id")

    create = commands[0]
    assert "com.docker.network.bridge.gateway_mode_ipv4=isolated" in create
    assert "com.docker.network.bridge.gateway_mode_ipv6=isolated" in create
    assert f"deerflow.network_policy_digest={backend._network_policy_digest()}" in create


def test_create_egress_network_is_per_sandbox_and_disables_inter_container_traffic(monkeypatch):
    backend = _restricted_backend()
    commands: list[list[str]] = []
    monkeypatch.setattr(backend, "_inspect_network", lambda _name: None)

    def fake_run(cmd, **_kwargs):
        commands.append(cmd)
        return SimpleNamespace(stdout="network-id\n", stderr="", returncode=0)

    monkeypatch.setattr("subprocess.run", fake_run)
    backend._create_egress_network("sandbox-egress", "sandbox-id")

    create = commands[0]
    assert "--internal" not in create
    assert "com.docker.network.bridge.enable_icc=false" in create
    assert "deerflow.role=egress-network" in create
    assert f"deerflow.network_policy_digest={backend._network_policy_digest()}" in create


def test_restricted_resource_status_requires_matching_policy_image_and_network():
    backend = _restricted_backend()
    sandbox_id = "existing"
    container_name = "sandbox-existing"
    proxy_name, network_name = backend._resource_names(sandbox_id)
    egress_network_name = backend._egress_network_name(sandbox_id)
    inspections = {
        container_name: _ContainerInspection(
            created_at=1.0,
            host_port=None,
            labels=backend._restricted_labels(sandbox_id, "sandbox"),
            image="sandbox:latest",
            networks=frozenset({network_name}),
        ),
        proxy_name: _ContainerInspection(
            created_at=1.0,
            host_port=18080,
            labels=backend._restricted_labels(sandbox_id, "network-proxy"),
            image="proxy:latest",
            networks=frozenset({egress_network_name, network_name}),
            relay_token="test-relay-token-that-is-at-least-32-bytes",
        ),
    }
    network = _NetworkInspection(
        driver="bridge",
        internal=True,
        labels=backend._restricted_labels(sandbox_id, "network"),
        options={
            "com.docker.network.bridge.gateway_mode_ipv4": "isolated",
            "com.docker.network.bridge.gateway_mode_ipv6": "isolated",
        },
    )
    egress_network = _NetworkInspection(
        driver="bridge",
        internal=False,
        labels=backend._restricted_labels(sandbox_id, "egress-network"),
        options={"com.docker.network.bridge.enable_icc": "false"},
    )
    backend._inspect_network = lambda name: network if name == network_name else egress_network

    assert backend._restricted_resources_status(sandbox_id, inspections=inspections) == "compatible"

    compatible_proxy = inspections[proxy_name]
    inspections[proxy_name] = _ContainerInspection(
        created_at=compatible_proxy.created_at,
        host_port=compatible_proxy.host_port,
        labels=compatible_proxy.labels,
        image=compatible_proxy.image,
        networks=compatible_proxy.networks,
    )
    assert backend._restricted_resources_status(sandbox_id, inspections=inspections) == "mismatch"
    inspections[proxy_name] = compatible_proxy

    egress_network = _NetworkInspection(
        driver="bridge",
        internal=False,
        labels=backend._restricted_labels(sandbox_id, "egress-network"),
        options={"com.docker.network.bridge.enable_icc": "true"},
    )
    assert backend._restricted_resources_status(sandbox_id, inspections=inspections) == "mismatch"

    egress_network = _NetworkInspection(
        driver="bridge",
        internal=False,
        labels=backend._restricted_labels(sandbox_id, "egress-network"),
        options={"com.docker.network.bridge.enable_icc": "false"},
    )
    inspections[proxy_name] = _ContainerInspection(
        created_at=1.0,
        host_port=18080,
        labels={**backend._restricted_labels(sandbox_id, "network-proxy"), "deerflow.network_policy_digest": "stale"},
        image="proxy:latest",
        networks=frozenset({egress_network_name, network_name}),
        relay_token="test-relay-token-that-is-at-least-32-bytes",
    )
    assert backend._restricted_resources_status(sandbox_id, inspections=inspections) == "mismatch"


def test_restricted_sandbox_has_no_published_port_and_forces_proxy_env(monkeypatch):
    backend = LocalContainerBackend(
        image="sandbox:latest",
        base_port=8080,
        container_prefix="sandbox",
        config_mounts=[],
        environment={"HTTP_PROXY": "http://operator-proxy:3128"},
    )
    monkeypatch.setattr(backend, "_runtime", "docker")
    captured_cmd: list[str] = []

    def fake_run(cmd, **kwargs):
        captured_cmd.extend(cmd)
        return SimpleNamespace(stdout="container-id\n", stderr="", returncode=0)

    monkeypatch.setattr("subprocess.run", fake_run)
    backend._start_container(
        "sandbox-test",
        18080,
        network_override="deer-flow-sandbox-net-test",
        publish_port=False,
        extra_environment={"HTTP_PROXY": "http://deer-flow-netproxy-test:3128"},
    )

    assert "-p" not in captured_cmd
    assert captured_cmd[captured_cmd.index("--network") + 1] == "deer-flow-sandbox-net-test"
    proxy_values = [captured_cmd[index + 1] for index, value in enumerate(captured_cmd) if value == "-e" and captured_cmd[index + 1].startswith("HTTP_PROXY=")]
    assert proxy_values[-1] == "HTTP_PROXY=http://deer-flow-netproxy-test:3128"


def test_restricted_start_configures_shell_and_aio_browser_proxy(monkeypatch):
    backend = LocalContainerBackend(
        image="sandbox:latest",
        base_port=8080,
        container_prefix="sandbox",
        config_mounts=[],
        environment={},
    )
    backend._network_mode = "allowlist"
    monkeypatch.setattr(backend, "_restricted_resources_status", lambda _sandbox_id: "missing")
    monkeypatch.setattr(backend, "_create_internal_network", lambda _name, _sandbox_id: None)
    monkeypatch.setattr(backend, "_create_egress_network", lambda _name, _sandbox_id: None)
    monkeypatch.setattr(backend, "_start_network_proxy", lambda *_args: None)
    captured: dict[str, object] = {}

    def fake_start(*_args, **kwargs):
        captured.update(kwargs)
        return "container-id"

    monkeypatch.setattr(backend, "_start_container", fake_start)

    assert (
        backend._start_restricted_sandbox(
            "id",
            "sandbox-id",
            18080,
            None,
            config_mount_exclusion_root=None,
            relay_token="test-relay-token",
        )
        == "container-id"
    )

    proxy_name, network_name = backend._resource_names("id")
    assert captured["network_override"] == network_name
    assert captured["publish_port"] is False
    environment = captured["extra_environment"]
    assert environment["HTTPS_PROXY"] == f"http://{proxy_name}:3128"
    assert environment["ALL_PROXY"] == f"http://{proxy_name}:3128"
    assert environment["PROXY_SERVER"] == f"{proxy_name}:3128"


def test_restricted_start_refuses_to_remove_resources_with_stale_policy(monkeypatch):
    backend = _restricted_backend()
    cleaned: list[str] = []
    created: list[tuple[str, str]] = []
    monkeypatch.setattr(backend, "_restricted_resources_status", lambda _sandbox_id: "mismatch")
    monkeypatch.setattr(backend, "_cleanup_restricted_resources", cleaned.append)
    monkeypatch.setattr(backend, "_create_internal_network", lambda name, sandbox_id: created.append((name, sandbox_id)))
    monkeypatch.setattr(backend, "_create_egress_network", lambda name, sandbox_id: created.append((name, sandbox_id)))
    monkeypatch.setattr(backend, "_start_network_proxy", lambda *_args: None)
    monkeypatch.setattr(backend, "_start_container", lambda *_args, **_kwargs: "container-id")

    with pytest.raises(RuntimeError, match="requires ownership-fenced replacement"):
        backend._start_restricted_sandbox(
            "stale",
            "sandbox-stale",
            18080,
            None,
            config_mount_exclusion_root=None,
            relay_token="test-relay-token",
        )

    assert cleaned == []
    assert created == []


def test_network_proxy_uses_read_only_root_and_bounded_policy_storage(monkeypatch):
    backend = LocalContainerBackend(
        image="sandbox:latest",
        base_port=8080,
        container_prefix="sandbox",
        config_mounts=[],
        environment={},
    )
    backend._network_mode = "allowlist"
    backend._network_config = {
        "mode": "allowlist",
        "allow_domains": [],
        "approval": "prompt",
        "proxy_image": "proxy:latest",
    }
    commands: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        commands.append(cmd)
        return SimpleNamespace(stdout="proxy-id\n", stderr="", returncode=0)

    monkeypatch.setattr("subprocess.run", fake_run)

    backend._start_network_proxy(
        "proxy-name",
        "network-name",
        "egress-network-name",
        "sandbox-name",
        18080,
        "sandbox-id",
        "test-relay-token",
    )

    create = commands[0]
    assert create[create.index("--network") + 1] == "egress-network-name"
    assert "bridge" not in create
    assert "--read-only" in create
    assert create[create.index("--tmpfs") + 1] == "/tmp:rw,noexec,nosuid,size=16m"
    assert "--cap-drop=ALL" in create
    assert "no-new-privileges" in create
    assert "DEERFLOW_RELAY_TOKEN=test-relay-token" in create


def test_start_container_filters_nested_config_mounts_for_policy_scoped_skills(
    monkeypatch,
):
    backend = LocalContainerBackend(
        image="sandbox:latest",
        base_port=8080,
        container_prefix="sandbox",
        config_mounts=[
            SimpleNamespace(
                host_path="/host/excluded-skill",
                container_path="/mnt/skills/public/excluded-skill",
                read_only=True,
            ),
            SimpleNamespace(
                host_path="/host/unrelated",
                container_path="/mnt/unrelated",
                read_only=True,
            ),
            SimpleNamespace(
                host_path="/host/sibling",
                container_path="/mnt/skills-extra",
                read_only=True,
            ),
        ],
        environment={},
    )
    monkeypatch.setattr(backend, "_runtime", "docker")
    captured_cmd: list[str] = []

    def fake_run(cmd, **kwargs):
        captured_cmd.extend(cmd)
        return SimpleNamespace(stdout="container-id\n", stderr="", returncode=0)

    monkeypatch.setattr("subprocess.run", fake_run)

    backend._start_container(
        "sandbox-test",
        18080,
        extra_mounts=[
            (
                "/host/thread-view/public",
                "/mnt/skills/public",
                True,
            )
        ],
        config_mount_exclusion_root="/mnt/skills",
    )

    command = " ".join(captured_cmd)
    assert "/host/excluded-skill" not in command
    assert "/host/unrelated" in command
    assert "/host/sibling" in command
    assert "/host/thread-view/public" in command


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
        "deerflow.community.aio_sandbox.local_backend._docker_server_is_desktop",
        lambda: False,
    )
    monkeypatch.setattr(
        "deerflow.community.aio_sandbox.local_backend._resolve_sandbox_host_address",
        lambda host: "192.168.64.1",
    )

    assert _resolve_docker_bind_host() == "192.168.64.1"


@pytest.mark.parametrize(
    "sandbox_host",
    [
        "host.docker.internal",
        "gateway.docker.internal",
        "Host.Docker.Internal.",
        "docker.for.mac.host.internal",
        "docker.for.win.localhost",
    ],
)
def test_resolve_docker_bind_host_uses_loopback_on_docker_desktop(monkeypatch, sandbox_host):
    """Docker Desktop cannot bind to internal VM gateway IPs, so default to 127.0.0.1."""
    monkeypatch.delenv("DEER_FLOW_SANDBOX_BIND_HOST", raising=False)
    monkeypatch.setenv("DEER_FLOW_SANDBOX_HOST", sandbox_host)
    monkeypatch.setattr(
        "deerflow.community.aio_sandbox.local_backend._docker_server_is_desktop",
        lambda: True,
    )
    monkeypatch.setattr(
        "deerflow.community.aio_sandbox.local_backend._resolve_sandbox_host_address",
        lambda host: "192.168.65.254",
    )

    assert _resolve_docker_bind_host() == "127.0.0.1"


def test_resolve_docker_bind_host_preserves_custom_host_on_docker_desktop(monkeypatch):
    """Custom non-loopback sandbox host on Docker Desktop binds the resolved address."""
    monkeypatch.delenv("DEER_FLOW_SANDBOX_BIND_HOST", raising=False)
    monkeypatch.setenv("DEER_FLOW_SANDBOX_HOST", "desktop-box")
    monkeypatch.setattr(
        "deerflow.community.aio_sandbox.local_backend._docker_server_is_desktop",
        lambda: True,
    )
    monkeypatch.setattr(
        "deerflow.community.aio_sandbox.local_backend._resolve_sandbox_host_address",
        lambda host: "192.0.2.55",
    )

    assert _resolve_docker_bind_host() == "192.0.2.55"


def test_resolve_docker_bind_host_explicit_override_precedes_desktop_detection(monkeypatch):
    """Explicit DEER_FLOW_SANDBOX_BIND_HOST takes precedence even on Docker Desktop."""
    monkeypatch.setenv("DEER_FLOW_SANDBOX_BIND_HOST", "192.0.2.10")
    monkeypatch.setenv("DEER_FLOW_SANDBOX_HOST", "host.docker.internal")
    monkeypatch.setattr(
        "deerflow.community.aio_sandbox.local_backend._docker_server_is_desktop",
        lambda: True,
    )

    assert _resolve_docker_bind_host() == "192.0.2.10"


def test_resolve_docker_bind_host_brackets_ipv6_host_gateway(monkeypatch):
    """An IPv6 host-gateway mapping binds the bracketed IPv6 address."""
    monkeypatch.delenv("DEER_FLOW_SANDBOX_BIND_HOST", raising=False)
    monkeypatch.setenv("DEER_FLOW_SANDBOX_HOST", "host.docker.internal")
    monkeypatch.setattr(
        "deerflow.community.aio_sandbox.local_backend._docker_server_is_desktop",
        lambda: False,
    )
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

    # IPv4 literals pass through unchanged.
    monkeypatch.setenv("DEER_FLOW_SANDBOX_BIND_HOST", "192.168.64.1")
    assert _resolve_docker_bind_host() == "192.168.64.1"
    monkeypatch.setenv("DEER_FLOW_SANDBOX_BIND_HOST", "0.0.0.0")
    assert _resolve_docker_bind_host() == "0.0.0.0"


def test_resolve_docker_bind_host_resolves_hostname_override(monkeypatch):
    """-p requires an IP literal as the host part, so a hostname override
    resolves to the address the daemon actually maps before use."""
    monkeypatch.setenv("DEER_FLOW_SANDBOX_BIND_HOST", "host.docker.internal")
    monkeypatch.setattr(
        "deerflow.community.aio_sandbox.local_backend._resolve_sandbox_host_address",
        lambda host: "192.168.64.1" if host == "host.docker.internal" else None,
    )
    assert _resolve_docker_bind_host() == "192.168.64.1"


def test_resolve_docker_bind_host_rejects_unresolvable_hostname_override(monkeypatch):
    monkeypatch.setenv("DEER_FLOW_SANDBOX_BIND_HOST", "not-a-resolvable-host.invalid")
    monkeypatch.setattr(
        "deerflow.community.aio_sandbox.local_backend._resolve_sandbox_host_address",
        lambda host: None,
    )
    with pytest.raises(RuntimeError, match="DEER_FLOW_SANDBOX_BIND_HOST"):
        _resolve_docker_bind_host()


def test_resolve_docker_bind_host_uses_discovered_bridge_gateway_when_resolution_fails(monkeypatch):
    monkeypatch.delenv("DEER_FLOW_SANDBOX_BIND_HOST", raising=False)
    monkeypatch.setenv("DEER_FLOW_SANDBOX_HOST", "host.docker.internal")
    monkeypatch.setattr(
        "deerflow.community.aio_sandbox.local_backend._docker_server_is_desktop",
        lambda: False,
    )
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
        "deerflow.community.aio_sandbox.local_backend._docker_server_is_desktop",
        lambda: False,
    )
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
        "DEER_FLOW_SANDBOX_IMAGE_STARTUP_CAPS",
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
    """Force resolver failure so host DNS cannot bypass the bridge-gateway fallback."""
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
        "deerflow.community.aio_sandbox.local_backend._resolve_sandbox_host_address",
        lambda host: None,
    )
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
    # The shipped image's entrypoint starts as root, creates the gem user,
    # chowns /opt/jupyter, prepares /run/user/1000 with chmod, and drops to
    # that user via su. CHOWN/FOWNER/SETUID/SETGID must survive the drop or
    # the container exits before readiness. The root nginx master also writes
    # gem-owned logs under /var/log/nginx for the container's lifetime, which
    # needs DAC_OVERRIDE.
    cap_adds = [arg.split("=", 1)[1] for arg in captured_cmd if arg.startswith("--cap-add=")]
    assert cap_adds == ["CHOWN", "FOWNER", "SETUID", "SETGID", "DAC_OVERRIDE"]
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
    # The opt-out must select the built-in profile explicitly: omitting the
    # option would inherit the daemon's (possibly unconfined) default.
    assert "seccomp=builtin" in security_opts
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


def test_start_container_rejects_host_networking(monkeypatch):
    """host mode discards -p/--publish, voiding the hardened bind and
    re-exposing the unauthenticated exec API on the host's interfaces."""
    backend = LocalContainerBackend(
        image="sandbox:latest",
        base_port=8080,
        container_prefix="sandbox",
        config_mounts=[],
        environment={},
    )
    _clear_hardening_env(monkeypatch)
    monkeypatch.setenv("DEER_FLOW_SANDBOX_NETWORK", "host")

    with pytest.raises(RuntimeError, match="DEER_FLOW_SANDBOX_NETWORK"):
        _capture_start_container_command(monkeypatch, backend)


def test_start_container_rejects_shared_container_network_namespace(monkeypatch):
    backend = LocalContainerBackend(
        image="sandbox:latest",
        base_port=8080,
        container_prefix="sandbox",
        config_mounts=[],
        environment={},
    )
    _clear_hardening_env(monkeypatch)
    monkeypatch.setenv("DEER_FLOW_SANDBOX_NETWORK", "container:gateway")

    with pytest.raises(RuntimeError, match="DEER_FLOW_SANDBOX_NETWORK"):
        _capture_start_container_command(monkeypatch, backend)


def test_start_container_rejects_none_network(monkeypatch):
    """The none driver leaves the container loopback-only, so the published
    sandbox API port cannot receive traffic: readiness would time out and
    every acquisition would fail. Fail fast at start-up instead."""
    backend = LocalContainerBackend(
        image="sandbox:latest",
        base_port=8080,
        container_prefix="sandbox",
        config_mounts=[],
        environment={},
    )
    _clear_hardening_env(monkeypatch)
    monkeypatch.setenv("DEER_FLOW_SANDBOX_NETWORK", "none")

    with pytest.raises(RuntimeError, match="loopback-only"):
        _capture_start_container_command(monkeypatch, backend)


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


def test_discover_replaces_container_with_insufficient_shell_capacity(monkeypatch):
    backend = _backend_for_inspect_tests()
    backend._environment["MAX_SHELL_SESSIONS"] = "13"
    container_name = "sandbox-existing"
    monkeypatch.setattr(backend, "_is_container_running", lambda _name: True)
    monkeypatch.setattr(
        backend,
        "_batch_inspect",
        lambda *_args, **_kwargs: {
            container_name: _ContainerInspection(
                created_at=1.0,
                host_port=18080,
                labels={
                    "deerflow.role": "sandbox",
                    "deerflow.sandbox_id": "existing",
                    "deerflow.network_mode": "open",
                },
                image="sandbox:latest",
                networks=frozenset({"bridge"}),
                max_shell_sessions=10,
            )
        },
    )

    info = backend.discover("existing")

    assert info is not None
    assert info.requires_replacement is True
    assert info.sandbox_url == ""


def test_list_running_marks_insufficient_shell_capacity_for_fenced_replacement(monkeypatch):
    backend = _backend_for_inspect_tests()
    backend._environment["MAX_SHELL_SESSIONS"] = "13"
    container_name = "sandbox-existing"

    def fake_run(cmd, **kwargs):
        assert cmd[:2] == ["docker", "ps"]
        return SimpleNamespace(stdout=f"{container_name}\n", stderr="", returncode=0)

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr(
        backend,
        "_batch_inspect",
        lambda *_args, **_kwargs: {
            container_name: _ContainerInspection(
                created_at=1.0,
                host_port=18080,
                labels={
                    "deerflow.role": "sandbox",
                    "deerflow.sandbox_id": "existing",
                    "deerflow.network_mode": "open",
                },
                image="sandbox:latest",
                networks=frozenset({"bridge"}),
                max_shell_sessions=10,
            )
        },
    )

    infos = backend.list_running()

    assert len(infos) == 1
    assert infos[0].requires_replacement is True
    assert infos[0].sandbox_url == ""


def test_restricted_discovery_uses_proxy_relay_port(monkeypatch):
    backend = _backend_for_inspect_tests()
    backend._network_mode = "allowlist"
    container_name = "sandbox-existing"
    proxy_name, _ = backend._resource_names("existing")
    monkeypatch.setattr(backend, "_is_container_running", lambda _name: True)
    inspections = {
        container_name: _ContainerInspection(
            1.0,
            None,
            {
                "deerflow.role": "sandbox",
                "deerflow.sandbox_id": "existing",
                "deerflow.network_mode": "allowlist",
            },
            "sandbox:latest",
            frozenset(),
        ),
        proxy_name: _ContainerInspection(
            1.0,
            18080,
            {},
            "proxy:latest",
            frozenset(),
            "test-relay-token-that-is-at-least-32-bytes",
        ),
    }
    monkeypatch.setattr(backend, "_batch_inspect", lambda *_args, **_kwargs: inspections)
    monkeypatch.setattr(backend, "_restricted_resources_status", lambda _sandbox_id, **_kwargs: "compatible")
    readiness: list[dict[str, object]] = []

    def fake_ready(_url, **kwargs):
        readiness.append(kwargs)
        return True

    monkeypatch.setattr("deerflow.community.aio_sandbox.local_backend.wait_for_sandbox_ready", fake_ready)

    info = backend.discover("existing")

    assert info is not None
    assert info.container_name == "sandbox-existing"
    assert info.sandbox_url == "http://localhost:18080"
    assert info.request_headers == {"X-DeerFlow-Relay-Token": "test-relay-token-that-is-at-least-32-bytes"}
    assert readiness == [{"timeout": 5, "headers": info.request_headers}]


def test_restricted_discovery_reports_stale_policy_without_removing_resources(monkeypatch):
    backend = _backend_for_inspect_tests()
    backend._network_mode = "allowlist"
    cleaned: list[str] = []
    container_name = "sandbox-stale"
    monkeypatch.setattr(backend, "_is_container_running", lambda _name: True)
    monkeypatch.setattr(
        backend,
        "_batch_inspect",
        lambda *_args, **_kwargs: {
            container_name: _ContainerInspection(
                1.0,
                None,
                {
                    "deerflow.role": "sandbox",
                    "deerflow.sandbox_id": "stale",
                    "deerflow.network_mode": "allowlist",
                },
                "sandbox:latest",
                frozenset(),
            )
        },
    )
    monkeypatch.setattr(backend, "_restricted_resources_status", lambda _sandbox_id, **_kwargs: "mismatch")
    monkeypatch.setattr(backend, "_cleanup_restricted_resources", cleaned.append)

    info = backend.discover("stale")

    assert info is not None
    assert info.sandbox_id == "stale"
    assert info.container_name == "sandbox-stale"
    assert info.requires_replacement is True
    assert cleaned == []


def test_restricted_discovery_reports_legacy_open_sandbox_for_fenced_replacement(monkeypatch):
    backend = _restricted_backend()
    container_name = "sandbox-legacy-open"
    inspected_batches: list[list[str]] = []
    monkeypatch.setattr(backend, "_is_container_running", lambda _name: True)

    def fake_batch_inspect(names, **_kwargs):
        inspected_batches.append(list(names))
        return {
            container_name: _ContainerInspection(
                1.0,
                18080,
                {},
                "sandbox:latest",
                frozenset({"bridge"}),
            )
        }

    monkeypatch.setattr(backend, "_batch_inspect", fake_batch_inspect)

    info = backend.discover("legacy-open")

    assert info is not None
    assert info.requires_replacement is True
    assert info.sandbox_url == ""
    assert inspected_batches == [[container_name]]


def test_restricted_discovery_reports_labelled_open_sandbox_for_fenced_replacement(monkeypatch):
    backend = _restricted_backend()
    container_name = "sandbox-labelled-open"
    monkeypatch.setattr(backend, "_is_container_running", lambda _name: True)
    monkeypatch.setattr(
        backend,
        "_batch_inspect",
        lambda *_args, **_kwargs: {
            container_name: _ContainerInspection(
                1.0,
                18080,
                {
                    "deerflow.role": "sandbox",
                    "deerflow.sandbox_id": "labelled-open",
                    "deerflow.network_mode": "open",
                },
                "sandbox:latest",
                frozenset({"bridge"}),
            )
        },
    )
    monkeypatch.setattr(
        backend,
        "_restricted_resources_status",
        lambda *_args, **_kwargs: pytest.fail("a mode mismatch must be reported before restricted resource inspection"),
    )

    info = backend.discover("labelled-open")

    assert info is not None
    assert info.requires_replacement is True
    assert info.sandbox_url == ""


def test_open_discovery_reports_restricted_sandbox_for_fenced_replacement(monkeypatch):
    backend = _backend_for_inspect_tests()
    container_name = "sandbox-old-restricted"
    monkeypatch.setattr(backend, "_is_container_running", lambda _name: True)
    monkeypatch.setattr(
        backend,
        "_batch_inspect",
        lambda *_args, **_kwargs: {
            container_name: _ContainerInspection(
                1.0,
                None,
                {
                    "deerflow.role": "sandbox",
                    "deerflow.sandbox_id": "old-restricted",
                    "deerflow.network_mode": "allowlist",
                },
                "sandbox:latest",
                frozenset({"deer-flow-sandbox-net-old"}),
            )
        },
    )

    info = backend.discover("old-restricted")

    assert info is not None
    assert info.requires_replacement is True
    assert info.sandbox_url == ""


def test_restricted_discovery_leaves_unlabelled_name_collision_unmanaged(monkeypatch):
    backend = _backend_for_inspect_tests()
    backend._network_mode = "allowlist"
    container_name = "sandbox-foreign"
    cleaned: list[str] = []
    monkeypatch.setattr(backend, "_is_container_running", lambda _name: True)
    monkeypatch.setattr(
        backend,
        "_batch_inspect",
        lambda *_args, **_kwargs: {
            container_name: _ContainerInspection(
                1.0,
                None,
                {},
                "foreign:latest",
                frozenset(),
            )
        },
    )
    monkeypatch.setattr(backend, "_restricted_resources_status", lambda _sandbox_id, **_kwargs: "mismatch")
    monkeypatch.setattr(backend, "_cleanup_restricted_resources", cleaned.append)

    assert backend.discover("foreign") is None
    assert cleaned == []


def test_restricted_discovery_leaves_unlabelled_published_foreign_image_unmanaged(monkeypatch):
    backend = _restricted_backend()
    container_name = "sandbox-foreign-published"
    monkeypatch.setattr(backend, "_is_container_running", lambda _name: True)
    monkeypatch.setattr(
        backend,
        "_batch_inspect",
        lambda *_args, **_kwargs: {
            container_name: _ContainerInspection(
                1.0,
                18080,
                {},
                "foreign:latest",
                frozenset({"bridge"}),
            )
        },
    )

    assert backend.discover("foreign-published") is None


def test_restricted_health_rejects_resources_with_stale_policy(monkeypatch):
    backend = _backend_for_inspect_tests()
    backend._network_mode = "allowlist"
    monkeypatch.setattr(backend, "_is_container_running", lambda _name: True)
    monkeypatch.setattr(backend, "_restricted_resources_status", lambda _sandbox_id: "mismatch")

    assert not backend.is_alive(
        SandboxInfo(
            sandbox_id="stale",
            sandbox_url="http://localhost:18080",
            container_name="sandbox-stale",
        )
    )


def test_restricted_list_reconciliation_reports_stale_policy_without_removing_resources(monkeypatch):
    backend = _backend_for_inspect_tests()
    backend._network_mode = "allowlist"
    proxy_name, _ = backend._resource_names("stale")
    cleaned: list[str] = []
    monkeypatch.setattr(
        "subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout="sandbox-stale\n", stderr="", returncode=0),
    )
    monkeypatch.setattr(
        backend,
        "_batch_inspect",
        lambda _names, **_kwargs: {
            "sandbox-stale": _ContainerInspection(
                1.0,
                None,
                {
                    "deerflow.role": "sandbox",
                    "deerflow.sandbox_id": "stale",
                    "deerflow.network_mode": "allowlist",
                },
                "sandbox:latest",
                frozenset(),
            ),
            proxy_name: _ContainerInspection(
                1.0,
                18080,
                {"deerflow.role": "network-proxy", "deerflow.sandbox_id": "stale"},
                "proxy:latest",
                frozenset(),
            ),
        },
    )
    monkeypatch.setattr(backend, "_restricted_resources_status", lambda _sandbox_id, **_kwargs: "mismatch")
    monkeypatch.setattr(backend, "_cleanup_restricted_resources", cleaned.append)

    infos = backend.list_running()

    assert len(infos) == 1
    assert infos[0].sandbox_id == "stale"
    assert infos[0].requires_replacement is True
    assert cleaned == []


def test_restricted_list_reports_legacy_open_sandbox_for_fenced_replacement(monkeypatch):
    backend = _restricted_backend()
    commands: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        commands.append(cmd)
        return SimpleNamespace(stdout="sandbox-legacy-open\n", stderr="", returncode=0)

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr(
        backend,
        "_batch_inspect",
        lambda _names, **_kwargs: {
            "sandbox-legacy-open": _ContainerInspection(
                1.0,
                18080,
                {},
                "sandbox:latest",
                frozenset({"bridge"}),
            )
        },
    )

    infos = backend.list_running()

    assert len(infos) == 1
    assert infos[0].requires_replacement is True
    assert infos[0].sandbox_url == ""
    assert "label=deerflow.role=sandbox" not in commands[0]


def test_open_list_reports_restricted_sandbox_for_fenced_replacement(monkeypatch):
    backend = _backend_for_inspect_tests()
    monkeypatch.setattr(
        "subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout="sandbox-old-restricted\n", stderr="", returncode=0),
    )
    monkeypatch.setattr(
        backend,
        "_batch_inspect",
        lambda _names, **_kwargs: {
            "sandbox-old-restricted": _ContainerInspection(
                1.0,
                None,
                {
                    "deerflow.role": "sandbox",
                    "deerflow.sandbox_id": "old-restricted",
                    "deerflow.network_mode": "isolated",
                },
                "sandbox:latest",
                frozenset({"deer-flow-sandbox-net-old"}),
            )
        },
    )

    infos = backend.list_running()

    assert len(infos) == 1
    assert infos[0].requires_replacement is True
    assert infos[0].sandbox_url == ""


def test_restricted_list_running_excludes_sidecars_for_overlapping_custom_prefix(monkeypatch):
    backend = _backend_for_inspect_tests()
    backend._network_mode = "allowlist"
    backend._container_prefix = "deer-flow"
    sandbox_id = "live"
    sandbox_name = "deer-flow-live"
    proxy_name, _ = backend._resource_names(sandbox_id)
    commands: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        commands.append(cmd)
        return SimpleNamespace(
            stdout=f"{sandbox_name}\n{proxy_name}\n",
            stderr="",
            returncode=0,
        )

    monkeypatch.setattr("subprocess.run", fake_run)
    inspected_batches: list[list[str]] = []

    def fake_batch_inspect(names, **_kwargs):
        inspected_batches.append(list(names))
        return {
            sandbox_name: _ContainerInspection(
                1.0,
                None,
                {
                    "deerflow.role": "sandbox",
                    "deerflow.sandbox_id": sandbox_id,
                    "deerflow.network_mode": "allowlist",
                },
                "sandbox:latest",
                frozenset(),
            ),
            proxy_name: _ContainerInspection(
                1.0,
                18080,
                {"deerflow.role": "network-proxy", "deerflow.sandbox_id": sandbox_id},
                "proxy:latest",
                frozenset(),
                "test-relay-token-that-is-at-least-32-bytes",
            ),
        }

    monkeypatch.setattr(backend, "_batch_inspect", fake_batch_inspect)
    checked: list[str] = []

    def compatible(current_sandbox_id, **_kwargs):
        checked.append(current_sandbox_id)
        return "compatible"

    monkeypatch.setattr(backend, "_restricted_resources_status", compatible)

    infos = backend.list_running()

    assert [info.sandbox_id for info in infos] == [sandbox_id]
    assert checked == [sandbox_id]
    assert "label=deerflow.role=sandbox" not in commands[0]
    sidecar_as_sandbox_id = proxy_name[len(backend._container_prefix) + 1 :]
    fabricated_proxy_name, _ = backend._resource_names(sidecar_as_sandbox_id)
    assert fabricated_proxy_name not in {name for batch in inspected_batches for name in batch}


def test_restricted_destroy_stops_pair_and_removes_both_networks(monkeypatch):
    backend = _backend_for_inspect_tests()
    backend._network_mode = "isolated"
    proxy_name, network_name = backend._resource_names("existing")
    egress_network_name = backend._egress_network_name("existing")
    stopped: list[str] = []
    commands: list[list[str]] = []
    monkeypatch.setattr(backend, "_stop_container", stopped.append)

    def fake_run(cmd, **_kwargs):
        commands.append(cmd)
        return SimpleNamespace(stdout="", stderr="", returncode=0)

    monkeypatch.setattr("subprocess.run", fake_run)
    backend.destroy(
        SandboxInfo(
            sandbox_id="existing",
            sandbox_url="http://localhost:18080",
            container_name="sandbox-existing",
            container_id="sandbox-container-id",
        )
    )

    assert stopped == [proxy_name, "sandbox-container-id"]
    assert ["docker", "rm", "-f", proxy_name] in commands
    assert ["docker", "network", "rm", network_name] in commands
    assert ["docker", "network", "rm", egress_network_name] in commands


def test_open_mode_replacement_destroy_removes_restricted_sidecar_and_networks(monkeypatch):
    backend = _backend_for_inspect_tests()
    stopped: list[str] = []
    cleaned: list[tuple[str, bool, bool]] = []
    monkeypatch.setattr(backend, "_stop_container", stopped.append)
    monkeypatch.setattr(backend, "_remove_restricted_proxy", lambda sandbox_id: cleaned.append((sandbox_id, False, True)))
    monkeypatch.setattr(
        backend,
        "_cleanup_restricted_resources",
        lambda sandbox_id, *, stop_sandbox=True, remove_proxy=True: cleaned.append((sandbox_id, stop_sandbox, remove_proxy)),
    )

    backend.destroy(
        SandboxInfo(
            sandbox_id="old-restricted",
            sandbox_url="",
            container_name="sandbox-old-restricted",
            requires_replacement=True,
        )
    )

    assert stopped == ["sandbox-old-restricted"]
    assert cleaned == [("old-restricted", False, True), ("old-restricted", False, False)]


def test_deny_pending_network_policy_events_uses_atomic_proxy_command(monkeypatch):
    backend = _restricted_backend()
    commands: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        commands.append(cmd)
        return SimpleNamespace(stdout="17\n", stderr="", returncode=0)

    monkeypatch.setattr("subprocess.run", fake_run)

    assert backend.deny_pending_network_policy_events("existing") is True
    proxy_name, _ = backend._resource_names("existing")
    assert commands == [["docker", "exec", proxy_name, "python", "/tmp/deerflow-network-proxy.py", "deny-pending"]]


def test_is_container_running_false_on_apple_container_not_found(monkeypatch):
    """Apple Container's generic "not found" is trusted when it names the container."""
    backend = _backend_for_inspect_tests()
    backend._runtime = "container"

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


@pytest.mark.parametrize("runtime", ["docker", "container"])
def test_absence_does_not_treat_stopped_container_as_missing(monkeypatch, runtime):
    backend = _backend_for_inspect_tests()
    backend._runtime = runtime
    name = "sandbox-stopped"
    entry = {"Name": f"/{name}", "Id": "stopped-generation", "State": {"Running": False}} if runtime == "docker" else {"configuration": {"id": name}, "status": "stopped"}
    monkeypatch.setattr("subprocess.run", lambda *_args, **_kwargs: SimpleNamespace(stdout=json.dumps([entry]), stderr="", returncode=0))
    assert backend.is_absent("stopped") is False


@pytest.mark.parametrize("runtime", ["docker", "container"])
def test_absence_requires_runtime_confirmation(monkeypatch, runtime):
    backend = _backend_for_inspect_tests()
    backend._runtime = runtime
    name = f"{backend._container_prefix}-missing"
    error = f"Error: No such container: {name}" if runtime == "docker" else f'Error: not found: "{name}"'
    monkeypatch.setattr("subprocess.run", lambda *_args, **_kwargs: SimpleNamespace(stdout="", stderr=error, returncode=1))
    assert backend.is_absent("missing") is True
    monkeypatch.setattr("subprocess.run", lambda *_args, **_kwargs: SimpleNamespace(stdout="", stderr="daemon unavailable", returncode=1))
    with pytest.raises(RuntimeError):
        backend.is_absent("missing")


@pytest.mark.parametrize("operation", ["is_absent", "_is_container_running", "_stop_container"])
@pytest.mark.parametrize(
    "error",
    [
        'Failed to initialize: unable to resolve docker endpoint: context "deerflow-container-review-missing": context not found: open /synthetic-home/.docker/contexts/meta/context/meta.json: no such file or directory',
        'unable to resolve docker endpoint: context "sandbox-missing": context not found',
        "Error: container runtime not found while inspecting sandbox-missing",
        "OCI runtime failed for container sandbox-missing: executable file not found in $PATH",
        "Error: No such object: sandbox-other",
        "Error response from daemon: No such container: sandbox-missing-extra",
    ],
)
def test_runtime_absence_rejects_errors_not_about_the_requested_container(monkeypatch, operation, error):
    backend = _backend_for_inspect_tests()

    def failed(cmd, **kwargs):
        if kwargs.get("check"):
            raise subprocess.CalledProcessError(1, cmd, stderr=error)
        return SimpleNamespace(stdout="", stderr=error, returncode=1)

    monkeypatch.setattr("subprocess.run", failed)
    target = "missing" if operation == "is_absent" else "sandbox-missing"
    with pytest.raises((RuntimeError, subprocess.CalledProcessError)):
        getattr(backend, operation)(target)


@pytest.mark.parametrize("operation", ["is_absent", "_is_container_running", "_stop_container"])
@pytest.mark.parametrize(
    ("runtime", "error"),
    [
        ("docker", "Error: No such object: sandbox-missing"),
        ("docker", "Error response from daemon: No such container: sandbox-missing"),
        # ArgumentParser prefers ContainerizationError.errorDescription, so
        # ContainerInspect's missing-resource message has no type or quotes.
        ("container", "Error: container not found: sandbox-missing"),
        ("container", 'Error: notFound: "container not found: sandbox-missing"'),
        ("container", 'Error: not found: "sandbox-missing"'),
    ],
)
def test_runtime_absence_accepts_exact_missing_container_responses(monkeypatch, operation, runtime, error):
    backend = _backend_for_inspect_tests()
    backend._runtime = runtime

    def missing(cmd, **kwargs):
        if kwargs.get("check"):
            raise subprocess.CalledProcessError(1, cmd, stderr=error)
        return SimpleNamespace(stdout="[]", stderr=error, returncode=1)

    monkeypatch.setattr("subprocess.run", missing)
    target = "missing" if operation == "is_absent" else "sandbox-missing"
    result = getattr(backend, operation)(target)
    assert result is (True if operation == "is_absent" else False if operation == "_is_container_running" else None)


@pytest.mark.parametrize("state", ["created", "exited", "running", "dead"])
def test_inspect_runtime_observes_docker_generation_without_health_or_port(monkeypatch, state):
    backend = _backend_for_inspect_tests()
    commands = []
    entry = {"Id": "immutable-docker-generation", "Name": "/sandbox-existing", "Created": "2026-04-08T01:22:50Z", "State": {"Status": state, "Running": state == "running"}}

    def inspect(cmd, **kwargs):
        commands.append(cmd)
        assert 0 < kwargs["timeout"] <= 15
        return SimpleNamespace(stdout=json.dumps([entry]), stderr="", returncode=0)

    monkeypatch.setattr("subprocess.run", inspect)
    monkeypatch.setattr(backend, "_is_container_running", lambda *_args: pytest.fail("runtime inspection must not require running"))
    monkeypatch.setattr(backend, "_get_container_port", lambda *_args: pytest.fail("runtime inspection must not require a port"))
    monkeypatch.setattr(local_backend_module, "wait_for_sandbox_ready", lambda *_args, **_kwargs: pytest.fail("runtime inspection must not require health"))

    info = backend.inspect_runtime("existing")

    assert info is not None
    assert info.sandbox_id == "existing"
    assert info.container_name == "sandbox-existing"
    assert info.container_id == "immutable-docker-generation"
    assert info.created_at == 1775611370.0
    assert commands == [["docker", "inspect", "sandbox-existing"]]


def test_inspect_runtime_keeps_apple_resource_with_unknown_generation(monkeypatch):
    backend = _backend_for_inspect_tests()
    backend._runtime = "container"
    # ManagedContainer serializes configuration.id, which is the user-selected
    # logical name rather than an immutable generation; it cannot fence teardown.
    entry = {"id": "sandbox-existing", "configuration": {"id": "sandbox-existing"}, "status": {"state": "stopped"}}
    monkeypatch.setattr("subprocess.run", lambda *_args, **_kwargs: SimpleNamespace(stdout=json.dumps([entry]), stderr="", returncode=0))

    info = backend.inspect_runtime("existing")

    assert info is not None
    assert info.container_name == "sandbox-existing"
    assert info.container_id is None
    assert backend.is_absent("existing") is False


@pytest.mark.parametrize("stopped", [False, True])
def test_destroy_retry_releases_port_recovered_from_runtime_metadata(monkeypatch, stopped):
    from deerflow.utils.network import PortAllocator

    backend = _backend_for_inspect_tests()
    allocator = PortAllocator()
    monkeypatch.setattr(allocator, "_is_port_available", lambda port: port not in allocator._reserved_ports)
    port = allocator.allocate(18080, max_range=1)
    monkeypatch.setattr(local_backend_module, "release_port", allocator.release)
    entry = {
        "Id": "retained-generation",
        "Name": "/sandbox-existing",
        "NetworkSettings": {"Ports": {"8080/tcp": None if stopped else [{"HostPort": str(port)}]}},
        "HostConfig": {"PortBindings": {"8080/tcp": [{"HostPort": str(port)}]}},
    }
    failed = True

    def runtime(cmd, **kwargs):
        nonlocal failed
        if "inspect" in cmd:
            return SimpleNamespace(stdout=json.dumps([entry]), stderr="", returncode=0)
        if failed:
            failed = False
            raise subprocess.CalledProcessError(1, cmd, stderr="daemon denied stop")
        return SimpleNamespace(stdout="", stderr="", returncode=0)

    monkeypatch.setattr("subprocess.run", runtime)
    original = SandboxInfo("existing", f"http://localhost:{port}", container_id="retained-generation")
    with pytest.raises(subprocess.CalledProcessError):
        backend.destroy(original)
    with pytest.raises(RuntimeError, match="No available port"):
        allocator.allocate(18080, max_range=1)

    recovered = backend.inspect_runtime("existing")
    assert recovered is not None
    backend.destroy(recovered)
    assert allocator.allocate(18080, max_range=1) == port


@pytest.mark.parametrize("proxy_missing", [False, True])
@pytest.mark.parametrize("persisted_mode", ["allowlist", "isolated"])
def test_inspect_runtime_recovers_restricted_proxy_port_without_losing_main_identity(monkeypatch, proxy_missing, persisted_mode):
    backend = _backend_for_inspect_tests()
    proxy_name, _ = backend._resource_names("existing")
    entry = {"Id": "main-generation", "Name": "/sandbox-existing", "Config": {"Labels": {"deerflow.network_mode": persisted_mode}}}
    proxy = {"Id": "proxy-generation", "Name": f"/{proxy_name}", "HostConfig": {"PortBindings": {"8080/tcp": [{"HostPort": "18080"}]}}}

    def runtime(cmd, **kwargs):
        if cmd[-1] == proxy_name:
            return SimpleNamespace(stdout="[]" if proxy_missing else json.dumps([proxy]), stderr=f"Error: No such object: {proxy_name}" if proxy_missing else "", returncode=1 if proxy_missing else 0)
        return SimpleNamespace(stdout=json.dumps([entry]), stderr="", returncode=0)

    monkeypatch.setattr("subprocess.run", runtime)
    info = backend.inspect_runtime("existing")
    assert info is not None
    assert info.container_id == "main-generation"
    assert info.sandbox_url == ("" if proxy_missing else "http://localhost:18080")


def test_inspect_runtime_propagates_unknown_proxy_port_probe(monkeypatch):
    backend = _backend_for_inspect_tests()
    proxy_name, _ = backend._resource_names("existing")
    entry = {"Id": "main-generation", "Name": "/sandbox-existing", "Config": {"Labels": {"deerflow.network_mode": "allowlist"}}}

    def runtime(cmd, **kwargs):
        if cmd[-1] == proxy_name:
            return SimpleNamespace(stdout="", stderr="daemon unavailable", returncode=1)
        return SimpleNamespace(stdout=json.dumps([entry]), stderr="", returncode=0)

    monkeypatch.setattr("subprocess.run", runtime)
    with pytest.raises(RuntimeError, match="daemon unavailable"):
        backend.inspect_runtime("existing")


def test_inspect_runtime_retains_direct_binding_during_network_mode_transition(monkeypatch):
    backend = _backend_for_inspect_tests()
    backend._network_mode = "allowlist"
    proxy_name, _ = backend._resource_names("existing")
    entry = {"Id": "legacy-generation", "Name": "/sandbox-existing", "HostConfig": {"PortBindings": {"8080/tcp": [{"HostPort": "18080"}]}}}

    def runtime(cmd, **kwargs):
        if cmd[-1] == proxy_name:
            return SimpleNamespace(stdout="[]", stderr=f"Error: No such object: {proxy_name}", returncode=1)
        return SimpleNamespace(stdout=json.dumps([entry]), stderr="", returncode=0)

    monkeypatch.setattr("subprocess.run", runtime)
    assert backend.inspect_runtime("existing").sandbox_url == "http://localhost:18080"


def test_inspect_runtime_does_not_inherit_another_generations_pending_port(monkeypatch):
    backend = _backend_for_inspect_tests()
    backend._pending_cleanup_ports["old-generation"] = ("existing", 18080)
    entry = {"Id": "replacement-generation", "Name": "/sandbox-existing"}
    monkeypatch.setattr("subprocess.run", lambda *_args, **_kwargs: SimpleNamespace(stdout=json.dumps([entry]), stderr="", returncode=0))
    info = backend.inspect_runtime("existing")
    assert info.container_id == "replacement-generation"
    assert info.sandbox_url == ""
    assert backend._pending_cleanup_ports == {"old-generation": ("existing", 18080)}


def test_destroy_releases_port_after_both_containers_are_removed_despite_network_timeout(monkeypatch):
    backend = _backend_for_inspect_tests()
    backend._network_mode = "allowlist"
    released = []
    monkeypatch.setattr(local_backend_module, "release_port", released.append)
    proxy_name, _ = backend._resource_names("existing")
    stopped = []
    monkeypatch.setattr(backend, "_stop_container", stopped.append)

    def runtime(cmd, **kwargs):
        if cmd[:3] == ["docker", "network", "rm"]:
            raise subprocess.TimeoutExpired(cmd, 15)
        return SimpleNamespace(stdout="", stderr="", returncode=0)

    monkeypatch.setattr("subprocess.run", runtime)
    info = SandboxInfo("existing", "http://localhost:18080", container_name="sandbox-existing", container_id="main-generation")
    with pytest.raises(subprocess.TimeoutExpired):
        backend.destroy(info)
    assert stopped == [proxy_name, "main-generation"]
    assert released == [18080]
    assert backend._pending_cleanup_ports == {}


def test_confirmed_absent_teardown_releases_a_timed_out_but_removed_generations_port_once(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    from deerflow.utils.network import PortAllocator

    backend = _backend_for_inspect_tests()
    allocator = PortAllocator()
    monkeypatch.setattr(allocator, "_is_port_available", lambda port: port not in allocator._reserved_ports)
    port = allocator.allocate(18080, max_range=1)
    other_port = allocator.allocate(18081, max_range=1)
    released = []
    removed = False

    def release(port):
        released.append(port)
        allocator.release(port)

    def runtime(cmd, **kwargs):
        nonlocal removed
        if "stop" in cmd:
            if cmd[-1].startswith("deer-flow-netproxy-"):
                raise subprocess.CalledProcessError(1, cmd, stderr=f"Error: No such container: {cmd[-1]}")
            if cmd[-1] == "removed-generation":
                removed = True
            raise subprocess.TimeoutExpired(cmd, 120)
        if cmd[:3] in [["docker", "rm", "-f"], ["docker", "network", "rm"]]:
            return SimpleNamespace(stdout="", stderr="", returncode=0)
        assert removed
        return SimpleNamespace(stdout="[]", stderr="Error: No such object: sandbox-existing", returncode=1)

    monkeypatch.setattr("subprocess.run", runtime)
    monkeypatch.setattr(local_backend_module, "release_port", release)
    for sandbox_id, generation, reserved_port in [("other", "other-generation", other_port), ("existing", "removed-generation", port)]:
        with pytest.raises(subprocess.TimeoutExpired):
            backend.destroy(SandboxInfo(sandbox_id, f"http://localhost:{reserved_port}", container_id=generation))

    assert backend.inspect_runtime("existing") is None
    assert backend.is_absent("existing") is True
    assert released == []  # Metadata and presence reads never mutate reservations.
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(backend.complete_absent_teardown, ["existing", "existing"]))
    assert released == [port]
    assert allocator.allocate(18080, max_range=1) == port
    with pytest.raises(RuntimeError, match="No available port"):
        allocator.allocate(18081, max_range=1)
    backend.complete_absent_teardown("existing")
    assert released == [port]


@pytest.mark.parametrize("restarted", [False, True])
def test_absent_teardown_removes_leftover_networks_and_allows_restricted_creation(monkeypatch, restarted):
    backend = _restricted_backend()
    restarted_backend = _restricted_backend() if restarted else None
    proxy_name, network_name = backend._resource_names("existing")
    networks = {network_name, backend._egress_network_name("existing")}
    released = []
    monkeypatch.setattr(local_backend_module, "release_port", released.append)

    def runtime(cmd, **kwargs):
        if "stop" in cmd:
            if cmd[-1] == "old-generation":
                raise subprocess.TimeoutExpired(cmd, 120)
            raise subprocess.CalledProcessError(1, cmd, stderr=f"Error: No such container: {cmd[-1]}")
        if cmd[:3] == ["docker", "rm", "-f"]:
            return SimpleNamespace(stdout="", stderr=f"Error: No such container: {proxy_name}", returncode=1)
        if cmd[:3] == ["docker", "network", "rm"]:
            networks.discard(cmd[-1])
            return SimpleNamespace(stdout=cmd[-1], stderr="", returncode=0)
        if cmd[:3] == ["docker", "network", "inspect"]:
            if cmd[-1] in networks:
                return SimpleNamespace(stdout=json.dumps([{"Driver": "bridge", "Internal": True}]), stderr="", returncode=0)
            return SimpleNamespace(stdout="[]", stderr=f"Error response from daemon: network {cmd[-1]} not found", returncode=1)
        assert cmd[:2] == ["docker", "inspect"]
        return SimpleNamespace(stdout="[]", stderr="\n".join(f"Error: No such container: {name}" for name in cmd[2:]), returncode=1)

    monkeypatch.setattr("subprocess.run", runtime)
    with pytest.raises(subprocess.TimeoutExpired):
        backend.destroy(SandboxInfo("existing", "http://localhost:18080", container_id="old-generation"))
    assert backend.is_absent("existing") is True
    assert backend._restricted_resources_status("existing") == "mismatch"
    if restarted:
        backend = restarted_backend
        assert backend._pending_cleanup_ports == {}
    backend.complete_absent_teardown("existing")
    assert backend._restricted_resources_status("existing") == "missing"
    assert released == ([] if restarted else [18080])
    monkeypatch.setattr(backend, "_create_internal_network", lambda *_args: None)
    monkeypatch.setattr(backend, "_create_egress_network", lambda *_args: None)
    monkeypatch.setattr(backend, "_start_network_proxy", lambda *_args: None)
    monkeypatch.setattr(backend, "_start_container", lambda *_args, **_kwargs: "replacement-generation")
    assert backend._start_restricted_sandbox("existing", "sandbox-existing", 18080, None, config_mount_exclusion_root=None, relay_token="token") == "replacement-generation"


@pytest.mark.parametrize("error_kind", ["context", "wrong-target", "active-endpoint", "empty"])
def test_absent_teardown_preserves_pending_port_on_unknown_network_cleanup_error(monkeypatch, error_kind):
    backend = _restricted_backend()
    backend._pending_cleanup_ports["old-generation"] = ("existing", 18080)
    proxy_name, network_name = backend._resource_names("existing")
    errors = {
        "context": f'context "{network_name}": context not found',
        "wrong-target": f"Error response from daemon: network {network_name}-extra not found",
        "active-endpoint": f"Error response from daemon: network {network_name} has active endpoints",
        "empty": "",
    }
    released = []
    monkeypatch.setattr(local_backend_module, "release_port", released.append)
    monkeypatch.setattr(backend, "_stop_container", lambda *_args: None)

    def runtime(cmd, **kwargs):
        if cmd == ["docker", "rm", "-f", proxy_name]:
            return SimpleNamespace(stdout="", stderr="", returncode=0)
        return SimpleNamespace(stdout="", stderr=errors[error_kind], returncode=1)

    monkeypatch.setattr("subprocess.run", runtime)
    with pytest.raises(RuntimeError):
        backend.complete_absent_teardown("existing")
    assert released == []
    assert backend._pending_cleanup_ports == {"old-generation": ("existing", 18080)}


def test_absent_teardown_accepts_only_exact_missing_networks(monkeypatch):
    backend = _restricted_backend()
    backend._pending_cleanup_ports["old-generation"] = ("existing", 18080)
    released = []
    monkeypatch.setattr(local_backend_module, "release_port", released.append)
    monkeypatch.setattr(backend, "_stop_container", lambda *_args: None)
    commands = []

    def runtime(cmd, **kwargs):
        commands.append(cmd)
        if cmd[:3] == ["docker", "rm", "-f"]:
            return SimpleNamespace(stdout="", stderr=f"Error: No such container: {cmd[-1]}", returncode=1)
        return SimpleNamespace(stdout="", stderr=f"Error response from daemon: network {cmd[-1]} not found", returncode=1)

    monkeypatch.setattr("subprocess.run", runtime)
    backend.complete_absent_teardown("existing")
    assert released == [18080]
    assert backend._pending_cleanup_ports == {}
    assert ["docker", "network", "rm", backend._resource_names("existing")[1]] in commands
    assert ["docker", "network", "rm", backend._egress_network_name("existing")] in commands


def test_apple_absent_teardown_releases_own_unknown_generation_port_after_timeout(monkeypatch):
    backend = _backend_for_inspect_tests()
    backend._runtime = "container"
    released = []
    monkeypatch.setattr(local_backend_module, "release_port", released.append)

    def runtime(cmd, **kwargs):
        if "stop" in cmd:
            raise subprocess.TimeoutExpired(cmd, 120)
        assert cmd[:2] == ["container", "inspect"]
        return SimpleNamespace(stdout="[]", stderr="Error: container not found: sandbox-existing", returncode=1)

    monkeypatch.setattr("subprocess.run", runtime)
    with pytest.raises(subprocess.TimeoutExpired):
        backend.destroy(SandboxInfo("other", "http://localhost:18081", container_name="sandbox-other"))
    with pytest.raises(subprocess.TimeoutExpired):
        backend.destroy(SandboxInfo("existing", "http://localhost:18080", container_name="sandbox-existing"))
    assert backend.inspect_runtime("existing") is None
    assert backend.is_absent("existing") is True
    assert released == []
    backend.complete_absent_teardown("existing")
    backend.complete_absent_teardown("existing")
    assert released == [18080]
    backend.complete_absent_teardown("other")
    assert released == [18080, 18081]


def test_apple_present_unknown_generation_does_not_inherit_pending_port(monkeypatch):
    backend = _backend_for_inspect_tests()
    backend._runtime = "container"
    released = []
    monkeypatch.setattr(local_backend_module, "release_port", released.append)

    def runtime(cmd, **kwargs):
        if "stop" in cmd:
            raise subprocess.TimeoutExpired(cmd, 120)
        entry = {"configuration": {"id": "sandbox-existing"}, "status": "running"}
        return SimpleNamespace(stdout=json.dumps([entry]), stderr="", returncode=0)

    monkeypatch.setattr("subprocess.run", runtime)
    with pytest.raises(subprocess.TimeoutExpired):
        backend.destroy(SandboxInfo("existing", "http://localhost:18080", container_name="sandbox-existing"))
    info = backend.inspect_runtime("existing")
    assert info is not None
    assert info.container_id is None
    assert info.sandbox_url == ""
    assert backend.is_absent("existing") is False
    assert released == []


@pytest.mark.parametrize("runtime", ["container", "docker"])
def test_successful_unknown_generation_retry_does_not_release_a_reused_port_again(monkeypatch, runtime):
    from deerflow.utils.network import PortAllocator

    backend = _backend_for_inspect_tests()
    backend._runtime = runtime
    allocator = PortAllocator()
    monkeypatch.setattr(allocator, "_is_port_available", lambda port: port not in allocator._reserved_ports)
    port = allocator.allocate(18080, max_range=1)
    failed = False
    released = []

    def release(port):
        released.append(port)
        allocator.release(port)

    def stop(_target):
        nonlocal failed
        if not failed:
            failed = True
            raise subprocess.TimeoutExpired("stop", 120)

    monkeypatch.setattr(backend, "_stop_container", stop)
    monkeypatch.setattr(local_backend_module, "release_port", release)
    monkeypatch.setattr("subprocess.run", lambda *_args, **_kwargs: SimpleNamespace(stdout="", stderr="", returncode=0))
    original = SandboxInfo("existing", f"http://localhost:{port}", container_name="sandbox-existing")
    with pytest.raises(subprocess.TimeoutExpired):
        backend.destroy(original)
    # Old Docker metadata can learn its immutable generation on a retry.
    if runtime == "docker":
        original.container_id = "learned-generation"
    backend.destroy(original)
    assert allocator.allocate(18080, max_range=1) == port
    backend.complete_absent_teardown("existing")
    assert released == [port]
    with pytest.raises(RuntimeError, match="No available port"):
        allocator.allocate(18080, max_range=1)


def test_absent_teardown_deduplicates_a_legacy_reservation_that_later_learns_its_generation(monkeypatch):
    backend = _backend_for_inspect_tests()
    released = []
    monkeypatch.setattr(local_backend_module, "release_port", released.append)
    monkeypatch.setattr("subprocess.run", lambda *_args, **_kwargs: SimpleNamespace(stdout="", stderr="", returncode=0))

    def timeout(_target):
        raise subprocess.TimeoutExpired("stop", 120)

    monkeypatch.setattr(backend, "_stop_container", timeout)
    info = SandboxInfo("existing", "http://localhost:18080", container_name="sandbox-existing")
    with pytest.raises(subprocess.TimeoutExpired):
        backend.destroy(info)
    info.container_id = "learned-generation"
    with pytest.raises(subprocess.TimeoutExpired):
        backend.destroy(info)
    monkeypatch.setattr(backend, "_stop_container", lambda *_args: None)
    backend.complete_absent_teardown("existing")
    backend.complete_absent_teardown("existing")
    assert released == [18080]


@pytest.mark.parametrize("failed_stage", ["proxy-stop", "proxy-remove", "main-stop"])
def test_restricted_partial_destroy_keeps_a_retryable_main_and_releases_port_once(monkeypatch, failed_stage):
    from deerflow.utils.network import PortAllocator

    backend = _backend_for_inspect_tests()
    backend._network_mode = "allowlist"
    allocator = PortAllocator()
    monkeypatch.setattr(allocator, "_is_port_available", lambda port: port not in allocator._reserved_ports)
    port = allocator.allocate(18080, max_range=1)
    released = []

    def release(port):
        released.append(port)
        allocator.release(port)

    monkeypatch.setattr(local_backend_module, "release_port", release)
    proxy_name, _ = backend._resource_names("existing")
    main = {"Id": "main-generation", "Name": "/sandbox-existing", "Config": {"Labels": {"deerflow.network_mode": "allowlist"}}}
    proxy = {"Id": "proxy-generation", "Name": f"/{proxy_name}", "HostConfig": {"PortBindings": {"8080/tcp": [{"HostPort": str(port)}]}}}
    removed = set()
    failed = False

    def runtime(cmd, **kwargs):
        nonlocal failed
        target = cmd[-1]
        if "inspect" in cmd:
            if target in removed:
                return SimpleNamespace(stdout="[]", stderr=f"Error: No such object: {target}", returncode=1)
            return SimpleNamespace(stdout=json.dumps([proxy if target == proxy_name else main]), stderr="", returncode=0)
        stage = "proxy-remove" if cmd[:3] == ["docker", "rm", "-f"] else "proxy-stop" if "stop" in cmd and target == proxy_name else "main-stop" if "stop" in cmd else None
        if stage == failed_stage and not failed:
            failed = True
            if kwargs.get("check"):
                raise subprocess.CalledProcessError(1, cmd, stderr="daemon denied teardown")
            return SimpleNamespace(stdout="", stderr="daemon denied teardown", returncode=1)
        if stage == "main-stop":
            removed.add("sandbox-existing")
        elif stage == "proxy-remove":
            removed.add(proxy_name)
        return SimpleNamespace(stdout="", stderr="", returncode=0)

    monkeypatch.setattr("subprocess.run", runtime)
    original = SandboxInfo("existing", f"http://localhost:{port}", container_name="sandbox-existing", container_id="main-generation")
    with pytest.raises((RuntimeError, subprocess.CalledProcessError)):
        backend.destroy(original)
    assert backend.is_absent("existing") is False
    assert released == []
    with pytest.raises(RuntimeError, match="No available port"):
        allocator.allocate(18080, max_range=1)
    recovered = backend.inspect_runtime("existing")
    assert recovered is not None
    backend.destroy(recovered)
    assert allocator.allocate(18080, max_range=1) == port
    assert released == [port]


def test_apple_list_does_not_mark_unsupported_runtime_metadata_for_replacement(monkeypatch):
    backend = _backend_for_inspect_tests()
    backend._runtime = "container"
    entry = {"configuration": {"id": "sandbox-existing"}, "status": "running"}

    def runtime(cmd, **kwargs):
        return SimpleNamespace(stdout="sandbox-existing\n" if "ps" in cmd else json.dumps([entry]), stderr="", returncode=0)

    monkeypatch.setattr("subprocess.run", runtime)
    assert backend.list_running() == []
    assert backend.inspect_runtime("existing") is not None


def test_apple_batch_preserves_legacy_docker_shaped_metadata(monkeypatch):
    backend = _backend_for_inspect_tests()
    backend._runtime = "container"
    entry = {"Name": "/sandbox-existing", "NetworkSettings": {"Ports": {"8080/tcp": [{"HostPort": "18080"}]}}}
    monkeypatch.setattr("subprocess.run", lambda *_args, **_kwargs: SimpleNamespace(stdout=json.dumps([entry]), stderr="", returncode=0))
    assert backend._batch_inspect(["sandbox-existing"], strict=True)["sandbox-existing"].host_port == 18080


@pytest.mark.parametrize("runtime", ["docker", "container"])
def test_inspect_runtime_only_returns_none_for_authoritative_absence(monkeypatch, runtime):
    backend = _backend_for_inspect_tests()
    backend._runtime = runtime
    error = "Error: No such object: sandbox-missing" if runtime == "docker" else "Error: container not found: sandbox-missing"
    monkeypatch.setattr("subprocess.run", lambda *_args, **_kwargs: SimpleNamespace(stdout="[]", stderr=error, returncode=1))

    assert backend.inspect_runtime("missing") is None


@pytest.mark.parametrize(
    "payload",
    [
        "",
        "[]",
        "{}",
        "not JSON",
        json.dumps([{"Name": "/sandbox-other", "Id": "generation"}]),
        json.dumps([{"Name": "/sandbox-existing"}]),
        json.dumps([{"Name": "/sandbox-existing", "Id": 42}]),
        json.dumps([{"Name": "/sandbox-existing", "Id": "generation"}, {"Name": "/sandbox-existing", "Id": "other-generation"}]),
    ],
)
def test_inspect_runtime_fails_closed_on_incomplete_or_invalid_docker_response(monkeypatch, payload):
    backend = _backend_for_inspect_tests()
    monkeypatch.setattr("subprocess.run", lambda *_args, **_kwargs: SimpleNamespace(stdout=payload, stderr="", returncode=0))

    with pytest.raises(RuntimeError):
        backend.inspect_runtime("existing")
    with pytest.raises(RuntimeError):
        backend.is_absent("existing")


@pytest.mark.parametrize("failure", [OSError("runtime unavailable"), subprocess.TimeoutExpired("inspect", 5)])
def test_inspect_runtime_propagates_runtime_failures(monkeypatch, failure):
    backend = _backend_for_inspect_tests()

    def failed(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr("subprocess.run", failed)
    with pytest.raises(RuntimeError):
        backend.inspect_runtime("existing")


def test_batch_inspect_keeps_present_generations_with_exact_partial_absence(monkeypatch):
    backend = _backend_for_inspect_tests()
    entry = {"Name": "/sandbox-existing", "Id": "immutable-generation"}
    monkeypatch.setattr("subprocess.run", lambda *_args, **_kwargs: SimpleNamespace(stdout=json.dumps([entry]), stderr="Error: No such object: sandbox-missing", returncode=1))

    inspections = backend._batch_inspect(["sandbox-existing", "sandbox-missing"], strict=True)

    assert list(inspections) == ["sandbox-existing"]
    assert inspections["sandbox-existing"].container_id == "immutable-generation"


def test_batch_inspect_does_not_accept_absence_of_an_unrequested_resource(monkeypatch):
    backend = _backend_for_inspect_tests()
    monkeypatch.setattr("subprocess.run", lambda *_args, **_kwargs: SimpleNamespace(stdout="[]", stderr="Error: No such object: sandbox-other", returncode=1))

    with pytest.raises(RuntimeError):
        backend._batch_inspect(["sandbox-existing"], strict=True)


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


def test_failed_stop_is_not_reported_as_destroyed(monkeypatch):
    backend = _backend_for_inspect_tests()

    def denied(cmd, **_kwargs):
        raise subprocess.CalledProcessError(1, cmd, stderr="daemon denied stop")

    monkeypatch.setattr("subprocess.run", denied)
    with pytest.raises(subprocess.CalledProcessError):
        backend.destroy(SandboxInfo("sandbox", "http://localhost:18080", container_id="generation"))


def test_docker_discovery_preserves_runtime_generation(monkeypatch):
    import json

    import requests

    backend = _backend_for_inspect_tests()
    payload = [
        {
            "Id": "docker-generation",
            "Name": "/sandbox-existing",
            "Config": {"Image": "sandbox:latest", "Labels": {"deerflow.role": "sandbox", "deerflow.sandbox_id": "existing", "deerflow.network_mode": "open"}},
            "NetworkSettings": {"Ports": {"8080/tcp": [{"HostPort": "18080"}]}},
        }
    ]

    def runtime(cmd, **_kwargs):
        return SimpleNamespace(returncode=0, stdout="true" if "-f" in cmd else json.dumps(payload), stderr="")

    monkeypatch.setattr("subprocess.run", runtime)
    monkeypatch.setattr(requests.Session, "get", lambda *_args, **_kwargs: SimpleNamespace(status_code=200))

    info = backend.discover("existing")
    assert info is not None
    assert info.container_id == "docker-generation"


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


# ── Extended network syntax and IPv6 host normalization ──────────────────────


def test_start_container_rejects_extended_network_syntax_host(monkeypatch):
    """name=host attaches the host network namespace exactly like `host`;
    the raw string must not dodge the rejection."""
    backend = _backend_for_inspect_tests()
    _clear_hardening_env(monkeypatch)
    monkeypatch.setenv("DEER_FLOW_SANDBOX_NETWORK", "name=host")

    with pytest.raises(RuntimeError, match="DEER_FLOW_SANDBOX_NETWORK"):
        _capture_start_container_command(monkeypatch, backend)


def test_start_container_rejects_extended_network_syntax_none(monkeypatch):
    backend = _backend_for_inspect_tests()
    _clear_hardening_env(monkeypatch)
    monkeypatch.setenv("DEER_FLOW_SANDBOX_NETWORK", "name=none")

    with pytest.raises(RuntimeError, match="loopback-only"):
        _capture_start_container_command(monkeypatch, backend)


def test_start_container_rejects_extended_network_syntax_container(monkeypatch):
    backend = _backend_for_inspect_tests()
    _clear_hardening_env(monkeypatch)
    monkeypatch.setenv("DEER_FLOW_SANDBOX_NETWORK", "name=container:gateway")

    with pytest.raises(RuntimeError, match="DEER_FLOW_SANDBOX_NETWORK"):
        _capture_start_container_command(monkeypatch, backend)


def test_start_container_passes_extended_network_syntax_for_custom_networks(monkeypatch):
    """The legit name=<custom-net> long form (and network IDs) keep working."""
    backend = _backend_for_inspect_tests()
    _clear_hardening_env(monkeypatch)
    monkeypatch.setenv("DEER_FLOW_SANDBOX_NETWORK", "name=deer-flow-sandbox-egress")

    captured_cmd = _capture_start_container_command(monkeypatch, backend)

    assert captured_cmd[captured_cmd.index("--network") + 1] == "name=deer-flow-sandbox-egress"


@pytest.mark.parametrize("sandbox_host", ["fd00::1", "[fd00::1]"])
def test_discover_brackets_ipv6_sandbox_host_for_url(monkeypatch, sandbox_host):
    """Both IPv6 input forms must yield the same bracketed URL authority:
    the bare form used to produce the malformed http://fd00::1:<port>."""
    backend = _backend_for_inspect_tests()
    monkeypatch.setenv("DEER_FLOW_SANDBOX_HOST", sandbox_host)
    monkeypatch.setattr(backend, "_is_container_running", lambda name: True)
    monkeypatch.setattr(
        backend,
        "_batch_inspect",
        lambda *_args, **_kwargs: {
            "sandbox-sbx-ipv6": _ContainerInspection(
                1.0,
                18081,
                {},
                "sandbox:latest",
                frozenset({"bridge"}),
            )
        },
    )

    seen_urls = []

    def fake_ready(url, timeout):
        seen_urls.append(url)
        return True

    monkeypatch.setattr("deerflow.community.aio_sandbox.local_backend.wait_for_sandbox_ready", fake_ready)

    info = backend.discover("sbx-ipv6")

    assert info.sandbox_url == "http://[fd00::1]:18081"
    assert seen_urls == ["http://[fd00::1]:18081"]


@pytest.mark.parametrize("sandbox_host", ["fd00::1", "[fd00::1]"])
def test_create_brackets_ipv6_sandbox_host_for_url(monkeypatch, sandbox_host):
    backend = _backend_for_inspect_tests()
    monkeypatch.setenv("DEER_FLOW_SANDBOX_HOST", sandbox_host)
    monkeypatch.setattr(
        backend,
        "_start_container",
        lambda name, port, mounts=None, **_kwargs: "container-id",
    )
    monkeypatch.setattr("deerflow.community.aio_sandbox.local_backend.get_free_port", lambda start_port=None: 18082)

    info = backend.create(thread_id="t", sandbox_id="sbx-ipv6")

    assert info.sandbox_url == "http://[fd00::1]:18082"


def test_resolve_sandbox_host_address_accepts_bracketed_ipv6(monkeypatch):
    """The bracketed form must resolve (unbracketed for getaddrinfo) instead
    of failing through to the IPv4 bridge fallback."""
    from deerflow.community.aio_sandbox.local_backend import _resolve_sandbox_host_address

    infos = [(socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("fd00::1", 0, 0, 0))]

    def fake_getaddrinfo(host, port, *args, **kwargs):
        assert host == "fd00::1", f"getaddrinfo must receive the unbracketed form, got {host!r}"
        return infos

    monkeypatch.setattr("deerflow.community.aio_sandbox.local_backend.socket.getaddrinfo", fake_getaddrinfo)

    assert _resolve_sandbox_host_address("[fd00::1]") == "[fd00::1]"


# ── Long-syntax fields in any position (Docker opts/network.go semantics) ────


@pytest.mark.parametrize(
    "network",
    [
        "name=host,gw-priority=0",
        "gw-priority=0,name=host",
        "name=host,alias=sbx",
    ],
)
def test_start_container_rejects_host_with_additional_long_syntax_fields(monkeypatch, network):
    """Docker accepts comma-separated fields in any order; both orderings
    select the host network and must not dodge the rejection."""
    backend = _backend_for_inspect_tests()
    _clear_hardening_env(monkeypatch)
    monkeypatch.setenv("DEER_FLOW_SANDBOX_NETWORK", network)

    with pytest.raises(RuntimeError, match="DEER_FLOW_SANDBOX_NETWORK"):
        _capture_start_container_command(monkeypatch, backend)


def test_start_container_rejects_none_with_additional_long_syntax_fields(monkeypatch):
    backend = _backend_for_inspect_tests()
    _clear_hardening_env(monkeypatch)
    monkeypatch.setenv("DEER_FLOW_SANDBOX_NETWORK", "gw-priority=0,name=none")

    with pytest.raises(RuntimeError, match="loopback-only"):
        _capture_start_container_command(monkeypatch, backend)


def test_start_container_rejects_container_mode_with_additional_long_syntax_fields(monkeypatch):
    backend = _backend_for_inspect_tests()
    _clear_hardening_env(monkeypatch)
    monkeypatch.setenv("DEER_FLOW_SANDBOX_NETWORK", "name=container:gateway,gw-priority=0")

    with pytest.raises(RuntimeError, match="DEER_FLOW_SANDBOX_NETWORK"):
        _capture_start_container_command(monkeypatch, backend)


def test_start_container_passes_long_syntax_custom_network_with_fields(monkeypatch):
    """A legit long-syntax value with extra fields keeps passing through verbatim."""
    backend = _backend_for_inspect_tests()
    _clear_hardening_env(monkeypatch)
    monkeypatch.setenv("DEER_FLOW_SANDBOX_NETWORK", "name=egressnet,gw-priority=1")

    captured_cmd = _capture_start_container_command(monkeypatch, backend)

    assert captured_cmd[captured_cmd.index("--network") + 1] == "name=egressnet,gw-priority=1"


def test_effective_network_target_last_name_field_wins():
    """Docker's parser lets a later name= field overwrite an earlier one."""
    from deerflow.community.aio_sandbox.local_backend import _effective_docker_network_target as target

    assert target("name=host,name=egressnet") == "egressnet"
    assert target("name=egressnet,name=host") == "host"
    assert target("gw-priority=0") == "gw-priority=0"  # no name= field: Docker errors itself
    assert target("bridge") == "bridge"
    assert target("1f2a" * 16) == "1f2a" * 16  # network ID passes through


# ── Real-image startup smoke tests (docker-gated) ────────────────────────────
# Keep the baseline default in sync with aio_sandbox_provider.DEFAULT_IMAGE.
_DEFAULT_AIO_IMAGE = "enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest"
# Dedicated regression target for #5161. The workflow resolves this tag to an
# immutable digest before pytest runs so the CI result records the exact image.
_FOWNER_REGRESSION_AIO_IMAGE = "enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:1.11.0"


def _docker_daemon_available() -> bool:
    try:
        subprocess.run(["docker", "info"], capture_output=True, timeout=30, check=True)
        return True
    except Exception:
        return False


def _assert_image_starts_under_hardened_capabilities(
    monkeypatch,
    *,
    image: str,
    sandbox_id: str,
    failure_label: str,
) -> None:
    from deerflow.community.aio_sandbox.backend import SANDBOX_LOCAL_PROVIDER_READY_TIMEOUT
    from deerflow.community.aio_sandbox.local_backend import wait_for_sandbox_ready

    if not _docker_daemon_available():
        pytest.skip("requires a running Docker daemon")

    backend = LocalContainerBackend(
        image=image,
        base_port=18210,
        container_prefix="sandbox-smoke",
        config_mounts=[],
        environment={},
    )
    _clear_hardening_env(monkeypatch)

    info = backend.create(thread_id="smoke", sandbox_id=sandbox_id)
    try:
        # The production deadline, single-sourced: the sync and async
        # provider paths destroy the container after exactly this budget, so
        # a longer one here could pass while every real acquisition fails.
        # (create() completes docker run — including the image pull — before
        # this timer starts, so the pull is not part of the budget.)
        ready = wait_for_sandbox_ready(info.sandbox_url, timeout=SANDBOX_LOCAL_PROVIDER_READY_TIMEOUT)
        if not ready:
            # Fail diagnosably: the entrypoint's own log tells us whether the
            # capability set is still incomplete (chown/chmod/useradd/su
            # errors) or the services are merely slow.
            logs = subprocess.run(
                ["docker", "logs", info.container_name],
                capture_output=True,
                text=True,
                timeout=30,
            )
            # supervisord only reports exit codes in the container log; the
            # failing program's own stderr goes to files inside the container.
            # Pull the usual suspects so the failure is actionable in CI.
            prog_logs = subprocess.run(
                [
                    "docker",
                    "exec",
                    info.container_name,
                    "sh",
                    "-c",
                    "cat /var/log/supervisor/* 2>/dev/null | tail -n 40; echo '--- nginx -t ---'; nginx -t 2>&1; echo '--- nginx error.log ---'; tail -n 20 /var/log/nginx/error.log 2>/dev/null",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            tail = "\n".join((logs.stdout + logs.stderr).splitlines()[-40:]) + "\n" + (prog_logs.stdout or "")
            pytest.fail(f"{failure_label} never became ready under the hardened capabilities: {info.sandbox_url}\n--- last 40 container log lines ---\n{tail}")
        assert backend.is_alive(info)
    finally:
        backend.destroy(info)


# `live`: pulls and runs external images, so the default offline suite
# (`make test` = `-m "not live"`) never touches the network. The daemon probe
# happens inside the helper — never at collection time.
@pytest.mark.live
def test_default_image_starts_under_hardened_capabilities(monkeypatch):
    """Preserve real-image coverage for the configured/default AIO image.

    This stays separate from the 1.11.0 regression because older images may
    not execute the FOWNER-gated chmod added by the newer startup path.
    """
    _assert_image_starts_under_hardened_capabilities(
        monkeypatch,
        image=os.environ.get("DEER_FLOW_SANDBOX_SMOKE_IMAGE", _DEFAULT_AIO_IMAGE),
        sandbox_id="caps-smoke-default",
        failure_label="configured/default image",
    )


@pytest.mark.live
def test_aio_1_11_image_starts_with_fowner_capability(monkeypatch):
    """Regression smoke for #5161 against the recommended AIO 1.11.0 image.

    Its entrypoint chmods /run/user/1000 after capabilities are dropped.
    Without FOWNER that startup path exits before readiness; reaching the
    endpoint proves the five-capability compatibility set covers the bug.
    """
    _assert_image_starts_under_hardened_capabilities(
        monkeypatch,
        image=os.environ.get("DEER_FLOW_SANDBOX_FOWNER_SMOKE_IMAGE", _FOWNER_REGRESSION_AIO_IMAGE),
        sandbox_id="caps-smoke-fowner-1-11",
        failure_label="AIO 1.11.0 FOWNER regression image",
    )


@pytest.mark.live
def test_restricted_network_proxy_enforces_and_approves_real_traffic(monkeypatch):
    """Exercise the Engine-28 bridge, API relay, proxy, event, and grant path."""
    if not _docker_daemon_available():
        pytest.skip("requires a running Docker daemon")

    image = os.environ.get("DEER_FLOW_SANDBOX_NETWORK_SMOKE_IMAGE", "python:3.12-alpine")
    backend = LocalContainerBackend(
        image=image,
        base_port=18310,
        container_prefix="sandbox-policy-smoke",
        config_mounts=[],
        environment={},
        network_config={
            "mode": "allowlist",
            "allow_domains": ["pypi.org"],
            "approval": "prompt",
            "temporary_grant_ttl": 300,
            "proxy_image": image,
        },
    )
    monkeypatch.delenv("DEER_FLOW_SANDBOX_BIND_HOST", raising=False)
    sandbox_id = "network-live"
    container_name = f"sandbox-policy-smoke-{sandbox_id}"
    proxy_name, network_name = backend._resource_names(sandbox_id)
    egress_network_name = backend._egress_network_name(sandbox_id)
    port = get_free_port(start_port=18310)
    relay_token = "live-relay-token-that-is-at-least-32-bytes"
    proxy_url = f"http://{proxy_name}:3128"

    try:
        assert backend._restricted_resources_status(sandbox_id) == "missing"
        backend._create_internal_network(network_name, sandbox_id)
        backend._create_egress_network(egress_network_name, sandbox_id)
        backend._start_network_proxy(proxy_name, network_name, egress_network_name, container_name, port, sandbox_id, relay_token)

        proxy_inspect = subprocess.run(
            ["docker", "inspect", proxy_name],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert proxy_inspect.returncode == 0, proxy_inspect.stderr
        proxy_networks = json.loads(proxy_inspect.stdout)[0]["NetworkSettings"]["Networks"]
        assert set(proxy_networks) == {network_name, egress_network_name}
        assert "bridge" not in proxy_networks
        proxy_egress_ip = proxy_networks[egress_network_name]["IPAddress"]
        outside = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "bridge",
                image,
                "python",
                "-c",
                (f"import socket,sys\ntry:\n    socket.create_connection(({proxy_egress_ip!r}, 8080), timeout=2)\nexcept OSError:\n    sys.exit(0)\nsys.exit(42)"),
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert outside.returncode == 0, outside.stderr or "a container on Docker's shared bridge reached the sandbox API relay"
        sandbox_labels = backend._restricted_labels(sandbox_id, "sandbox")
        sandbox = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "-d",
                "--network",
                network_name,
                "--name",
                container_name,
                *(item for key, value in sandbox_labels.items() for item in ("--label", f"{key}={value}")),
                "-e",
                f"HTTP_PROXY={proxy_url}",
                "-e",
                f"HTTPS_PROXY={proxy_url}",
                "-e",
                f"http_proxy={proxy_url}",
                "-e",
                f"https_proxy={proxy_url}",
                image,
                "python",
                "-m",
                "http.server",
                "8080",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert sandbox.returncode == 0, sandbox.stderr
        assert backend._restricted_resources_status(sandbox_id) == "compatible"
        backend._network_config["allow_domains"] = ["changed.example"]
        assert backend._restricted_resources_status(sandbox_id) == "mismatch"
        backend._network_config["allow_domains"] = ["pypi.org"]

        sandbox_url = f"http://127.0.0.1:{port}"
        unauthenticated = subprocess.run(
            ["curl", "--fail", "--silent", "--max-time", "2", sandbox_url],
            capture_output=True,
            text=True,
        )
        assert unauthenticated.returncode != 0
        deadline = time.time() + 20
        while time.time() < deadline:
            relay = subprocess.run(
                [
                    "curl",
                    "--fail",
                    "--silent",
                    "--max-time",
                    "2",
                    "-H",
                    f"X-DeerFlow-Relay-Token: {relay_token}",
                    sandbox_url,
                ],
                capture_output=True,
                text=True,
            )
            if relay.returncode == 0:
                break
            time.sleep(0.25)
        assert relay.returncode == 0, relay.stderr

        def sandbox_fetch(url: str, *, use_proxy: bool = True) -> subprocess.CompletedProcess[str]:
            proxy_handler = "urllib.request.ProxyHandler()" if use_proxy else "urllib.request.ProxyHandler({})"
            code = f"import urllib.request; opener=urllib.request.build_opener({proxy_handler}); print(opener.open({url!r}, timeout=15).status)"
            return subprocess.run(
                ["docker", "exec", container_name, "python", "-c", code],
                capture_output=True,
                text=True,
                timeout=25,
            )

        allowed = sandbox_fetch("https://pypi.org/simple/")
        assert allowed.returncode == 0, allowed.stderr
        assert allowed.stdout.strip() == "200"

        denied = sandbox_fetch("https://example.com/")
        assert denied.returncode != 0
        events = backend.consume_network_policy_events(sandbox_id)
        assert [(event["host"], event["port"]) for event in events] == [("example.com", 443)]

        request_id = str(events[0]["request_id"])
        assert backend.decide_network_policy_request(sandbox_id, request_id, "allow_temporary")
        approved = sandbox_fetch("https://example.com/")
        assert approved.returncode == 0, approved.stderr
        assert approved.stdout.strip() == "200"

        metadata = sandbox_fetch("http://169.254.169.254/latest/meta-data/")
        assert metadata.returncode != 0
        assert backend.consume_network_policy_events(sandbox_id) == []

        direct = sandbox_fetch("https://example.com/", use_proxy=False)
        assert direct.returncode != 0
    finally:
        backend._cleanup_restricted_resources(sandbox_id)
        release_port(port)


def test_start_container_preinitialized_image_can_drop_startup_caps(monkeypatch):
    """A custom, pre-initialized non-root image never runs the root handoff,
    so CHOWN/FOWNER/SETUID/SETGID/DAC_OVERRIDE must not stay available for
    the container's lifetime (chown/chmod on bind mounts, UID/GID
    impersonation). Opting out with DEER_FLOW_SANDBOX_IMAGE_STARTUP_CAPS=0
    drops every capability."""
    backend = LocalContainerBackend(
        image="my-preinitialized-sandbox:latest",
        base_port=8080,
        container_prefix="sandbox",
        config_mounts=[],
        environment={},
    )
    _clear_hardening_env(monkeypatch)
    monkeypatch.setenv("DEER_FLOW_SANDBOX_IMAGE_STARTUP_CAPS", "0")

    captured_cmd = _capture_start_container_command(monkeypatch, backend)

    assert "--cap-drop=ALL" in captured_cmd
    assert not [arg for arg in captured_cmd if arg.startswith("--cap-add=")]
    security_opts = [captured_cmd[i + 1] for i, arg in enumerate(captured_cmd) if arg == "--security-opt"]
    assert "no-new-privileges" in security_opts


def test_docker_subprocess_calls_pin_utf8_decoding(monkeypatch):
    """Locale-default text decoding silently loses docker CLI output on hosts
    whose ANSI code page is not UTF-8 (e.g. cp936 Chinese Windows): the decode
    error surfaces inside subprocess's reader thread, so ``stdout``/``stderr``
    come back ``None``, and JSON-parsing call sites either crash on ``None``
    or silently mis-parse. Every text-mode call in this module must therefore
    pin ``encoding="utf-8"`` with ``errors="replace"``.
    """
    seen: list[dict] = []

    def fake_run(cmd, **kwargs):
        seen.append(kwargs)
        return SimpleNamespace(stdout='"Debian GNU/Linux 15"\n', stderr="", returncode=0)

    _docker_server_is_desktop.cache_clear()
    monkeypatch.setattr("subprocess.run", fake_run)
    try:
        backend = LocalContainerBackend(
            image="sandbox:latest",
            base_port=8080,
            container_prefix="sandbox",
            config_mounts=[],
            environment={},
        )
        assert backend._docker_server_is_desktop() is False
    finally:
        _docker_server_is_desktop.cache_clear()

    assert seen, "expected the docker detection path to shell out"
    for kwargs in seen:
        assert kwargs.get("encoding") == "utf-8", kwargs
        assert kwargs.get("errors") == "replace", kwargs


def test_every_text_mode_subprocess_call_pins_utf8():
    """Check each text-mode subprocess call's encoding and error handling.

    A text-mode call without ``encoding=`` decodes with the platform's
    preferred encoding, which loses output entirely on non-UTF-8 locales.
    ``errors="replace"`` also keeps malformed bytes from discarding a stream.
    """
    source = Path(local_backend_module.__file__).read_text(encoding="utf-8")
    calls = [node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == "subprocess" and node.func.attr == "run"]
    assert calls, "expected subprocess.run calls in the local backend"
    for call in calls:
        keywords = {keyword.arg: keyword.value for keyword in call.keywords}
        text_mode = keywords.get("text")
        if not isinstance(text_mode, ast.Constant) or text_mode.value is not True:
            continue
        for name, expected in (("encoding", "utf-8"), ("errors", "replace")):
            value = keywords.get(name)
            assert isinstance(value, ast.Constant) and value.value == expected, f"line {call.lineno}: text-mode subprocess.run must pass {name}={expected!r}"
