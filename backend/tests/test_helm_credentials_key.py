"""The Helm chart generates and injects ``DEER_FLOW_CREDENTIALS_KEY``.

Every gateway Pod must encrypt and decrypt stored credentials with one key, so
the chart generates a Fernet key into the app Secret once, preserves it across
upgrades through ``lookup`` like ``AUTH_JWT_SECRET``, and injects it into the
gateway. Sprig's ``randBytes`` emits standard base64; Fernet keys use the
urlsafe alphabet, so the template translates ``+``/``/`` to ``-``/``_``.

The ``helm template`` tests skip when helm is not installed; CI's runner has it.
"""

from __future__ import annotations

import base64
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from cryptography.fernet import Fernet

from deerflow.config.credentials_key import CREDENTIALS_KEY_ENV_VAR, parse_credentials_keys

REPO_ROOT = Path(__file__).resolve().parents[2]
CHART = REPO_ROOT / "deploy" / "helm" / "deer-flow"
APP_SECRET_TEMPLATE = CHART / "templates" / "secret-app.yaml"
README = CHART / "README.md"
NOTES = CHART / "templates" / "NOTES.txt"
VALUES = CHART / "values.yaml"

_FERNET_KEY = re.compile(r"[A-Za-z0-9_-]{43}=")


def _render_chart(*settings: str) -> list[dict]:
    helm = shutil.which("helm")
    if helm is None:
        pytest.skip("helm is unavailable")
    command = [helm, "template", "deer-flow", str(CHART)]
    for setting in settings:
        command.extend(["--set", setting])
    rendered = subprocess.run(command, check=True, capture_output=True, text=True).stdout
    return [document for document in yaml.safe_load_all(rendered) if isinstance(document, dict)]


def _app_secret(documents: list[dict]) -> dict:
    return next(document for document in documents if document.get("kind") == "Secret" and document["metadata"]["name"].endswith("-app"))


def _gateway(documents: list[dict]) -> dict:
    deployment = next(document for document in documents if document.get("kind") == "Deployment" and document["metadata"]["name"].endswith("-gateway"))
    return next(container for container in deployment["spec"]["template"]["spec"]["containers"] if container["name"] == "gateway")


def _env(container: dict) -> dict[str, dict]:
    return {item["name"]: item for item in container["env"]}


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
