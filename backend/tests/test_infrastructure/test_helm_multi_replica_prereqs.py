"""Regression tests for the Helm chart's multi-replica prerequisites.

The chart used to ship ``gateway.replicas: 1`` with a README that cited the
long-closed issue #3948, while its rendered config lacked the two settings a
second Pod actually needs: run-ownership heartbeats (without a lease, a
starting Pod writes every peer's live run off as an orphan) and
database-backed run events. These tests pin the config block, the
``DEER_FLOW_MULTI_INSTANCE`` declaration the Gateway's startup gate reads
(derived from ``gateway.replicas`` or declared with ``gateway.multiInstance``
for deployments scaled by kubectl/HPA), the shared ``AUTH_JWT_SECRET`` that is
required once more than one instance runs, the ``existingAppSecret`` wiring,
the rollout strategy, the PodDisruptionBudget, and a termination grace period
that covers the shutdown work.

The ``helm template`` tests skip when helm is not installed; CI's runner has it.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from _gateway_shutdown_budget import lifespan_shutdown_seconds

REPO_ROOT = Path(__file__).resolve().parents[2]
CHART = REPO_ROOT / "deploy" / "helm" / "deer-flow"
VALUES = CHART / "values.yaml"
APP_SECRET_TEMPLATE = CHART / "templates" / "secret-app.yaml"
README = CHART / "README.md"


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


def _has_kind(documents: list[dict], kind: str) -> bool:
    return any(document.get("kind") == kind for document in documents)


def _container(documents: list[dict], deployment_suffix: str, container_name: str) -> dict:
    containers = _by_kind(documents, "Deployment", deployment_suffix)["spec"]["template"]["spec"]["containers"]
    return next(container for container in containers if container["name"] == container_name)


def _env(container: dict) -> dict[str, dict]:
    return {item["name"]: item for item in container["env"]}


def _secret_ref(container: dict, env_name: str) -> dict:
    return _env(container)[env_name]["valueFrom"]["secretKeyRef"]


def test_default_config_enables_the_multi_replica_prerequisites() -> None:
    config = _rendered_config()
    assert config["database"]["backend"] == "postgres"
    assert config["checkpointer"]["type"] == "postgres"
    assert config["stream_bridge"]["type"] == "redis"
    assert config["run_ownership"]["heartbeat_enabled"] is True, "without a lease every peer run is reclaimed as an orphan on Pod start"
    assert config["run_events"]["backend"] == "db", "memory run events are process-local"


def test_default_replica_count_stays_conservative_with_a_rollout_budget() -> None:
    values = _values()
    gateway = values["gateway"]
    assert gateway["replicas"] == 1
    assert gateway["multiInstance"] is None, "derived from replicas unless the operator declares it"
    assert gateway["strategy"]["type"] == "RollingUpdate"
    assert gateway["strategy"]["rollingUpdate"]["maxUnavailable"] == 0
    assert gateway["strategy"]["rollingUpdate"]["maxSurge"] == 1
    assert gateway["podDisruptionBudget"]["enabled"] is True
    assert gateway["podDisruptionBudget"]["minAvailable"] == 1
    assert values["existingAppSecret"] == ""


def test_termination_grace_period_covers_the_shutdown_work() -> None:
    gateway = _values()["gateway"]
    required = gateway["preStopSleepSeconds"] + gateway["uvicornGracefulShutdownSeconds"] + lifespan_shutdown_seconds()
    assert gateway["terminationGracePeriodSeconds"] > required, f"grace period must exceed {required}s of shutdown work"


def test_app_secret_template_preserves_the_jwt_secret_across_upgrades() -> None:
    """``helm template`` never sees ``lookup`` results, so pin the preservation in the source."""
    template = APP_SECRET_TEMPLATE.read_text(encoding="utf-8")
    assert 'index $prev.data "AUTH_JWT_SECRET"' in template, "must survive upgrades like the other app secrets"
    assert "AUTH_JWT_SECRET: {{ $jwtSecret | quote }}" in template


def test_readme_documents_the_multi_instance_knobs() -> None:
    readme = README.read_text(encoding="utf-8")
    assert re.search(r"do not raise\s+`gateway\.replicas` past 1", readme) is None
    for needle in ("DEER_FLOW_MULTI_INSTANCE", "AUTH_JWT_SECRET", "gateway.multiInstance", "existingAppSecret", ".jwt_secret"):
        assert needle in readme, needle


@pytest.mark.parametrize("replicas", [1, 2, 3])
def test_rendered_declaration_follows_the_replica_count(replicas: int) -> None:
    values = _values()["gateway"]
    documents = _render_chart(f"gateway.replicas={replicas}")
    gateway = _container(documents, "-gateway", "gateway")
    multi_instance = replicas > 1

    assert _env(gateway)["DEER_FLOW_MULTI_INSTANCE"]["value"] == str(multi_instance).lower()
    jwt = _secret_ref(gateway, "AUTH_JWT_SECRET")
    assert jwt["name"].endswith("-app")
    assert jwt["key"] == "AUTH_JWT_SECRET"
    assert jwt["optional"] is (not multi_instance), "the shared key is required once Pods could race to write .jwt_secret"
    assert f"--timeout-graceful-shutdown {values['uvicornGracefulShutdownSeconds']}" in " ".join(gateway["args"])

    assert _has_kind(documents, "PodDisruptionBudget") is multi_instance
    if multi_instance:
        assert _by_kind(documents, "PodDisruptionBudget", "-gateway")["spec"]["minAvailable"] == values["podDisruptionBudget"]["minAvailable"]

    deployment = _by_kind(documents, "Deployment", "-gateway")
    assert deployment["spec"]["strategy"] == values["strategy"]
    assert deployment["spec"]["template"]["spec"]["terminationGracePeriodSeconds"] == values["terminationGracePeriodSeconds"]


def test_explicit_multi_instance_declaration_wins_over_the_replica_count() -> None:
    """kubectl scale and HPAs change the count without a Helm upgrade, so the operator declares it."""
    documents = _render_chart("gateway.replicas=1", "gateway.multiInstance=true")
    gateway = _container(documents, "-gateway", "gateway")
    assert _env(gateway)["DEER_FLOW_MULTI_INSTANCE"]["value"] == "true"
    assert _secret_ref(gateway, "AUTH_JWT_SECRET")["optional"] is False
    assert _has_kind(documents, "PodDisruptionBudget")


def test_pdb_can_be_disabled_and_a_zero_graceful_shutdown_is_honored() -> None:
    documents = _render_chart("gateway.replicas=2", "gateway.podDisruptionBudget.enabled=false", "gateway.uvicornGracefulShutdownSeconds=0")
    assert not _has_kind(documents, "PodDisruptionBudget")
    assert "--timeout-graceful-shutdown 0" in " ".join(_container(documents, "-gateway", "gateway")["args"])


def test_existing_app_secret_is_honored_by_every_consumer() -> None:
    """The helper used to ignore the value, so Pods referenced a Secret the chart no longer rendered."""
    documents = _render_chart("existingAppSecret=my-app-secret", "gateway.replicas=2")
    assert not any(document.get("kind") == "Secret" and document["metadata"]["name"].endswith("-app") for document in documents)
    gateway = _container(documents, "-gateway", "gateway")
    assert _secret_ref(gateway, "DEER_FLOW_INTERNAL_AUTH_TOKEN")["name"] == "my-app-secret"
    assert _secret_ref(gateway, "AUTH_JWT_SECRET")["name"] == "my-app-secret"
    frontend = _container(documents, "-frontend", "frontend")
    assert _secret_ref(frontend, "BETTER_AUTH_SECRET")["name"] == "my-app-secret"


def test_rendered_app_secret_carries_the_jwt_secret() -> None:
    documents = _render_chart()
    secret = _by_kind(documents, "Secret", "-app")
    assert secret["stringData"]["AUTH_JWT_SECRET"]
