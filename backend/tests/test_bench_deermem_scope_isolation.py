from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.benchmark.deermem_scope_isolation.contract import load_protocol
from scripts.benchmark.deermem_scope_isolation.grading import grade_routing_row, grade_semantic_rows
from scripts.benchmark.deermem_scope_isolation.report import RowIntegrityError, build_report, collect_rows
from scripts.benchmark.deermem_scope_isolation.runner import ROOT, ensure_run_identity, run

MANIFEST = ROOT / "manifest.json"


def test_contract_is_versioned_and_canaries_are_unique() -> None:
    protocol = load_protocol(MANIFEST)

    assert protocol.protocol_id == "deermem-scope-isolation-v1"
    assert len(protocol.semantic_cases) == 6
    canaries = [canary for case in protocol.semantic_cases for canary in (*case.expected_persisted_canaries, *case.expected_rejected_canaries, *case.expected_removed_canaries)] + [protocol.routing_case.canary]
    assert len(canaries) == len(set(canaries))


def test_contract_rejects_duplicate_canary(tmp_path: Path) -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["semantic_cases"][1]["expected_rejected_canaries"] = manifest["semantic_cases"][0]["expected_persisted_canaries"]
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="canary"):
        load_protocol(path)


def test_offline_runner_executes_production_scope_and_routing_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    protocol = load_protocol(MANIFEST)
    monkeypatch.setattr(
        "scripts.benchmark.deermem_scope_isolation.runner.build_llm",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("offline mode must not build a provider model")),
    )

    result = run(protocol, manifest_path=MANIFEST, output_dir=tmp_path, mode="offline")
    marker = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    semantic, routing = collect_rows(protocol, tmp_path, marker)

    assert result.executed == 7
    assert all(row["update_succeeded"] for row in semantic)
    assert grade_semantic_rows(semantic)["durable_retention_rate"] == 1.0
    assert grade_semantic_rows(semantic)["unsafe_persistence_rate"] == 0.0
    assert grade_semantic_rows(semantic)["atomic_correction_success_rate"] == 1.0
    assert routing is not None
    assert routing["checked_scopes"]["default"]["agent_name"] == "__default__"
    assert grade_routing_row(routing)["cross_agent_contamination_rate"] == 0.0
    assert grade_routing_row(routing)["cross_user_contamination_rate"] == 0.0
    assert grade_routing_row(routing)["custom_agent_bootstrap_success"] is True


def test_resume_reuses_protocol_bound_rows_and_rejects_changed_manifest(tmp_path: Path) -> None:
    protocol = load_protocol(MANIFEST)
    first = run(protocol, manifest_path=MANIFEST, output_dir=tmp_path / "run", mode="offline")
    second = run(protocol, manifest_path=MANIFEST, output_dir=tmp_path / "run", mode="offline")

    assert first.executed == 7
    assert second.executed == 0
    assert second.reused == 7

    changed = tmp_path / "changed.json"
    raw = json.loads(MANIFEST.read_text(encoding="utf-8"))
    raw["protocol_id"] = "changed"
    changed.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="different protocol"):
        ensure_run_identity(tmp_path / "run", mode="offline", protocol=load_protocol(changed), manifest_path=changed, settings=None)


def test_report_recomputes_metrics_and_rejects_tampered_outcome(tmp_path: Path) -> None:
    protocol = load_protocol(MANIFEST)
    run(protocol, manifest_path=MANIFEST, output_dir=tmp_path, mode="offline")
    marker = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))

    report = build_report(protocol, tmp_path, marker)

    assert report["semantic_model_quality"]["durable_retention_rate"] == 1.0
    assert report["deterministic_identity_routing"]["cross_agent_contamination_rate"] == 0.0

    path = tmp_path / "rows" / "durable-preference.json"
    row = json.loads(path.read_text(encoding="utf-8"))
    row["expected_persisted_canaries"] = []
    path.write_text(json.dumps(row), encoding="utf-8")
    with pytest.raises(RowIntegrityError, match="result-integrity"):
        collect_rows(protocol, tmp_path, marker)
