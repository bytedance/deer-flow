"""Regression tests for the Helm chart's provisioner API key.

The chart enables the sandbox provisioner by default and points
``config.sandbox.provisioner_url`` at it, but nothing rendered
``PROVISIONER_API_KEY``: the provisioner Deployment had no such env, the app
Secret no such key, and the embedded config no ``provisioner_api_key``. Since
the provisioner started requiring the key (#4116), its ``verify_api_key``
middleware answers 401 to every ``/api/*`` request while the key is empty or
mismatched, so a default install could not create a single sandbox.
docker-compose was unaffected because it reads the key from ``.env``.

These tests pin the generated, upgrade-preserved key in the app Secret, its
injection into both the gateway and provisioner Pods from that one Secret, the
``existingAppSecret`` wiring, and the ``$PROVISIONER_API_KEY`` reference in the
default config.

The ``helm template`` tests skip when helm is not installed; CI's runner has it.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CHART = REPO_ROOT / "deploy" / "helm" / "deer-flow"
VALUES = CHART / "values.yaml"
APP_SECRET_TEMPLATE = CHART / "templates" / "secret-app.yaml"
README = CHART / "README.md"
NOTES = CHART / "templates" / "NOTES.txt"

ENV_NAME = "PROVISIONER_API_KEY"


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


def _container(documents: list[dict], deployment_suffix: str, container_name: str) -> dict:
    containers = _by_kind(documents, "Deployment", deployment_suffix)["spec"]["template"]["spec"]["containers"]
    return next(container for container in containers if container["name"] == container_name)


def _env(container: dict) -> dict[str, dict]:
    return {item["name"]: item for item in container["env"]}


def _secret_ref(container: dict, env_name: str) -> dict:
    return _env(container)[env_name]["valueFrom"]["secretKeyRef"]


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


def test_gateway_key_is_omitted_while_the_bundled_provisioner_is_disabled() -> None:
    """An explicit env entry wins over envFrom, so rendering it would override the key an operator
    supplies through ``secrets`` for an external provisioner with the generated, unrelated value."""
    documents = _render_chart("provisioner.enabled=false", "secrets.PROVISIONER_API_KEY=external-provisioner-key")
    assert not any(document.get("kind") == "Deployment" and document["metadata"]["name"].endswith("-provisioner") for document in documents)
    gateway = _container(documents, "-gateway", "gateway")
    assert ENV_NAME not in _env(gateway)
    assert any(source["secretRef"]["name"].endswith("-provider") for source in gateway["envFrom"]), "the external key still arrives through the provider Secret"
    assert _by_kind(documents, "Secret", "-provider")["stringData"][ENV_NAME] == "external-provisioner-key"
