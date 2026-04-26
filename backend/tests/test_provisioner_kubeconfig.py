"""Regression tests for provisioner kubeconfig path handling."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_provisioner_module():
    """Load docker/provisioner/app.py as an importable test module."""
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "docker" / "provisioner" / "app.py"
    spec = importlib.util.spec_from_file_location("provisioner_app_test", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_wait_for_kubeconfig_rejects_directory(tmp_path):
    """Directory mount at kubeconfig path should fail fast with clear error."""
    provisioner_module = _load_provisioner_module()
    kubeconfig_dir = tmp_path / "config_dir"
    kubeconfig_dir.mkdir()

    provisioner_module.KUBECONFIG_PATH = str(kubeconfig_dir)

    try:
        provisioner_module._wait_for_kubeconfig(timeout=1)
        raise AssertionError("Expected RuntimeError for directory kubeconfig path")
    except RuntimeError as exc:
        assert "directory" in str(exc)


def test_wait_for_kubeconfig_accepts_file(tmp_path):
    """Regular file mount should pass readiness wait."""
    provisioner_module = _load_provisioner_module()
    kubeconfig_file = tmp_path / "config"
    kubeconfig_file.write_text("apiVersion: v1\n")

    provisioner_module.KUBECONFIG_PATH = str(kubeconfig_file)

    # Should return immediately without raising.
    provisioner_module._wait_for_kubeconfig(timeout=1)


def test_init_k8s_client_rejects_directory_path(tmp_path):
    """KUBECONFIG_PATH that resolves to a directory should be rejected."""
    provisioner_module = _load_provisioner_module()
    kubeconfig_dir = tmp_path / "config_dir"
    kubeconfig_dir.mkdir()

    provisioner_module.KUBECONFIG_PATH = str(kubeconfig_dir)

    try:
        provisioner_module._init_k8s_client()
        raise AssertionError("Expected RuntimeError for directory kubeconfig path")
    except RuntimeError as exc:
        assert "expected a file" in str(exc)


def test_init_k8s_client_uses_file_kubeconfig(tmp_path, monkeypatch):
    """When file exists, provisioner should load kubeconfig file path."""
    provisioner_module = _load_provisioner_module()
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


def test_init_k8s_client_falls_back_to_incluster_when_missing(tmp_path, monkeypatch):
    """When kubeconfig file is missing, in-cluster config should be attempted."""
    provisioner_module = _load_provisioner_module()
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
