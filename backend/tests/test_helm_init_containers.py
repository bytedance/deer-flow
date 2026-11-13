"""The gateway's init containers must follow the chart's image and resource values.

``init-home`` and ``init-extensions`` hard-coded ``busybox:1.36`` and set no
resources. Clusters that pull only from a mirror could not start the gateway, and
a namespace ResourceQuota on ``limits.*`` rejected the pod, while every main
container already has configurable images and requests+limits.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CHART = REPO_ROOT / "deploy" / "helm" / "deer-flow"


def _init_containers(*settings: str) -> list[dict]:
    helm = shutil.which("helm")
    if helm is None:
        pytest.skip("helm is unavailable")
    command = [helm, "template", "deer-flow", str(CHART)]
    for setting in settings:
        command.extend(["--set", setting])
    rendered = subprocess.run(command, check=True, capture_output=True, text=True, encoding="utf-8").stdout
    gateways = [document for document in yaml.safe_load_all(rendered) if isinstance(document, dict) and document.get("kind") == "Deployment" and document["metadata"]["name"].endswith("-gateway")]
    assert len(gateways) == 1
    init_containers = gateways[0]["spec"]["template"]["spec"]["initContainers"]
    assert [container["name"] for container in init_containers] == ["init-home", "init-extensions"]
    return init_containers


def test_init_containers_keep_busybox_with_requests_and_limits_by_default() -> None:
    for container in _init_containers():
        assert container["image"] == "busybox:1.36"
        assert set(container["resources"]) == {"requests", "limits"}
        assert set(container["resources"]["limits"]) == {"cpu", "memory"}


def test_init_containers_use_configured_image_and_resources() -> None:
    for container in _init_containers(
        "gateway.initContainers.image.repository=registry.example.com/mirror/busybox",
        "gateway.initContainers.image.tag=1.36.1",
        "gateway.initContainers.resources.limits.memory=32Mi",
    ):
        assert container["image"] == "registry.example.com/mirror/busybox:1.36.1"
        assert container["resources"]["limits"]["memory"] == "32Mi"
