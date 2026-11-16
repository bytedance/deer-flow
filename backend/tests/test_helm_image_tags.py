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


def _images(*settings: str) -> dict[str, str]:
    helm = shutil.which("helm")
    if helm is None:
        pytest.skip("helm is unavailable")
    command = [helm, "template", "deer-flow", str(CHART), "--set", "image.registry=registry.example.com/team", "--set", "image.tag=v1.0.0"]
    for setting in settings:
        command.extend(["--set", setting])
    rendered = subprocess.run(command, check=True, capture_output=True, text=True, encoding="utf-8").stdout
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
