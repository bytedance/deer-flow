"""Regression tests for provisioner kubeconfig path handling."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

# The provisioner image runs as uid 1000 (`deerflow`) and mounts the host
# kubeconfig here; see docker/provisioner/Dockerfile.
UNPRIVILEGED_KUBECONFIG_PATH = "/home/deerflow/.kube/config"


def test_kubeconfig_is_mounted_where_the_unprivileged_user_can_read_it():
    """The non-root provisioner must still be able to read its kubeconfig.

    ``python:3.12-slim-bookworm`` has ``/root`` at 0700 root:root, so a mount at
    ``/root/.kube/config`` is unreachable for uid 1000: ``os.path.exists()``
    returns False on EACCES, ``_init_k8s_client`` falls back to in-cluster config,
    and k8s sandbox mode stops working. The compose mounts, the image layout and
    the module default must therefore agree on one home-relative path.
    """
    for compose_name in ("docker/docker-compose.yaml", "docker/docker-compose-dev.yaml"):
        compose_path = REPO_ROOT / compose_name
        compose_text = compose_path.read_text(encoding="utf-8")
        service = yaml.safe_load(compose_text)["services"]["provisioner"]

        assert f"~/.kube/config:{UNPRIVILEGED_KUBECONFIG_PATH}:ro" in service["volumes"], compose_name
        assert f"KUBECONFIG_PATH={UNPRIVILEGED_KUBECONFIG_PATH}" in service["environment"], compose_name
        assert "/root/.kube" not in compose_text, compose_name

    app_source = (REPO_ROOT / "docker" / "provisioner" / "app.py").read_text(encoding="utf-8")
    default_path = re.search(r'KUBECONFIG_PATH = os\.environ\.get\("KUBECONFIG_PATH", "([^"]+)"\)', app_source)

    assert default_path is not None, "app.py must keep env-overridable KUBECONFIG_PATH default"
    assert default_path.group(1) == UNPRIVILEGED_KUBECONFIG_PATH
    assert "/root/.kube" not in app_source

    dockerfile = (REPO_ROOT / "docker" / "provisioner" / "Dockerfile").read_text(encoding="utf-8")
    mount_dir = UNPRIVILEGED_KUBECONFIG_PATH.rsplit("/", 1)[0]

    assert "useradd --create-home --uid 1000 deerflow" in dockerfile
    # The user owns the mount point's parent, so the read-only bind-mount target
    # stays reachable for it (/home/deerflow is not world-writable).
    assert f"install -d -o deerflow -g deerflow -m 0700 {mount_dir}" in dockerfile
    assert dockerfile.index("USER deerflow") > dockerfile.index(mount_dir)


def test_wait_for_kubeconfig_rejects_directory(tmp_path, provisioner_module):
    """Directory mount at kubeconfig path should fail fast with clear error."""
    kubeconfig_dir = tmp_path / "config_dir"
    kubeconfig_dir.mkdir()

    provisioner_module.KUBECONFIG_PATH = str(kubeconfig_dir)

    try:
        provisioner_module._wait_for_kubeconfig(timeout=1)
        raise AssertionError("Expected RuntimeError for directory kubeconfig path")
    except RuntimeError as exc:
        assert "directory" in str(exc)


def test_wait_for_kubeconfig_accepts_file(tmp_path, provisioner_module):
    """Regular file mount should pass readiness wait."""
    kubeconfig_file = tmp_path / "config"
    kubeconfig_file.write_text("apiVersion: v1\n")

    provisioner_module.KUBECONFIG_PATH = str(kubeconfig_file)

    # Should return immediately without raising.
    provisioner_module._wait_for_kubeconfig(timeout=1)


def test_init_k8s_client_rejects_directory_path(tmp_path, provisioner_module):
    """KUBECONFIG_PATH that resolves to a directory should be rejected."""
    kubeconfig_dir = tmp_path / "config_dir"
    kubeconfig_dir.mkdir()

    provisioner_module.KUBECONFIG_PATH = str(kubeconfig_dir)

    try:
        provisioner_module._init_k8s_client()
        raise AssertionError("Expected RuntimeError for directory kubeconfig path")
    except RuntimeError as exc:
        assert "expected a file" in str(exc)


def test_init_k8s_client_uses_file_kubeconfig(tmp_path, monkeypatch, provisioner_module):
    """When file exists, provisioner should load kubeconfig file path."""
    kubeconfig_file = tmp_path / "config"
    kubeconfig_file.write_text("apiVersion: v1\n")

    called: dict[str, object] = {}

    def fake_load_kube_config(config_file: str):
        called["config_file"] = config_file

    monkeypatch.setattr(
        provisioner_module.k8s_config,
        "load_kube_config",
        fake_load_kube_config,
    )
    monkeypatch.setattr(
        provisioner_module.k8s_client,
        "CoreV1Api",
        lambda *args, **kwargs: "core-v1",
    )

    provisioner_module.KUBECONFIG_PATH = str(kubeconfig_file)

    result = provisioner_module._init_k8s_client()

    assert called["config_file"] == str(kubeconfig_file)
    assert result == "core-v1"


def test_init_k8s_client_falls_back_to_incluster_when_missing(tmp_path, monkeypatch, provisioner_module):
    """When kubeconfig file is missing, in-cluster config should be attempted."""
    missing_path = tmp_path / "missing-config"

    calls: dict[str, int] = {"incluster": 0}

    def fake_load_incluster_config():
        calls["incluster"] += 1

    monkeypatch.setattr(
        provisioner_module.k8s_config,
        "load_incluster_config",
        fake_load_incluster_config,
    )
    monkeypatch.setattr(
        provisioner_module.k8s_client,
        "CoreV1Api",
        lambda *args, **kwargs: "core-v1",
    )

    provisioner_module.KUBECONFIG_PATH = str(missing_path)

    result = provisioner_module._init_k8s_client()

    assert calls["incluster"] == 1
    assert result == "core-v1"
