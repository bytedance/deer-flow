"""Regression tests for the Helm chart's multi-replica prerequisites.

The chart used to ship ``gateway.replicas: 1`` with a README that cited the
long-closed issue #3948, while its rendered config lacked the two settings a
second Pod actually needs: run-ownership heartbeats (without a lease, a
starting Pod writes every peer's live run off as an orphan) and
database-backed run events. These tests pin the config block, the
``DEER_FLOW_MULTI_INSTANCE`` declaration the Gateway's startup gate reads, the
shared ``AUTH_JWT_SECRET``, the rollout strategy, the PodDisruptionBudget, and
a termination grace period that covers the shutdown work.
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
GATEWAY_TEMPLATE = CHART / "templates" / "gateway-deployment.yaml"
PDB_TEMPLATE = CHART / "templates" / "gateway-pdb.yaml"
APP_SECRET_TEMPLATE = CHART / "templates" / "secret-app.yaml"
README = CHART / "README.md"

# Shutdown work the grace period must cover besides the preStop sleep and the
# uvicorn graceful-shutdown bound: channel stop, the in-flight run drain, and
# the memory queue flush (memory.shutdown_flush_timeout_seconds default).
CHANNEL_STOP_SECONDS = 5
RUN_DRAIN_SECONDS = 5
MEMORY_FLUSH_SECONDS = 30


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


def _gateway_deployment(documents: list[dict]) -> dict:
    return next(document for document in documents if document.get("kind") == "Deployment" and document["metadata"]["name"].endswith("-gateway"))


def _gateway_container(documents: list[dict]) -> dict:
    containers = _gateway_deployment(documents)["spec"]["template"]["spec"]["containers"]
    return next(container for container in containers if container["name"] == "gateway")


def test_default_config_enables_the_multi_replica_prerequisites() -> None:
    config = _rendered_config()
    assert config["database"]["backend"] == "postgres"
    assert config["checkpointer"]["type"] == "postgres"
    assert config["stream_bridge"]["type"] == "redis"
    assert config["run_ownership"]["heartbeat_enabled"] is True, "without a lease every peer run is reclaimed as an orphan on Pod start"
    assert config["run_events"]["backend"] == "db", "memory run events are process-local"


def test_default_replica_count_stays_conservative_with_a_rollout_budget() -> None:
    gateway = _values()["gateway"]
    assert gateway["replicas"] == 1
    assert gateway["strategy"]["type"] == "RollingUpdate"
    assert gateway["strategy"]["rollingUpdate"]["maxUnavailable"] == 0
    assert gateway["strategy"]["rollingUpdate"]["maxSurge"] == 1
    assert gateway["podDisruptionBudget"]["enabled"] is True
    assert gateway["podDisruptionBudget"]["minAvailable"] == 1


def test_termination_grace_period_covers_the_shutdown_work() -> None:
    gateway = _values()["gateway"]
    required = gateway["preStopSleepSeconds"] + gateway["uvicornGracefulShutdownSeconds"] + CHANNEL_STOP_SECONDS + RUN_DRAIN_SECONDS + MEMORY_FLUSH_SECONDS
    assert gateway["terminationGracePeriodSeconds"] > required, f"grace period must exceed {required}s of shutdown work"


def test_gateway_template_wires_the_multi_instance_declaration_and_shutdown_bound() -> None:
    template = GATEWAY_TEMPLATE.read_text(encoding="utf-8")
    assert "name: DEER_FLOW_MULTI_INSTANCE" in template
    assert "gt (int .Values.gateway.replicas) 1" in template
    assert "--timeout-graceful-shutdown {{ .Values.gateway.uvicornGracefulShutdownSeconds" in template
    assert "{{- with .Values.gateway.strategy }}" in template
    assert "key: AUTH_JWT_SECRET" in template
    assert "optional: true" in template


def test_app_secret_template_generates_and_preserves_the_jwt_secret() -> None:
    template = APP_SECRET_TEMPLATE.read_text(encoding="utf-8")
    assert 'index $prev.data "AUTH_JWT_SECRET"' in template, "must survive upgrades like the other app secrets"
    assert "AUTH_JWT_SECRET: {{ $jwtSecret | quote }}" in template


def test_pdb_template_only_renders_for_several_replicas() -> None:
    template = PDB_TEMPLATE.read_text(encoding="utf-8")
    assert "kind: PodDisruptionBudget" in template
    assert "gt (int .Values.gateway.replicas) 1" in template


def test_readme_no_longer_cites_the_closed_run_control_issue_as_a_blocker() -> None:
    readme = README.read_text(encoding="utf-8")
    assert re.search(r"do not raise\s+`gateway\.replicas` past 1", readme) is None
    assert "DEER_FLOW_MULTI_INSTANCE" in readme
    assert "AUTH_JWT_SECRET" in readme


@pytest.mark.parametrize("replicas", [1, 2, 3])
def test_rendered_declaration_follows_the_replica_count(replicas: int) -> None:
    documents = _render_chart(f"gateway.replicas={replicas}")
    gateway = _gateway_container(documents)
    env = {item["name"]: item for item in gateway["env"]}
    assert env["DEER_FLOW_MULTI_INSTANCE"]["value"] == ("true" if replicas > 1 else "false")
    assert env["AUTH_JWT_SECRET"]["valueFrom"]["secretKeyRef"]["key"] == "AUTH_JWT_SECRET"
    assert env["AUTH_JWT_SECRET"]["valueFrom"]["secretKeyRef"]["optional"] is True
    assert "--timeout-graceful-shutdown 10" in " ".join(gateway["args"])
    pdbs = [document for document in documents if document.get("kind") == "PodDisruptionBudget"]
    assert bool(pdbs) is (replicas > 1)
    if pdbs:
        assert pdbs[0]["spec"]["minAvailable"] == 1
    deployment = _gateway_deployment(documents)
    assert deployment["spec"]["strategy"]["rollingUpdate"]["maxUnavailable"] == 0
    assert deployment["spec"]["template"]["spec"]["terminationGracePeriodSeconds"] == 90


def test_rendered_app_secret_carries_the_jwt_secret() -> None:
    documents = _render_chart()
    secret = next(document for document in documents if document.get("kind") == "Secret" and document["metadata"]["name"].endswith("-app"))
    assert secret["stringData"]["AUTH_JWT_SECRET"]
