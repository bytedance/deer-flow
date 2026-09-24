"""Regression tests for the Helm provisioner lark-cli sandbox runtime images.

The provisioner reads ``LARK_CLI_INIT_IMAGE`` (Pattern A: init container +
shared ``emptyDir``) and ``LARK_CLI_BROKER_IMAGE`` (Pattern B: shim + credential
broker sidecar) and treats either as off when it is empty —
see ``docker/provisioner/app.py``. ``docker/docker-compose.yaml`` and the root
``README.md`` both expose the two variables, but the chart never plumbed them
into the provisioner Pod, so a Helm operator following the README had no value
to set and silently got a sandbox without a ``lark-cli`` runtime.
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

INIT_IMAGE = "registry.example.com/deer-flow/lark-cli-init:v1.0.65"
BROKER_IMAGE = "registry.example.com/deer-flow/lark-cli-broker:v1.0.65"

LARK_CLI_ENV_VARS = ("LARK_CLI_INIT_IMAGE", "LARK_CLI_BROKER_IMAGE")


def _render_chart(*settings: str) -> list[dict]:
    helm = shutil.which("helm")
    if helm is None:
        pytest.skip("helm is unavailable")
    command = [helm, "template", "deer-flow", str(CHART)]
    for setting in settings:
        command.extend(["--set", setting])
    rendered = subprocess.run(command, check=True, capture_output=True, text=True).stdout
    return [document for document in yaml.safe_load_all(rendered) if isinstance(document, dict)]


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
