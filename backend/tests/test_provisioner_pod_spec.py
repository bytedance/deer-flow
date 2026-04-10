"""Regression tests for provisioner sandbox pod spec generation."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_provisioner_module():
    """Load docker/provisioner/app.py as an importable test module."""
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "docker" / "provisioner" / "app.py"
    spec = importlib.util.spec_from_file_location("provisioner_app_pod_spec_test", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_pod_omits_env_from_when_sandbox_secret_is_unset():
    provisioner_module = _load_provisioner_module()
    provisioner_module.SANDBOX_ENV_SECRET = ""

    pod = provisioner_module._build_pod("sandbox-1", "thread-1")
    container = pod.spec.containers[0]

    assert container.env_from is None


def test_build_pod_adds_secret_env_from_when_configured():
    provisioner_module = _load_provisioner_module()
    provisioner_module.SANDBOX_ENV_SECRET = "sandbox-env"

    pod = provisioner_module._build_pod("sandbox-1", "thread-1")
    container = pod.spec.containers[0]

    assert container.env_from is not None
    assert len(container.env_from) == 1
    assert container.env_from[0].secret_ref is not None
    assert container.env_from[0].secret_ref.name == "sandbox-env"
