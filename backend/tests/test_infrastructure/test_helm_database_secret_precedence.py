"""The gateway and the bundled postgres must resolve the same Secret.

`deer-flow.databaseUrlSecret` is read by three consumers — the gateway's
`DATABASE_URL`, the postgres StatefulSet's `POSTGRES_PASSWORD`, and
`postgres-secret.yaml`'s own `metadata.name` — so the precedence chain
(`postgresql.external.existingSecret` → `postgresql.existingSecret` →
`<release>-postgres`) has to exist once. This suite pins that chain and that
every consumer follows it.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CHART = REPO_ROOT / "deploy" / "helm" / "deer-flow"
RELEASE = "deer-flow"


def _render_chart(*settings: str) -> list[dict]:
    helm = shutil.which("helm")
    if helm is None:
        pytest.skip("helm is unavailable")
    # Pin the generated app secrets so a render is reproducible.
    command = [helm, "template", RELEASE, str(CHART), "--set", "existingAppSecret=fixed-app-secret"]
    for setting in settings:
        command.extend(["--set", setting])
    rendered = subprocess.run(command, check=True, capture_output=True, text=True, encoding="utf-8").stdout
    return [document for document in yaml.safe_load_all(rendered) if isinstance(document, dict)]


def _container(documents: list[dict], name: str) -> dict:
    workload = next(document for document in documents if document.get("kind") in {"Deployment", "StatefulSet"} and document["metadata"]["name"].endswith(f"-{name}"))
    return next(container for container in workload["spec"]["template"]["spec"]["containers"] if container["name"] == name)


def _secret_ref(container: dict, env_name: str) -> dict:
    return next(item for item in container["env"] if item["name"] == env_name)["valueFrom"]["secretKeyRef"]


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
    documents = _render_chart(*settings)

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
