"""Regression for AIO selecting an execution-role container namespace."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_generate_rejects_role_namespace_before_private_writes(tmp_path):
    script = Path(__file__).resolve().parents[2] / "scripts/ecs_native.py"
    spec = importlib.util.spec_from_file_location("native_ops_prefix_guard", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    private_dir = tmp_path / "not-created"
    args = SimpleNamespace(
        project="owned-fixture",
        sandbox_prefix="owned-fixture-worker",
        private_dir=str(private_dir),
    )
    with pytest.raises(ValueError, match="must not select role containers"):
        module.generate(args)
    assert not private_dir.exists()
