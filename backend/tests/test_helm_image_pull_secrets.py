"""Every chart workload must honour ``image.pullSecrets``.

``values.yaml`` documents ``image.pullSecrets`` as the way to pull from a private
registry, and the frontend, gateway, provisioner, Postgres and Redis pods all
include ``deer-flow.imagePullSecrets``. The nginx Deployment did not, so with a
mirrored ``nginx.image`` in a private registry the nginx pod stayed in
``ImagePullBackOff`` while every other pod started.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CHART = REPO_ROOT / "deploy" / "helm" / "deer-flow"

# Enable every optional workload so the test covers all pod templates.
ALL_WORKLOADS = ("provisioner.enabled=true", "postgresql.enabled=true", "redis.enabled=true")


def _render_chart(*settings: str) -> list[dict]:
    helm = shutil.which("helm")
    if helm is None:
        pytest.skip("helm is unavailable")
    command = [helm, "template", "deer-flow", str(CHART)]
    for setting in settings:
        command.extend(["--set", setting])
    rendered = subprocess.run(command, check=True, capture_output=True, text=True, encoding="utf-8").stdout
    return [document for document in yaml.safe_load_all(rendered) if isinstance(document, dict)]


def _workloads(documents: list[dict]) -> dict[str, dict]:
    return {document["metadata"]["name"]: document["spec"]["template"]["spec"] for document in documents if document.get("kind") in {"Deployment", "StatefulSet"}}


def test_every_workload_uses_configured_pull_secrets() -> None:
    workloads = _workloads(_render_chart(*ALL_WORKLOADS, "image.pullSecrets[0].name=registry-credentials"))
    assert any(name.endswith("-nginx") for name in workloads)
    missing = sorted(name for name, pod in workloads.items() if pod.get("imagePullSecrets") != [{"name": "registry-credentials"}])
    assert missing == []


def test_no_workload_sets_pull_secrets_by_default() -> None:
    workloads = _workloads(_render_chart(*ALL_WORKLOADS))
    assert [name for name, pod in workloads.items() if "imagePullSecrets" in pod] == []
