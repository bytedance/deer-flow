"""Helm chart rendering and secret/mount/prereq contract tests (`deploy/helm/deer-flow`)."""

from __future__ import annotations

import base64
import os
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
import yaml
from _gateway_shutdown_budget import lifespan_shutdown_seconds
from cryptography.fernet import Fernet
from support.shell import require_posix_sh

from deerflow.config.app_config import AppConfig
from deerflow.config.credentials_key import CREDENTIALS_KEY_ENV_VAR, parse_credentials_keys

REPO_ROOT = Path(__file__).resolve().parents[2]
CHART = REPO_ROOT / "deploy" / "helm" / "deer-flow"
VALUES = CHART / "values.yaml"
APP_SECRET_TEMPLATE = CHART / "templates" / "secret-app.yaml"
GATEWAY_TEMPLATE = CHART / "templates" / "gateway-deployment.yaml"
README = CHART / "README.md"
NOTES = CHART / "templates" / "NOTES.txt"


def _render_chart(*settings: str, release: str = "deer-flow") -> list[dict]:
    helm = shutil.which("helm")
    if helm is None:
        pytest.skip("helm is unavailable")
    command = [helm, "template", release, str(CHART)]
    for setting in settings:
        command.extend(["--set", setting])
    rendered = subprocess.run(command, check=True, capture_output=True, text=True, encoding="utf-8").stdout
    return [document for document in yaml.safe_load_all(rendered) if isinstance(document, dict)]


def _render_chart_with_fixed_app_secret(*settings: str) -> list[dict]:
    return _render_chart("existingAppSecret=fixed-app-secret", *settings, release=RELEASE)


def _values() -> dict:
    return yaml.safe_load(VALUES.read_text(encoding="utf-8"))


def _rendered_config() -> dict:
    return yaml.safe_load(_values()["config"])


def _by_kind(documents: list[dict], kind: str, name_suffix: str) -> dict:
    return next(document for document in documents if document.get("kind") == kind and document.get("metadata", {}).get("name", "").endswith(name_suffix))


def _env(container: dict) -> dict[str, dict]:
    return {entry["name"]: entry for entry in container.get("env", [])}


def _container(documents: list[dict], workload_suffix: str, container_name: str | None = None) -> dict:
    if container_name is None:
        workload = next(document for document in documents if document.get("kind") in {"Deployment", "StatefulSet"} and document["metadata"]["name"].endswith(f"-{workload_suffix}"))
        target = workload_suffix
    else:
        workload = _by_kind(documents, "Deployment", workload_suffix)
        target = container_name
    return next(container for container in workload["spec"]["template"]["spec"]["containers"] if container["name"] == target)


def _secret_ref(container: dict, env_name: str) -> dict:
    return _env(container)[env_name]["valueFrom"]["secretKeyRef"]


# --- test_helm_credentials_key ---

_FERNET_KEY = re.compile(r"[A-Za-z0-9_-]{43}=")


def _app_secret(documents: list[dict]) -> dict:
    return next(document for document in documents if document.get("kind") == "Secret" and document["metadata"]["name"].endswith("-app"))


def _gateway(documents: list[dict]) -> dict:
    deployment = next(document for document in documents if document.get("kind") == "Deployment" and document["metadata"]["name"].endswith("-gateway"))
    return next(container for container in deployment["spec"]["template"]["spec"]["containers"] if container["name"] == "gateway")


def test_rendered_app_secret_carries_a_valid_fernet_key() -> None:
    key = _app_secret(_render_chart())["stringData"][CREDENTIALS_KEY_ENV_VAR]

    assert _FERNET_KEY.fullmatch(key), "must be urlsafe base64 of 32 bytes"
    assert len(base64.urlsafe_b64decode(key)) == 32
    Fernet(key)
    assert parse_credentials_keys(key) == [key], "the Gateway's own parser must accept the generated key"


def test_each_fresh_render_generates_an_independent_key() -> None:
    """randBytes, not a constant: two installs must not share a key."""
    first = _app_secret(_render_chart())["stringData"][CREDENTIALS_KEY_ENV_VAR]
    second = _app_secret(_render_chart())["stringData"][CREDENTIALS_KEY_ENV_VAR]
    assert first != second


def test_app_secret_template_preserves_the_key_across_upgrades() -> None:
    """``helm template`` never sees ``lookup`` results, so pin the preservation in the source."""
    template = APP_SECRET_TEMPLATE.read_text(encoding="utf-8")
    assert f'index $prev.data "{CREDENTIALS_KEY_ENV_VAR}"' in template, "a regenerated key would make every stored credential unreadable"
    assert f"{CREDENTIALS_KEY_ENV_VAR}: {{{{ $credentialsKey | quote }}}}" in template
    assert 'randBytes 32 | replace "+" "-" | replace "/" "_"' in template


@pytest.mark.parametrize("replicas", ["1", "3"])
def test_gateway_reads_the_key_from_the_app_secret(replicas: str) -> None:
    gateway = _gateway(_render_chart(f"gateway.replicas={replicas}"))
    reference = _env(gateway)[CREDENTIALS_KEY_ENV_VAR]["valueFrom"]["secretKeyRef"]

    assert reference["name"].endswith("-app")
    assert reference["key"] == CREDENTIALS_KEY_ENV_VAR
    # Optional so a user-managed existingAppSecret without the key still boots: the
    # Gateway's own startup gate refuses a multi-instance deployment that stores
    # credentials without it, and leaves the others alone.
    assert reference["optional"] is True


def test_existing_app_secret_is_honored_for_the_key() -> None:
    documents = _render_chart("existingAppSecret=my-app-secret")
    assert not any(document.get("kind") == "Secret" and document["metadata"]["name"].endswith("-app") for document in documents)
    assert _env(_gateway(documents))[CREDENTIALS_KEY_ENV_VAR]["valueFrom"]["secretKeyRef"]["name"] == "my-app-secret"


def test_docs_mention_the_key() -> None:
    for document in (README, NOTES, VALUES):
        assert CREDENTIALS_KEY_ENV_VAR in document.read_text(encoding="utf-8"), document.name
    assert ".credentials_key" in README.read_text(encoding="utf-8"), "the README must say how to keep an auto-generated key"


# --- test_helm_database_secret_precedence ---

RELEASE = "deer-flow"


def _postgres_secrets(documents: list[dict]) -> list[str]:
    return sorted(document["metadata"]["name"] for document in documents if document.get("kind") == "Secret" and document["metadata"]["name"].endswith("-postgres"))


@pytest.mark.parametrize(
    ("settings", "expected"),
    [
        ((), None),
        (("postgresql.existingSecret=custom-pg",), "custom-pg"),
        (("postgresql.external.existingSecret=ext-pg",), "ext-pg"),
        (("postgresql.existingSecret=custom-pg", "postgresql.external.existingSecret=ext-pg"), "ext-pg"),
        # Falsy non-string values are how people spell "not set" in values.yaml.
        # The old if/else-if treated them as unset, and the helper has to keep
        # doing that: `or` returns its last operand even when it is falsy, which
        # would name the Secret `false`. `default ""` yields an empty string
        # instead, so the chart-managed branch is taken.
        (("postgresql.existingSecret=false",), None),
        (("postgresql.external.existingSecret=false", "postgresql.existingSecret=false"), None),
    ],
    ids=[
        "chart-managed",
        "existing-secret",
        "external-secret",
        "external-wins",
        "existing-secret-false",
        "both-secrets-false",
    ],
)
def test_gateway_and_postgres_resolve_the_same_secret(settings: tuple[str, ...], expected: str | None) -> None:
    documents = _render_chart_with_fixed_app_secret(*settings)

    gateway_ref = _secret_ref(_container(documents, "gateway"), "DATABASE_URL")
    postgres_ref = _secret_ref(_container(documents, "postgres"), "POSTGRES_PASSWORD")
    assert gateway_ref["key"] == "database-url"
    assert postgres_ref["key"] == "postgres-password"

    # The point of the shared helper: both consumers name the same Secret, so a
    # source added to one of them cannot silently split the credentials.
    assert gateway_ref["name"] == postgres_ref["name"]

    secrets = _postgres_secrets(documents)
    if expected is None:
        # Chart-managed branch: the chart creates the Secret the consumers name.
        assert secrets == [gateway_ref["name"]]
    else:
        # User-managed branches: the Secret must already exist, so rendering one
        # would shadow the operator's.
        assert gateway_ref["name"] == expected
        assert secrets == []


# --- test_helm_extensions_config_writable ---

RUNTIME_CONFIG_PATH = "/app/backend/.deer-flow/extensions-config/extensions_config.json"


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


# --- test_helm_image_pull_secrets ---

ALL_WORKLOADS = ("provisioner.enabled=true", "postgresql.enabled=true", "redis.enabled=true")


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


# --- test_helm_init_containers ---


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


# --- test_helm_memory_retrieval_index ---

CONFIG_EXAMPLE = REPO_ROOT / "config.example.yaml"


INDEX_PATH = "/var/lib/deerflow/memory-index"


VOLUME_NAME = "memory-index"


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


# --- test_helm_multi_replica_prereqs ---


def _has_kind(documents: list[dict], kind: str) -> bool:
    return any(document.get("kind") == kind for document in documents)


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


# --- test_helm_provisioner_api_key ---

ENV_NAME = "PROVISIONER_API_KEY"


SHELL_DEFAULT = 'export PROVISIONER_API_KEY="${PROVISIONER_API_KEY:-}" && '


def test_default_config_references_the_provisioner_api_key() -> None:
    """The provisioner is on by default, so the gateway must present the key it was given."""
    values = _values()
    assert values["provisioner"]["enabled"] is True
    sandbox = _rendered_config()["sandbox"]
    assert sandbox["provisioner_url"] == "http://provisioner:8002"
    assert sandbox["provisioner_api_key"] == f"${ENV_NAME}", "the harness resolves $VAR from the gateway env"


def test_app_secret_template_preserves_the_provisioner_api_key_across_upgrades() -> None:
    """``helm template`` never sees ``lookup`` results, so pin the preservation in the source."""
    template = APP_SECRET_TEMPLATE.read_text(encoding="utf-8")
    assert f'index $prev.data "{ENV_NAME}"' in template, "a rotated key on upgrade would desynchronize the two Pods mid-rollout"
    assert f"{ENV_NAME}: {{{{ $provisionerKey | quote }}}}" in template


def test_docs_mention_the_provisioner_api_key() -> None:
    assert ENV_NAME in README.read_text(encoding="utf-8")
    assert ENV_NAME in NOTES.read_text(encoding="utf-8")
    assert "provisioner_api_key: $PROVISIONER_API_KEY" in README.read_text(encoding="utf-8"), "the README config example replaces the chart default wholesale"


def test_rendered_app_secret_carries_the_provisioner_api_key() -> None:
    secret = _by_kind(_render_chart(), "Secret", "-app")
    assert secret["stringData"][ENV_NAME]


def test_both_pods_read_the_key_from_the_same_app_secret() -> None:
    documents = _render_chart()
    provisioner = _secret_ref(_container(documents, "-provisioner", "provisioner"), ENV_NAME)
    gateway = _secret_ref(_container(documents, "-gateway", "gateway"), ENV_NAME)
    assert provisioner["name"].endswith("-app")
    assert provisioner["key"] == ENV_NAME
    assert provisioner.get("optional", False) is False, "a provisioner without the key rejects every request"
    assert gateway["name"] == provisioner["name"], "the middleware compares the two values byte for byte"
    assert gateway["key"] == ENV_NAME
    assert gateway.get("optional", False) is False, "the default config references $PROVISIONER_API_KEY and the harness fails on an unset variable"


def test_existing_app_secret_is_honored_by_the_provisioner() -> None:
    documents = _render_chart("existingAppSecret=my-app-secret")
    assert not any(document.get("kind") == "Secret" and document["metadata"]["name"].endswith("-app") for document in documents)
    assert _secret_ref(_container(documents, "-provisioner", "provisioner"), ENV_NAME)["name"] == "my-app-secret"
    assert _secret_ref(_container(documents, "-gateway", "gateway"), ENV_NAME)["name"] == "my-app-secret"


def test_harness_needs_the_variable_set_but_accepts_an_empty_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pins the contract the gateway Deployment relies on when the bundled provisioner is disabled."""
    reference = {"sandbox": {"provisioner_api_key": f"${ENV_NAME}"}}
    monkeypatch.delenv(ENV_NAME, raising=False)
    with pytest.raises(ValueError, match=ENV_NAME):
        AppConfig.resolve_env_variables(reference)
    monkeypatch.setenv(ENV_NAME, "")
    assert AppConfig.resolve_env_variables(reference) == {"sandbox": {"provisioner_api_key": ""}}


@pytest.mark.parametrize("external", [None, "external-provisioner-key"])
def test_shell_default_sets_the_variable_only_when_nothing_else_did(external: str | None) -> None:
    """Pins the start-command prefix from the template source: it must leave an envFrom-supplied key
    alone and turn an unset variable into "" (the only value the harness accepts short of a real key)."""
    prefix = re.search(r"\}\}(export PROVISIONER_API_KEY=.*?&& )\{\{ end \}\}cd backend", GATEWAY_TEMPLATE.read_text(encoding="utf-8"))
    assert prefix is not None and prefix.group(1) == SHELL_DEFAULT
    env = {"PATH": "/usr/bin:/bin"} | ({ENV_NAME: external} if external else {})
    result = subprocess.run(["sh", "-c", prefix.group(1) + f"printenv {ENV_NAME}"], env=env, capture_output=True, text=True)
    assert result.returncode == 0, "the variable must be set in every case"
    assert result.stdout == f"{external or ''}\n"


def test_default_start_command_carries_no_shell_default() -> None:
    """With the bundled provisioner the key is injected and required; the start command stays as it was."""
    gateway = _container(_render_chart(), "-gateway", "gateway")
    assert not " ".join(gateway["args"]).startswith("export")


def test_gateway_key_is_omitted_when_an_external_key_is_supplied() -> None:
    """An explicit env entry wins over envFrom, so rendering it would override the key an operator
    supplies through ``secrets`` for an external provisioner with the generated, unrelated value."""
    documents = _render_chart("provisioner.enabled=false", "secrets.PROVISIONER_API_KEY=external-provisioner-key")
    assert not any(document.get("kind") == "Deployment" and document["metadata"]["name"].endswith("-provisioner") for document in documents)
    gateway = _container(documents, "-gateway", "gateway")
    assert ENV_NAME not in _env(gateway)
    assert any(source["secretRef"]["name"].endswith("-provider") for source in gateway["envFrom"]), "the external key still arrives through the provider Secret"
    assert _by_kind(documents, "Secret", "-provider")["stringData"][ENV_NAME] == "external-provisioner-key"
    assert " ".join(gateway["args"]).startswith(SHELL_DEFAULT), "the shell default keeps the supplied key"


def test_user_managed_provider_secret_without_the_key_still_boots_the_gateway() -> None:
    """``existingSecret`` is a generic provider Secret that often holds only model keys; the chart
    cannot see inside it, so it must neither override a key it carries nor leave the variable unset."""
    gateway = _container(_render_chart("provisioner.enabled=false", "existingSecret=my-provider-secret"), "-gateway", "gateway")
    assert ENV_NAME not in _env(gateway)
    assert [source["secretRef"]["name"] for source in gateway["envFrom"]] == ["my-provider-secret"]
    assert " ".join(gateway["args"]).startswith(SHELL_DEFAULT)


def test_disabled_provisioner_without_any_key_still_boots_the_gateway() -> None:
    """The default config still references $PROVISIONER_API_KEY; an unset variable would stop the gateway
    from starting at all, where the chart used to boot it and only fail sandbox calls at use time."""
    gateway = _container(_render_chart("provisioner.enabled=false"), "-gateway", "gateway")
    assert ENV_NAME not in _env(gateway)
    assert "envFrom" not in gateway
    assert " ".join(gateway["args"]).startswith(SHELL_DEFAULT)


# --- test_helm_provisioner_lark_cli_images ---

INIT_IMAGE = "registry.example.com/deer-flow/lark-cli-init:v1.0.65"


BROKER_IMAGE = "registry.example.com/deer-flow/lark-cli-broker:v1.0.65"


LARK_CLI_ENV_VARS = ("LARK_CLI_INIT_IMAGE", "LARK_CLI_BROKER_IMAGE")


def _provisioner_env(documents: list[dict]) -> dict[str, dict]:
    deployment = next(document for document in documents if document.get("kind") == "Deployment" and document["metadata"]["name"].endswith("-provisioner"))
    container = next(item for item in deployment["spec"]["template"]["spec"]["containers"] if item["name"] == "provisioner")
    return {item["name"]: item for item in container.get("env", [])}


def test_values_declare_both_lark_cli_image_keys_as_empty() -> None:
    provisioner = yaml.safe_load(VALUES.read_text(encoding="utf-8"))["provisioner"]
    assert provisioner["larkCliInitImage"] == ""
    assert provisioner["larkCliBrokerImage"] == ""


def test_default_chart_omits_both_lark_cli_image_env_vars() -> None:
    env = _provisioner_env(_render_chart())
    # The provisioner keys off ``bool(env)``, so the chart must omit the variable
    # rather than inject an empty string: an empty value would still be "off",
    # but only absence keeps the rendered Pod byte-identical to a chart that
    # never knew about lark-cli.
    for name in LARK_CLI_ENV_VARS:
        assert name not in env


@pytest.mark.parametrize(
    ("settings", "expected"),
    [
        ((f"provisioner.larkCliInitImage={INIT_IMAGE}",), {"LARK_CLI_INIT_IMAGE": INIT_IMAGE}),
        ((f"provisioner.larkCliBrokerImage={BROKER_IMAGE}",), {"LARK_CLI_BROKER_IMAGE": BROKER_IMAGE}),
        (
            (
                f"provisioner.larkCliInitImage={INIT_IMAGE}",
                f"provisioner.larkCliBrokerImage={BROKER_IMAGE}",
            ),
            {"LARK_CLI_INIT_IMAGE": INIT_IMAGE, "LARK_CLI_BROKER_IMAGE": BROKER_IMAGE},
        ),
    ],
)
def test_rendered_provisioner_env_carries_lark_cli_images(settings: tuple[str, ...], expected: dict[str, str]) -> None:
    env = _provisioner_env(_render_chart(*settings))
    for name, value in expected.items():
        assert env[name]["value"] == value
    for name in LARK_CLI_ENV_VARS:
        if name not in expected:
            assert name not in env


def test_explicitly_empty_lark_cli_images_stay_omitted() -> None:
    env = _provisioner_env(
        _render_chart("provisioner.larkCliInitImage=", "provisioner.larkCliBrokerImage="),
    )
    for name in LARK_CLI_ENV_VARS:
        assert name not in env


# --- test_helm_redis_existing_secret ---

PASSWORD = "p a$$'\"@:/?#%[]*"


def _run_command(command: list[str], tmp_path: Path, password: str | None) -> list[str]:
    """Execute the rendered shell with argv-recording Redis executables."""
    assert command[:2] == ["sh", "-c"]
    for name in ("redis-server", "redis-cli"):
        executable = tmp_path / name
        executable.write_text(f"#!/bin/sh\nprintf '%s\\0' {name} \"$@\"\n", encoding="utf-8", newline="\n")
        executable.chmod(0o755)
    env = {key: value for key, value in os.environ.items() if key != "REDIS_PASSWORD"}
    if password is not None:
        env["REDIS_PASSWORD"] = password
    # cd accepts native checkout paths in Git Bash, and pwd supplies its PATH form.
    script = 'PATH="$(cd "$1" && pwd):$PATH"; export PATH; ' + command[2]
    result = subprocess.run([require_posix_sh(), "-c", script, "_", tmp_path.as_posix()], env=env, check=True, capture_output=True, text=True, encoding="utf-8")
    return result.stdout.rstrip("\0").split("\0")


@pytest.mark.parametrize("password", ["", PASSWORD])
def test_chart_managed_redis_credentials_match_the_gateway(password: str, tmp_path: Path) -> None:
    documents = _render_chart(f"redis.auth.password={password}")
    redis = _container(documents, "redis")
    gateway_ref = _secret_ref(_container(documents, "gateway"), "DEER_FLOW_STREAM_BRIDGE_REDIS_URL")
    secret = next(document for document in documents if document.get("kind") == "Secret" and document["metadata"]["name"] == gateway_ref["name"])
    url = urlsplit(secret["stringData"][gateway_ref["key"]])
    assert unquote(url.password or "") == password
    assert url.hostname == gateway_ref["name"]
    if password:
        assert secret["stringData"]["redis-password"] == password
        assert _secret_ref(redis, "REDIS_PASSWORD") == {"name": gateway_ref["name"], "key": "redis-password"}
    else:
        assert "redis-password" not in secret["stringData"]
        assert "env" not in redis
    expected_auth = ["--requirepass", password] if password else []
    assert _run_command(redis["command"] + redis["args"], tmp_path, password or None) == ["redis-server", "--appendonly", "yes", *expected_auth]
    for probe in ("readinessProbe", "livenessProbe"):
        expected_auth = ["--no-auth-warning", "-a", password] if password else []
        assert _run_command(redis[probe]["exec"]["command"], tmp_path, password or None) == ["redis-cli", *expected_auth, "ping"]


@pytest.mark.parametrize("password", [None, "", PASSWORD])
@pytest.mark.parametrize("ignored_password", ["", "ignored-values-password"])
def test_bundled_redis_uses_optional_existing_secret_password(password: str | None, ignored_password: str, tmp_path: Path) -> None:
    documents = _render_chart("redis.existingSecret=managed-redis", f"redis.auth.password={ignored_password}")
    redis = _container(documents, "redis")
    assert _secret_ref(redis, "REDIS_PASSWORD") == {"name": "managed-redis", "key": "redis-password", "optional": True}
    assert _secret_ref(_container(documents, "gateway"), "DEER_FLOW_STREAM_BRIDGE_REDIS_URL") == {"name": "managed-redis", "key": "redis-url"}
    assert not any(document.get("kind") == "Secret" and document["metadata"]["name"].endswith("-redis") for document in documents)
    if ignored_password:
        # The stale value must not leak into the manifest: it is the only input
        # here that a template edit could accidentally start rendering.
        assert ignored_password not in yaml.safe_dump(documents)
    expected_auth = ["--requirepass", password] if password else []
    assert _run_command(redis["command"] + redis["args"], tmp_path, password) == ["redis-server", "--appendonly", "yes", *expected_auth]
    for probe in ("readinessProbe", "livenessProbe"):
        argv = _run_command(redis[probe]["exec"]["command"], tmp_path, password)
        assert argv == ["redis-cli", *(["--no-auth-warning", "-a", password] if password else []), "ping"]


@pytest.mark.parametrize(
    "settings",
    [
        ("redis.existingSecret=false",),
        ("redis.external.existingSecret=false", "redis.existingSecret=false"),
    ],
    ids=["existing-secret-false", "both-secrets-false"],
)
def test_falsy_existing_secret_still_uses_the_chart_managed_secret(settings: tuple[str, ...]) -> None:
    # `false` is how people spell "not set" in values.yaml. `or` returns its
    # last operand even when falsy, so it would name the Secret `false` — and
    # nothing creates a Secret by that name, leaving both refs dangling.
    documents = _render_chart(*settings, f"redis.auth.password={PASSWORD}")
    gateway_ref = _secret_ref(_container(documents, "gateway"), "DEER_FLOW_STREAM_BRIDGE_REDIS_URL")
    redis_ref = _secret_ref(_container(documents, "redis"), "REDIS_PASSWORD")
    assert isinstance(gateway_ref["name"], str)
    assert gateway_ref == {"name": redis_ref["name"], "key": "redis-url"}
    assert redis_ref["key"] == "redis-password"
    assert any(document.get("kind") == "Secret" and document["metadata"]["name"] == gateway_ref["name"] for document in documents)


@pytest.mark.parametrize("enabled", ["true", "false"])
def test_external_secret_precedence_is_unchanged(enabled: str) -> None:
    # The existing helper gives external.existingSecret precedence in both modes.
    documents = _render_chart(f"redis.enabled={enabled}", "redis.existingSecret=bundled-secret", "redis.external.existingSecret=external-secret")
    assert _secret_ref(_container(documents, "gateway"), "DEER_FLOW_STREAM_BRIDGE_REDIS_URL") == {"name": "external-secret", "key": "redis-url"}
    if enabled == "true":
        assert _secret_ref(_container(documents, "redis"), "REDIS_PASSWORD") == {"name": "external-secret", "key": "redis-password", "optional": True}
    else:
        assert not any(document.get("kind") == "StatefulSet" and document["metadata"]["name"].endswith("-redis") for document in documents)
    assert not any(document.get("kind") == "Secret" and document["metadata"]["name"].endswith("-redis") for document in documents)


@pytest.mark.parametrize("setting", ["redis.existingSecret=managed-external", "redis.external.redisUrl=redis://:password@managed.example:6380/1"])
def test_external_redis_does_not_deploy_a_bundled_instance(setting: str) -> None:
    documents = _render_chart("redis.enabled=false", setting)
    assert not any(document.get("kind") == "StatefulSet" and document["metadata"]["name"].endswith("-redis") for document in documents)
    ref = _secret_ref(_container(documents, "gateway"), "DEER_FLOW_STREAM_BRIDGE_REDIS_URL")
    if setting.startswith("redis.existingSecret="):
        assert ref == {"name": "managed-external", "key": "redis-url"}
    else:
        secret = next(document for document in documents if document.get("kind") == "Secret" and document["metadata"]["name"] == ref["name"])
        assert secret["stringData"] == {"redis-url": setting.split("=", 1)[1]}
