"""Regression tests for the Helm extensions config write path."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CHART = REPO_ROOT / "deploy" / "helm" / "deer-flow"
GATEWAY_TEMPLATE = CHART / "templates" / "gateway-deployment.yaml"
RUNTIME_CONFIG_PATH = "/app/backend/.deer-flow/extensions-config/extensions_config.json"


def _render_chart(*settings: str) -> list[dict]:
    helm = shutil.which("helm")
    if helm is None:
        pytest.skip("helm is unavailable")
    command = [helm, "template", "deer-flow", str(CHART)]
    for setting in settings:
        command.extend(["--set", setting])
    rendered = subprocess.run(command, check=True, capture_output=True, text=True).stdout
    return [document for document in yaml.safe_load_all(rendered) if isinstance(document, dict)]


def _gateway_deployment(documents: list[dict]) -> dict:
    return next(document for document in documents if document.get("kind") == "Deployment" and document["metadata"]["name"].endswith("-gateway"))


def _named(items: list[dict], name: str) -> dict:
    return next(item for item in items if item["name"] == name)


def test_helm_template_seeds_a_directory_backed_writable_extensions_config() -> None:
    template = GATEWAY_TEMPLATE.read_text(encoding="utf-8")
    assert f"value: {RUNTIME_CONFIG_PATH}" in template
    assert "name: init-extensions" in template
    assert "cp /extensions-seed/extensions_config.json /extensions-runtime/extensions_config.json" in template
    assert "mountPath: /extensions-seed" in template
    assert "mountPath: /app/backend/extensions_config.json" not in template
    assert "subPath: extensions_config.json" not in template


@pytest.mark.parametrize("persistence_enabled", [True, False])
def test_rendered_helm_extensions_config_is_writable_and_seeded(persistence_enabled: bool) -> None:
    documents = _render_chart(f"persistence.home.enabled={str(persistence_enabled).lower()}")
    deployment = _gateway_deployment(documents)
    pod_spec = deployment["spec"]["template"]["spec"]
    gateway = _named(pod_spec["containers"], "gateway")
    init_extensions = _named(pod_spec["initContainers"], "init-extensions")

    env = {item["name"]: item for item in gateway["env"]}
    assert env["DEER_FLOW_EXTENSIONS_CONFIG_PATH"]["value"] == RUNTIME_CONFIG_PATH

    seed_mount = _named(init_extensions["volumeMounts"], "extensions-seed")
    assert seed_mount["mountPath"] == "/extensions-seed"
    assert seed_mount["readOnly"] is True
    runtime_mount = _named(init_extensions["volumeMounts"], "home")
    assert runtime_mount["mountPath"] == "/extensions-runtime"
    assert runtime_mount["subPath"] == "deer-flow/extensions-config"

    home_mount = _named(gateway["volumeMounts"], "home")
    assert home_mount["mountPath"] == "/app/backend/.deer-flow"
    assert home_mount["subPath"] == "deer-flow"
    assert "readOnly" not in home_mount

    volumes = {item["name"]: item for item in pod_spec["volumes"]}
    assert volumes["extensions-seed"]["configMap"]["name"].endswith("-extensions")
    if persistence_enabled:
        assert volumes["home"]["persistentVolumeClaim"]["claimName"].endswith("-home")
    else:
        assert volumes["home"]["emptyDir"] == {}
