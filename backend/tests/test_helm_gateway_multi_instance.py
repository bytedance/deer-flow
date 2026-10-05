"""Regression tests for Helm Gateway multi-instance topology declaration."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CHART = REPO_ROOT / "deploy" / "helm" / "deer-flow"
MULTI_INSTANCE_ENV = "DEER_FLOW_MULTI_INSTANCE"


def _gateway_env(*settings: str) -> dict[str, dict]:
    helm = shutil.which("helm")
    if helm is None:
        pytest.skip("helm is unavailable")
    command = [
        helm,
        "template",
        "deer-flow",
        str(CHART),
        "--show-only",
        "templates/gateway-deployment.yaml",
    ]
    for setting in settings:
        command.extend(["--set", setting])
    rendered = subprocess.run(command, check=True, capture_output=True, text=True).stdout
    deployment = yaml.safe_load(rendered)
    gateway = next(
        container
        for container in deployment["spec"]["template"]["spec"]["containers"]
        if container["name"] == "gateway"
    )
    return {item["name"]: item for item in gateway["env"]}


def test_single_gateway_replica_does_not_declare_multi_instance() -> None:
    env = _gateway_env()
    assert MULTI_INSTANCE_ENV not in env


@pytest.mark.parametrize("replicas", [2, 3])
def test_multiple_gateway_replicas_declare_multi_instance(replicas: int) -> None:
    env = _gateway_env(f"gateway.replicas={replicas}")
    assert env[MULTI_INSTANCE_ENV]["value"] == "true"
