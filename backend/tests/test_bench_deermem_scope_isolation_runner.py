from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.benchmark.deermem_scope_isolation.manifest import load_manifest
from scripts.benchmark.deermem_scope_isolation.report import compute_metrics, load_identity_rows, load_semantic_rows
from scripts.benchmark.deermem_scope_isolation.runner import run_offline

BACKEND_ROOT = Path(__file__).parents[1]
EVAL_ROOT = BACKEND_ROOT / "scripts" / "benchmark" / "deermem_scope_isolation"
MANIFEST_PATH = EVAL_ROOT / "manifests" / "scope-isolation-v1.json"
PROMPT_PATH = BACKEND_ROOT / "packages" / "harness" / "deerflow" / "agents" / "memory" / "backends" / "deermem" / "deermem" / "core" / "prompts" / "memory_update.chat.yaml"


def test_offline_run_exercises_semantic_gate_and_identity_buckets(tmp_path: Path) -> None:
    manifest = load_manifest(MANIFEST_PATH)
    output_dir = tmp_path / "run"

    report = run_offline(
        manifest,
        output_dir=output_dir,
        manifest_path=MANIFEST_PATH,
        prompt_path=PROMPT_PATH,
        backend_root=BACKEND_ROOT,
    )

    assert report.semantic_cases == 6
    assert report.identity_observations > 0
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["metrics"]["durable_retention_rate"]["rate"] == 1.0
    assert summary["metrics"]["unsafe_persistence_rate"]["rate"] == 0.0
    assert summary["metrics"]["cross_agent_contamination_rate"]["rate"] == 0.0
    assert summary["metrics"]["cross_user_contamination_rate"]["rate"] == 0.0
    assert summary["metrics"]["atomic_correction_success_rate"]["rate"] == 1.0
    assert summary["metrics"]["identity_retention_rate"]["rate"] == 1.0

    semantic_rows = load_semantic_rows(output_dir)
    correction = next(row for row in semantic_rows if row["scenario"] == "user_correction")
    assert correction["correction_checks"] == [
        {
            "new_canary": "DFMEM_NEW_EDITOR_744",
            "new_observed": True,
            "old_canary": "DFMEM_OLD_EDITOR_311",
            "old_observed": False,
            "passed": True,
        }
    ]

    public_rows = (output_dir / "semantic.rows.jsonl").read_text(encoding="utf-8")
    assert "force-push this branch" not in public_rows
    assert "Current repository" not in public_rows

    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        run_offline(
            manifest,
            output_dir=output_dir,
            manifest_path=MANIFEST_PATH,
            prompt_path=PROMPT_PATH,
            backend_root=BACKEND_ROOT,
        )


def test_report_is_recomputable_and_zero_denominators_are_null(tmp_path: Path) -> None:
    manifest = load_manifest(MANIFEST_PATH)
    output_dir = tmp_path / "run"
    run_offline(
        manifest,
        output_dir=output_dir,
        manifest_path=MANIFEST_PATH,
        prompt_path=PROMPT_PATH,
        backend_root=BACKEND_ROOT,
    )

    recomputed = compute_metrics(load_semantic_rows(output_dir), load_identity_rows(output_dir))
    committed = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))["metrics"]
    assert recomputed == committed
    empty = compute_metrics([], [])
    assert all(metric["rate"] is None for metric in empty.values())
