"""Paired metadata maintenance on real databases; receipts here are synthetic.

This tests the consumer's gate, not actual cloud draining or backup restoration.
M10 must produce and verify those operator artifacts before deployment.
"""

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from test_workspace_executor_migration import executor_engine, native_engine  # noqa: F401


def _private_json(path, value):
    encoded = json.dumps(value, sort_keys=True).encode()
    path.write_bytes(encoded)
    path.chmod(0o600)
    return hashlib.sha256(encoded).hexdigest()


def test_paired_cli_requires_evidence_and_both_phase_receipts(executor_engine, native_engine, tmp_path):  # noqa: F811
    from ecs_executor.schema import upgrade_schema

    path = Path(__file__).resolve().parents[2] / "scripts" / "tenant_migration.py"
    assert path.is_file(), "controlled tenant migration CLI is not implemented"
    spec = importlib.util.spec_from_file_location("tenant_migration_cli", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    upgrade_schema(executor_engine)
    directory = tmp_path / "receipts"
    directory.mkdir(mode=0o700)
    engines = (native_engine, executor_engine)
    target = module.target_fingerprint(*engines)
    generation = str(uuid4())
    environment = dict(os.environ, DEERFLOW_TENANT_NATIVE_URL=native_engine.url.render_as_string(hide_password=False), DEERFLOW_TENANT_EXECUTOR_URL=executor_engine.url.render_as_string(hide_password=False))
    command = [sys.executable, str(path), "plan", "--phase", "native", "--receipt-directory", str(directory)]
    completed = subprocess.run(command, env=environment, capture_output=True, text=True, encoding="utf-8", errors="strict", timeout=30)
    assert completed.returncode == 0 and completed.stderr == ""
    assert json.loads(completed.stdout) == {"operation": "plan", "phase": "native", "completed": True, "ready_for_activation": False}
    assert len(list(directory.glob("plan-*.json"))) == 1
    result = module.run_phase(*engines, directory, operation="plan", phase="native")
    assert len(result["users"]) == 1 and len(result["resources"]) == 2
    with pytest.raises(ValueError, match="maintenance"):
        module.run_phase(*engines, directory, operation="apply", phase="native")
    with native_engine.connect() as conn:
        assert conn.execute(sa.text("SELECT COUNT(*) FROM workspaces")).scalar_one() == 0
    identity = {"generation": generation, "target_sha256": target}
    evidence = {}
    for name, details in {
        "drain": {"admission_closed": True, "writers_stopped": True, "physical_stopped": True},
        "backup": {"restore_verified": True, "native_sha256": "1" * 64, "executor_sha256": "2" * 64, "nas_manifest_sha256": "3" * 64},
    }.items():
        filename = name + ".json"
        digest = _private_json(directory / filename, {"format": "deerflow.tenant." + name + ".v1", **identity, **details})
        evidence[name] = {"file": filename, "sha256": digest}
    manifest = {"format": "deerflow.tenant.maintenance.v1", **identity, "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(), "evidence": evidence}
    _private_json(directory / "maintenance.json", manifest)
    with pytest.raises(ValueError, match="native"):
        module.run_phase(*engines, directory, operation="apply", phase="executor")
    native = module.run_phase(*engines, directory, operation="apply", phase="native")
    assert native["result"]["created_workspaces"] == 1
    assert (directory / "native.json").stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError, match="executor"):
        module.run_phase(*engines, directory, operation="verify", phase="all")
    executor = module.run_phase(*engines, directory, operation="apply", phase="executor")
    assert executor["result"]["assigned_jobs"] == 0 and executor["result"]["assigned_affinities"] == 1
    assert module.run_phase(*engines, directory, operation="apply", phase="native") == native
    assert module.run_phase(*engines, directory, operation="apply", phase="executor") == executor
    verified = module.run_phase(*engines, directory, operation="verify", phase="all")
    assert verified["metadata_verified"] is True and verified["ready_for_activation"] is False
    with executor_engine.connect() as conn:
        assert conn.execute(sa.text("SELECT version,state,workspace_id FROM ecs_execution_jobs WHERE id='unknown'")).one() == (7, "uncertain", None)
    (directory / "drain.json").write_text("{}")
    with pytest.raises(ValueError, match="evidence"):
        module.run_phase(*engines, directory, operation="apply", phase="native")
