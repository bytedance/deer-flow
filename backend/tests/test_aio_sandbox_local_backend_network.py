"""Tests for the Docker network mode in :class:`LocalContainerBackend`.

The legacy port-mapping path stays the default; these tests pin the new
network-mode behavior introduced for issue #2600 — sandbox containers
join a shared Docker network and are reached via container-name DNS so
the gateway/langgraph processes do not have to route through
``host-gateway``.
"""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from deerflow.community.aio_sandbox.local_backend import LocalContainerBackend
from deerflow.community.aio_sandbox.sandbox_info import SandboxInfo


def _make_backend(*, network: str | None, runtime: str = "docker", network_exists: bool = True) -> LocalContainerBackend:
    """Construct a backend with the runtime and network-existence checks stubbed.

    Patches ``_detect_runtime`` and ``_docker_network_exists`` so tests do
    not depend on the host having Docker installed.
    """
    with (
        patch.object(LocalContainerBackend, "_detect_runtime", return_value=runtime),
        patch.object(LocalContainerBackend, "_docker_network_exists", return_value=network_exists),
    ):
        return LocalContainerBackend(
            image="test-image:latest",
            base_port=8080,
            container_prefix="deer-flow-sandbox",
            config_mounts=[],
            environment={},
            network=network,
        )


# ---------------------------------------------------------------------------
# _resolve_network
# ---------------------------------------------------------------------------


def test_resolve_network_returns_none_when_unset() -> None:
    backend = _make_backend(network=None)
    assert backend._network is None


def test_resolve_network_keeps_name_when_docker_and_network_exists() -> None:
    backend = _make_backend(network="deer-flow")
    assert backend._network == "deer-flow"


def test_resolve_network_falls_back_to_none_for_apple_container() -> None:
    backend = _make_backend(network="deer-flow", runtime="container")
    assert backend._network is None


def test_resolve_network_raises_when_network_missing() -> None:
    with pytest.raises(RuntimeError, match="does not exist"):
        _make_backend(network="missing-net", network_exists=False)


# ---------------------------------------------------------------------------
# _start_container command construction
# ---------------------------------------------------------------------------


def test_start_container_uses_network_flag_in_network_mode() -> None:
    backend = _make_backend(network="deer-flow")

    captured: dict[str, list[str]] = {}

    def fake_run(cmd, **kwargs):  # noqa: ANN001 - subprocess.run signature
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="cid123\n", stderr="")

    with patch("deerflow.community.aio_sandbox.local_backend.subprocess.run", side_effect=fake_run):
        backend._start_container("deer-flow-sandbox-abc", port=None, extra_mounts=None)

    cmd = captured["cmd"]
    assert "--network" in cmd
    assert cmd[cmd.index("--network") + 1] == "deer-flow"
    # Network mode must NOT publish a host port.
    assert "-p" not in cmd
    # Container name still set.
    assert "--name" in cmd
    assert cmd[cmd.index("--name") + 1] == "deer-flow-sandbox-abc"


def test_start_container_uses_port_publish_in_legacy_mode() -> None:
    backend = _make_backend(network=None)

    captured: dict[str, list[str]] = {}

    def fake_run(cmd, **kwargs):  # noqa: ANN001
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="cid456\n", stderr="")

    with patch("deerflow.community.aio_sandbox.local_backend.subprocess.run", side_effect=fake_run):
        backend._start_container("deer-flow-sandbox-xyz", port=9999, extra_mounts=None)

    cmd = captured["cmd"]
    assert "--network" not in cmd
    assert "-p" in cmd
    assert cmd[cmd.index("-p") + 1] == "9999:8080"


def test_start_container_rejects_missing_port_in_legacy_mode() -> None:
    backend = _make_backend(network=None)
    with pytest.raises(RuntimeError, match="port must be provided"):
        backend._start_container("deer-flow-sandbox-zzz", port=None, extra_mounts=None)


# ---------------------------------------------------------------------------
# create() — SandboxInfo URL shape
# ---------------------------------------------------------------------------


def test_create_returns_container_name_url_in_network_mode() -> None:
    backend = _make_backend(network="deer-flow")

    with patch.object(LocalContainerBackend, "_start_container", return_value="cid-net") as start:
        info = backend.create("thread-1", "sandbox-net-1")

    start.assert_called_once_with("deer-flow-sandbox-sandbox-net-1", port=None, extra_mounts=None)
    assert info.sandbox_url == "http://deer-flow-sandbox-sandbox-net-1:8080"
    assert info.container_name == "deer-flow-sandbox-sandbox-net-1"
    assert info.container_id == "cid-net"


def test_create_returns_host_port_url_in_legacy_mode(monkeypatch) -> None:
    backend = _make_backend(network=None)

    with (
        patch("deerflow.community.aio_sandbox.local_backend.get_free_port", return_value=8123),
        patch.object(LocalContainerBackend, "_start_container", return_value="cid-host"),
    ):
        monkeypatch.delenv("DEER_FLOW_SANDBOX_HOST", raising=False)
        info = backend.create("thread-2", "sandbox-host-2")

    assert info.sandbox_url == "http://localhost:8123"
    assert info.container_name == "deer-flow-sandbox-sandbox-host-2"


def test_create_in_network_mode_skips_get_free_port() -> None:
    backend = _make_backend(network="deer-flow")

    with (
        patch("deerflow.community.aio_sandbox.local_backend.get_free_port") as get_free_port,
        patch.object(LocalContainerBackend, "_start_container", return_value="cid"),
    ):
        backend.create("thread-3", "sandbox-3")

    get_free_port.assert_not_called()


# ---------------------------------------------------------------------------
# discover() — URL shape
# ---------------------------------------------------------------------------


def test_discover_returns_container_name_url_in_network_mode() -> None:
    backend = _make_backend(network="deer-flow")

    with (
        patch.object(LocalContainerBackend, "_is_container_running", return_value=True),
        patch.object(LocalContainerBackend, "_get_container_port") as get_port,
        patch("deerflow.community.aio_sandbox.local_backend.wait_for_sandbox_ready", return_value=True),
    ):
        info = backend.discover("sandbox-disc")

    # _get_container_port must NOT be called in network mode — there is no
    # host port mapping to look up.
    get_port.assert_not_called()
    assert info is not None
    assert info.sandbox_url == "http://deer-flow-sandbox-sandbox-disc:8080"


def test_discover_uses_host_port_in_legacy_mode(monkeypatch) -> None:
    backend = _make_backend(network=None)

    with (
        patch.object(LocalContainerBackend, "_is_container_running", return_value=True),
        patch.object(LocalContainerBackend, "_get_container_port", return_value=9090),
        patch("deerflow.community.aio_sandbox.local_backend.wait_for_sandbox_ready", return_value=True),
    ):
        monkeypatch.delenv("DEER_FLOW_SANDBOX_HOST", raising=False)
        info = backend.discover("sandbox-disc-legacy")

    assert info is not None
    assert info.sandbox_url == "http://localhost:9090"


# ---------------------------------------------------------------------------
# destroy() — port release behavior
# ---------------------------------------------------------------------------


def test_destroy_skips_release_port_in_network_mode() -> None:
    backend = _make_backend(network="deer-flow")
    info = SandboxInfo(
        sandbox_id="x",
        sandbox_url="http://deer-flow-sandbox-x:8080",
        container_name="deer-flow-sandbox-x",
        container_id="cid",
    )

    with (
        patch.object(LocalContainerBackend, "_stop_container") as stop,
        patch("deerflow.community.aio_sandbox.local_backend.release_port") as release,
    ):
        backend.destroy(info)

    stop.assert_called_once()
    release.assert_not_called()


def test_destroy_releases_port_in_legacy_mode() -> None:
    backend = _make_backend(network=None)
    info = SandboxInfo(
        sandbox_id="x",
        sandbox_url="http://localhost:8123",
        container_name="deer-flow-sandbox-x",
        container_id="cid",
    )

    with (
        patch.object(LocalContainerBackend, "_stop_container"),
        patch("deerflow.community.aio_sandbox.local_backend.release_port") as release,
    ):
        backend.destroy(info)

    release.assert_called_once_with(8123)
