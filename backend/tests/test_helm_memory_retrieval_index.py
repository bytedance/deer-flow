"""Regression tests for the Helm chart's Pod-local DeerMem retrieval index.

The chart's default ``config`` carried a legacy ``memory.storage_path:
memory.json`` line that the Gateway dropped with a warning at every start, and
nothing kept DeerMem's derived SQLite FTS5 index off the shared home volume: with
``gateway.replicas > 1`` every Pod opened one WAL database over the
ReadWriteMany filesystem, rebuilt it under its peers at startup and deleted it
from under them on corruption recovery. These tests pin the ``emptyDir`` mounted
at the index path, the ``memory.backend_config.retrieval_index_path`` that
points DeerMem at it, the removal of the legacy key, the config_version sync,
and the operator notes.

The ``helm template`` tests skip when helm is not installed; CI's runner has it.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CHART = REPO_ROOT / "deploy" / "helm" / "deer-flow"
VALUES = CHART / "values.yaml"
README = CHART / "README.md"
NOTES = CHART / "templates" / "NOTES.txt"
GATEWAY_TEMPLATE = CHART / "templates" / "gateway-deployment.yaml"
CONFIG_EXAMPLE = REPO_ROOT / "config.example.yaml"

INDEX_PATH = "/var/lib/deerflow/memory-index"
VOLUME_NAME = "memory-index"


def _values() -> dict:
    return yaml.safe_load(VALUES.read_text(encoding="utf-8"))


def _rendered_config() -> dict:
    return yaml.safe_load(_values()["config"])


def _render_chart(*settings: str) -> list[dict]:
    helm = shutil.which("helm")
    if helm is None:
        pytest.skip("helm is unavailable")
    command = [helm, "template", "deer-flow", str(CHART)]
    for setting in settings:
        command.extend(["--set", setting])
    rendered = subprocess.run(command, check=True, capture_output=True, text=True).stdout
    return [document for document in yaml.safe_load_all(rendered) if isinstance(document, dict)]


def _by_kind(documents: list[dict], kind: str, name_suffix: str) -> dict:
    return next(document for document in documents if document.get("kind") == kind and document["metadata"]["name"].endswith(name_suffix))


def _gateway_pod(documents: list[dict]) -> dict:
    return _by_kind(documents, "Deployment", "-gateway")["spec"]["template"]["spec"]


def test_default_config_points_deermem_at_the_pod_local_index() -> None:
    memory = _rendered_config()["memory"]
    assert memory["backend_config"]["retrieval_index_path"] == INDEX_PATH
    assert "storage_path" not in memory, "the legacy file-style key was dropped with a warning at every Gateway start"
    assert "storage_path" not in memory["backend_config"], "canonical memory stays at the default root on the home volume"


def test_gateway_template_mounts_an_empty_dir_at_the_index_path() -> None:
    template = GATEWAY_TEMPLATE.read_text(encoding="utf-8")
    assert re.search(rf"- name: {VOLUME_NAME}\n\s+mountPath: {re.escape(INDEX_PATH)}\n", template), "the gateway container must mount the index volume at the configured path"
    assert re.search(rf"- name: {VOLUME_NAME}\n\s+emptyDir: \{{\}}", template), "the index is rebuildable derived data, so a Pod-local emptyDir is enough"


def test_chart_config_version_tracks_the_example() -> None:
    example = yaml.safe_load(CONFIG_EXAMPLE.read_text(encoding="utf-8"))["config_version"]
    chart = _rendered_config()["config_version"]
    assert chart >= example, "scripts/check_config_version.sh fails the chart build when it lags"
    readme_versions = {int(value) for value in re.findall(r"^\s+config_version:\s+(\d+)$", README.read_text(encoding="utf-8"), flags=re.MULTILINE)}
    assert readme_versions == {chart}, "the README's config example must show the chart's version"


def test_operator_notes_document_the_pod_local_index() -> None:
    for path in (VALUES, README, NOTES):
        text = path.read_text(encoding="utf-8")
        assert "retrieval_index_path" in text, path.name
        assert INDEX_PATH in text, path.name


def test_rendered_gateway_pod_keeps_the_retrieval_index_on_an_empty_dir() -> None:
    documents = _render_chart("gateway.replicas=2")
    pod = _gateway_pod(documents)
    gateway = next(container for container in pod["containers"] if container["name"] == "gateway")
    mount = next(item for item in gateway["volumeMounts"] if item["name"] == VOLUME_NAME)
    assert mount["mountPath"] == INDEX_PATH
    assert "subPath" not in mount
    volume = next(item for item in pod["volumes"] if item["name"] == VOLUME_NAME)
    assert volume == {"name": VOLUME_NAME, "emptyDir": {}}
    assert pod["securityContext"]["fsGroup"] == 1000, "the emptyDir is group-writable for the non-root gateway user"


def test_rendered_config_map_carries_the_index_path() -> None:
    documents = _render_chart()
    config = yaml.safe_load(_by_kind(documents, "ConfigMap", "-config")["data"]["config.yaml"])
    assert config["memory"]["backend_config"]["retrieval_index_path"] == INDEX_PATH
    assert "storage_path" not in config["memory"]
