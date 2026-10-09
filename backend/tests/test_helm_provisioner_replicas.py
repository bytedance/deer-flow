"""Regression tests for the Helm chart's sandbox-provisioner replica count.

The chart hard-coded ``replicas: 1`` into the provisioner Deployment, gave it
no rollout strategy and no PodDisruptionBudget, and ``values.yaml`` had no
``provisioner.replicas`` key, so a multi-replica gateway deployment still sent
every sandbox create/discover/destroy call through one Pod: while that Pod
restarted or its node drained no sandbox could be created. The provisioner
itself keeps no state between requests -- the labelled sandbox Pods and
Services are the only registry, every handler reads them back from the API
server, and create tolerates the 409 a concurrent creator produces -- so the
chart only had to stop pinning it. These tests pin the values keys, the
Deployment wiring, the PodDisruptionBudget guard (enabled and replicas > 1),
the label agreement between the two templates, the operator notes, and the
source-level statelessness the replica claim rests on.

The ``helm template`` tests skip when helm is not installed; CI's runner has it.
"""

from __future__ import annotations

import ast
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CHART = REPO_ROOT / "deploy" / "helm" / "deer-flow"
VALUES = CHART / "values.yaml"
README = CHART / "README.md"
DEPLOYMENT_TEMPLATE = CHART / "templates" / "provisioner-deployment.yaml"
PDB_TEMPLATE = CHART / "templates" / "provisioner-pdb.yaml"
GATEWAY_PDB_TEMPLATE = CHART / "templates" / "gateway-pdb.yaml"
PROVISIONER_APP = REPO_ROOT / "docker" / "provisioner" / "app.py"
PROVISIONER_README = REPO_ROOT / "docker" / "provisioner" / "README.md"

# A selector block as both templates spell it: the shared selector helper plus
# the component label, so the budget can only ever count provisioner Pods.
SELECTOR_BLOCK = re.compile(r"matchLabels:\n\s+\{\{- include \"deer-flow.selectorLabels\" \. \| nindent 6 \}\}\n\s+app\.kubernetes\.io/component: provisioner\n")

# Methods that mutate a container in place. A module-level container touched by
# one of these from a request handler would be per-Pod state the chart's
# replica claim could not survive.
MUTATING_METHODS = frozenset({"add", "append", "clear", "discard", "extend", "insert", "pop", "popitem", "remove", "setdefault", "update"})
BACKGROUND_WORK = frozenset({"create_task", "ensure_future", "Thread", "Timer", "add_event_handler", "on_event", "repeat_every"})


def _values() -> dict:
    return yaml.safe_load(VALUES.read_text(encoding="utf-8"))


def _render_chart(*settings: str) -> list[dict]:
    helm = shutil.which("helm")
    if helm is None:
        pytest.skip("helm is unavailable")
    command = [helm, "template", "deer-flow", str(CHART)]
    for setting in settings:
        command.extend(["--set", setting])
    rendered = subprocess.run(command, check=True, capture_output=True, text=True).stdout
    return [document for document in yaml.safe_load_all(rendered) if isinstance(document, dict)]


def _find(documents: list[dict], kind: str, name_suffix: str) -> dict | None:
    return next((document for document in documents if document.get("kind") == kind and document["metadata"]["name"].endswith(name_suffix)), None)


def _by_kind(documents: list[dict], kind: str, name_suffix: str) -> dict:
    document = _find(documents, kind, name_suffix)
    assert document is not None, f"no {kind} ending in {name_suffix}"
    return document


def _root_name(node: ast.expr) -> str | None:
    while isinstance(node, (ast.Subscript, ast.Attribute)):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _module_level_mutations(tree: ast.Module) -> list[str]:
    """Return every statement that writes into a module-level container from anywhere in the module."""
    module_names = {target.id for node in tree.body if isinstance(node, ast.Assign) for target in node.targets if isinstance(target, ast.Name)}
    module_names |= {node.target.id for node in tree.body if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)}
    findings: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Subscript) and _root_name(target) in module_names:
                    findings.append(f"line {node.lineno}: item assignment into {_root_name(target)}")
        elif isinstance(node, ast.Delete):
            for target in node.targets:
                if isinstance(target, ast.Subscript) and _root_name(target) in module_names:
                    findings.append(f"line {node.lineno}: del on {_root_name(target)}")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in MUTATING_METHODS:
            if isinstance(node.func.value, ast.Name) and node.func.value.id in module_names:
                findings.append(f"line {node.lineno}: {node.func.value.id}.{node.func.attr}()")
    return findings


def test_default_values_keep_one_provisioner_replica_with_a_rollout_budget() -> None:
    provisioner = _values()["provisioner"]
    assert provisioner["enabled"] is True
    assert provisioner["replicas"] == 1, "the conservative default is unchanged; operators opt into more"
    assert provisioner["strategy"]["type"] == "RollingUpdate"
    assert provisioner["strategy"]["rollingUpdate"]["maxSurge"] == 1
    assert provisioner["strategy"]["rollingUpdate"]["maxUnavailable"] == 0, "surge-then-drain keeps one Pod answering sandbox calls through a rollout"
    assert provisioner["podDisruptionBudget"]["enabled"] is True
    assert provisioner["podDisruptionBudget"]["minAvailable"] == 1


def test_deployment_template_takes_replicas_and_strategy_from_values() -> None:
    template = DEPLOYMENT_TEMPLATE.read_text(encoding="utf-8")
    assert "replicas: {{ .Values.provisioner.replicas }}" in template
    assert re.search(r"^\s*replicas:\s*\d+\s*$", template, flags=re.MULTILINE) is None, "a literal replica count ignores provisioner.replicas"
    assert re.search(r"\{\{- with \.Values\.provisioner\.strategy \}\}\n\s+strategy:\n\s+\{\{- toYaml \. \| nindent 4 \}\}\n\s+\{\{- end \}\}", template), "the rollout strategy must come from values like the gateway's"
    assert SELECTOR_BLOCK.search(template), "the Deployment selector is what the budget has to match"


def test_pdb_template_is_guarded_on_enabled_and_more_than_one_replica() -> None:
    template = PDB_TEMPLATE.read_text(encoding="utf-8")
    guard = re.search(r"\{\{- if and \.Values\.provisioner\.enabled \$pdb\.enabled \(gt \(int \.Values\.provisioner\.replicas\) 1\) \}\}", template)
    assert guard is not None, "render only for an enabled provisioner with an enabled budget and more than one replica"
    assert "{{- $pdb := .Values.provisioner.podDisruptionBudget | default dict -}}" in template
    assert "apiVersion: policy/v1" in template
    assert "kind: PodDisruptionBudget" in template
    assert 'name: {{ include "deer-flow.fullname" . }}-provisioner' in template, "must not collide with the gateway budget"
    assert "minAvailable: {{ $pdb.minAvailable | default 1 | int }}" in template, "a budget of 0 is a disabled budget; disable it instead"
    assert template.count("app.kubernetes.io/component: provisioner") == 2, "once in metadata.labels, once in the selector"
    assert SELECTOR_BLOCK.search(template), "the selector must match the Deployment's Pod labels exactly"


def test_provisioner_pdb_mirrors_the_gateway_pdb() -> None:
    """Same shape as the gateway budget so the two stay reviewable side by side."""
    gateway = GATEWAY_PDB_TEMPLATE.read_text(encoding="utf-8").replace("gateway", "provisioner")
    provisioner = PDB_TEMPLATE.read_text(encoding="utf-8")
    for line in ("apiVersion: policy/v1", "kind: PodDisruptionBudget", 'name: {{ include "deer-flow.fullname" . }}-provisioner', "minAvailable: {{ $pdb.minAvailable | default 1 | int }}"):
        assert line in gateway and line in provisioner, line


def test_operator_notes_document_the_provisioner_replicas() -> None:
    values = VALUES.read_text(encoding="utf-8")
    readme = README.read_text(encoding="utf-8")
    provisioner_readme = PROVISIONER_README.read_text(encoding="utf-8")
    for needle in ("provisioner.replicas", "409", "PodDisruptionBudget"):
        assert needle in readme, needle
    assert "409" in values, "the comment explains why a concurrent create on another replica is harmless"
    assert "replica" in provisioner_readme, "the provisioner's own README must say it can run several replicas"
    assert "app=deer-flow-sandbox" in provisioner_readme or "labels" in provisioner_readme, "and that the labelled K8s objects are the only registry"
    assert "that one provisioner" not in readme, "the health note must not promise a single provisioner Pod"


def test_provisioner_keeps_no_state_between_requests() -> None:
    """The replica claim in values.yaml rests on this; a registry or reaper added here must re-open it."""
    source = PROVISIONER_APP.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(PROVISIONER_APP))
    globals_declared = {name for node in ast.walk(tree) if isinstance(node, ast.Global) for name in node.names}
    assert globals_declared == {"core_v1"}, f"only the K8s client is process-global, found {sorted(globals_declared)}"
    assert _module_level_mutations(tree) == [], "a module-level container written at request time is per-Pod state"
    background = sorted({node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute) and node.attr in BACKGROUND_WORK})
    assert background == [], f"a background loop would run once per replica: {background}"
    assert source.count("exc.status != 409") >= 2, "Pod and Service create must both tolerate AlreadyExists from a concurrent creator"
    assert 'label_selector="app=deer-flow-sandbox"' in source, "the label is the registry every replica lists from"


@pytest.mark.parametrize("replicas", [1, 2, 3])
def test_rendered_provisioner_follows_the_replica_count(replicas: int) -> None:
    values = _values()["provisioner"]
    documents = _render_chart(f"provisioner.replicas={replicas}")
    deployment = _by_kind(documents, "Deployment", "-provisioner")
    assert deployment["spec"]["replicas"] == replicas
    assert deployment["spec"]["strategy"] == values["strategy"]

    pdb = _find(documents, "PodDisruptionBudget", "-provisioner")
    assert (pdb is not None) is (replicas > 1), "a budget of 1 on a single replica would block every node drain"
    assert _find(documents, "PodDisruptionBudget", "-gateway") is None, "the gateway stays at one replica in this render"
    if pdb is not None:
        assert pdb["spec"]["minAvailable"] == values["podDisruptionBudget"]["minAvailable"]
        assert pdb["spec"]["selector"]["matchLabels"] == deployment["spec"]["selector"]["matchLabels"]
        assert pdb["spec"]["selector"]["matchLabels"] == deployment["spec"]["template"]["metadata"]["labels"]
        assert pdb["metadata"]["labels"]["app.kubernetes.io/component"] == "provisioner"
        assert pdb["metadata"]["namespace"] == deployment["metadata"]["namespace"]


def test_rendered_default_matches_the_previous_single_replica_deployment() -> None:
    documents = _render_chart()
    deployment = _by_kind(documents, "Deployment", "-provisioner")
    assert deployment["spec"]["replicas"] == 1
    assert deployment["spec"]["strategy"] == {"type": "RollingUpdate", "rollingUpdate": {"maxSurge": 1, "maxUnavailable": 0}}
    assert not any(document.get("kind") == "PodDisruptionBudget" for document in documents)


def test_gateway_and_provisioner_budgets_render_side_by_side() -> None:
    documents = _render_chart("gateway.replicas=2", "provisioner.replicas=2")
    names = sorted(document["metadata"]["name"] for document in documents if document.get("kind") == "PodDisruptionBudget")
    assert len(names) == 2 and names[0].endswith("-gateway") and names[1].endswith("-provisioner")


def test_disabled_provisioner_renders_neither_deployment_nor_budget() -> None:
    documents = _render_chart("provisioner.enabled=false", "provisioner.replicas=2")
    assert _find(documents, "Deployment", "-provisioner") is None
    assert _find(documents, "PodDisruptionBudget", "-provisioner") is None


def test_provisioner_budget_can_be_disabled_independently() -> None:
    documents = _render_chart("provisioner.replicas=2", "provisioner.podDisruptionBudget.enabled=false")
    assert _by_kind(documents, "Deployment", "-provisioner")["spec"]["replicas"] == 2
    assert _find(documents, "PodDisruptionBudget", "-provisioner") is None
