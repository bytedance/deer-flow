"""``strategy.type: Recreate`` must render without ``rollingUpdate``.

The gateway and provisioner default to ``RollingUpdate`` with a
``rollingUpdate`` block. Kubernetes rejects ``rollingUpdate`` next to
``type: Recreate``, and a parent chart that uses this chart as a dependency
cannot null the default block (Helm keeps subchart defaults), so a single
gateway on a ReadWriteOnce home PVC could not switch to ``Recreate``.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CHART = REPO_ROOT / "deploy" / "helm" / "deer-flow"


def _strategies(chart: Path, *settings: str) -> dict[str, dict]:
    helm = shutil.which("helm")
    if helm is None:
        pytest.skip("helm is unavailable")
    command = [helm, "template", "deer-flow", str(chart)]
    for setting in settings:
        command.extend(["--set", setting])
    rendered = subprocess.run(command, check=True, capture_output=True, text=True, encoding="utf-8").stdout
    deployments = [document for document in yaml.safe_load_all(rendered) if isinstance(document, dict) and document.get("kind") == "Deployment"]
    return {name: d["spec"].get("strategy") for d in deployments for name in ("gateway", "provisioner") if d["metadata"]["name"].endswith(f"-{name}")}


def test_default_strategy_is_surge_then_drain() -> None:
    strategies = _strategies(CHART)
    assert set(strategies) == {"gateway", "provisioner"}
    for strategy in strategies.values():
        assert strategy == {"type": "RollingUpdate", "rollingUpdate": {"maxSurge": 1, "maxUnavailable": 0}}


@pytest.mark.parametrize("component", ["gateway", "provisioner"])
def test_recreate_drops_rolling_update(component: str) -> None:
    strategies = _strategies(CHART, f"{component}.strategy.type=Recreate")
    assert strategies[component] == {"type": "Recreate"}


def test_recreate_from_a_parent_chart(tmp_path: Path) -> None:
    parent = tmp_path / "parent"
    shutil.copytree(CHART, parent / "charts" / "deer-flow")
    (parent / "Chart.yaml").write_text('apiVersion: v2\nname: parent\nversion: 0.0.1\ndependencies:\n  - name: deer-flow\n    version: "*"\n')
    (parent / "values.yaml").write_text("deer-flow:\n  gateway:\n    strategy:\n      type: Recreate\n      rollingUpdate: null\n")
    assert _strategies(parent)["gateway"] == {"type": "Recreate"}
