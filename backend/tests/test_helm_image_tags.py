"""Each DeerFlow image can take its own tag; ``image.tag`` stays the default.

All three images shared ``image.tag``, so a backend rebuilt on top of a release
(extra packages, a local fix) forced a matching tag for the frontend and
provisioner images, which then had to be re-tagged copies of the release.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CHART = REPO_ROOT / "deploy" / "helm" / "deer-flow"


def _render(*settings: str, set_flag: str = "--set") -> subprocess.CompletedProcess[str]:
    helm = shutil.which("helm")
    if helm is None:
        pytest.skip("helm is unavailable")
    command = [helm, "template", "deer-flow", str(CHART), "--set", "image.registry=registry.example.com/team", "--set", "image.tag=v1.0.0"]
    for setting in settings:
        command.extend([set_flag, setting])
    return subprocess.run(command, check=False, capture_output=True, text=True, encoding="utf-8")


def _images(*settings: str, set_flag: str = "--set") -> dict[str, str]:
    result = _render(*settings, set_flag=set_flag)
    assert result.returncode == 0, result.stderr
    rendered = result.stdout
    deployments = [document for document in yaml.safe_load_all(rendered) if isinstance(document, dict) and document.get("kind") == "Deployment"]
    images = {}
    for deployment in deployments:
        for name in ("gateway", "frontend", "provisioner"):
            if deployment["metadata"]["name"].endswith(f"-{name}"):
                images[name] = deployment["spec"]["template"]["spec"]["containers"][0]["image"]
    assert set(images) == {"gateway", "frontend", "provisioner"}
    return images


def test_images_share_image_tag_by_default() -> None:
    assert _images() == {
        "gateway": "registry.example.com/team/deer-flow-backend:v1.0.0",
        "frontend": "registry.example.com/team/deer-flow-frontend:v1.0.0",
        "provisioner": "registry.example.com/team/deer-flow-provisioner:v1.0.0",
    }


@pytest.mark.parametrize(("name", "image"), [("gateway", "deer-flow-backend"), ("frontend", "deer-flow-frontend"), ("provisioner", "deer-flow-provisioner")])
def test_per_image_tag_overrides_only_that_image(name: str, image: str) -> None:
    images = _images(f"image.{name}Tag=v1.0.0-custom.1")
    assert images.pop(name) == f"registry.example.com/team/{image}:v1.0.0-custom.1"
    assert all(ref.endswith(":v1.0.0") for ref in images.values())


@pytest.mark.parametrize("name", ["gateway", "frontend", "provisioner"])
@pytest.mark.parametrize("value", ["20261118", "0"])
def test_numeric_per_image_tag_fails_the_render(name: str, value: str) -> None:
    # --set turns a digit string into an integer: printf would render
    # `%!s(int64=20261118)`, and `default` would silently drop 0.
    result = _render(f"image.{name}Tag={value}")
    assert result.returncode != 0
    assert f"image.{name}Tag must be a string" in result.stderr
    assert "--set-string" in result.stderr


def _render_as_subchart(tmp_path: Path, tag: str) -> subprocess.CompletedProcess[str]:
    helm = shutil.which("helm")
    if helm is None:
        pytest.skip("helm is unavailable")
    parent = tmp_path / "parent"
    shutil.copytree(CHART, parent / "charts" / "deer-flow")
    (parent / "Chart.yaml").write_text("apiVersion: v2\nname: parent\nversion: 0.1.0\n", encoding="utf-8")
    (parent / "values.yaml").write_text(f"deer-flow:\n  image:\n    gatewayTag: {tag}\n", encoding="utf-8")
    return subprocess.run([helm, "template", "parent", str(parent)], check=False, capture_output=True, text=True, encoding="utf-8")


@pytest.mark.parametrize("value", ["7.0", "0123"])
def test_numeric_per_image_tag_from_parent_chart_fails_the_render(tmp_path: Path, value: str) -> None:
    # Helm 3.18.0 passes an unquoted number from a parent chart's values to the
    # subchart as a json.Number (kind "string"): 7.0 and 0123 rendered as 7 and 83.
    result = _render_as_subchart(tmp_path, value)
    assert result.returncode != 0
    assert "image.gatewayTag must be a string" in result.stderr


def test_quoted_per_image_tag_from_parent_chart_renders(tmp_path: Path) -> None:
    result = _render_as_subchart(tmp_path, '"0123"')
    assert result.returncode == 0, result.stderr
    assert "deer-flow-backend:0123" in result.stdout


def test_numeric_per_image_tag_as_string_renders() -> None:
    images = _images("image.gatewayTag=20261118", set_flag="--set-string")
    assert images["gateway"] == "registry.example.com/team/deer-flow-backend:20261118"
    assert images["frontend"].endswith(":v1.0.0")
