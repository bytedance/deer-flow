"""Keep Gateway/provisioner extra-mount allowlists in lockstep."""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _literal_assignment(path: Path, name: str):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found in {path}")


def test_gateway_and_provisioner_extra_mount_contracts_match() -> None:
    gateway_path = REPO_ROOT / "backend/packages/harness/deerflow/community/aio_sandbox/remote_backend.py"
    provisioner_path = REPO_ROOT / "docker/provisioner/app.py"

    gateway_paths = _literal_assignment(gateway_path, "_PROVISIONER_EXTRA_MOUNT_PATHS")
    provisioner_paths = _literal_assignment(provisioner_path, "ALLOWED_EXTRA_MOUNT_PATHS")

    assert gateway_paths == provisioner_paths
    assert "/mnt/integrations/lark-cli/runtime" in gateway_paths
    assert _literal_assignment(provisioner_path, "MAX_EXTRA_MOUNTS") == 9
