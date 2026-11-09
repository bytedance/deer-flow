from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.benchmark.context_memory_comparison.cli import main
from scripts.benchmark.context_memory_comparison.contract import load_protocol
from scripts.benchmark.context_memory_comparison.grading import (
    grade_all_rows,
    grade_scope_isolation_rows,
    grade_token_overhead_rows,
    grade_turn_invalidation_rows,
)
from scripts.benchmark.context_memory_comparison.report import (
    RowIntegrityError,
    collect_rows,
    write_report,
)
from scripts.benchmark.context_memory_comparison.runner import (
    ROOT,
    ensure_run_identity,
    run,
)

MANIFEST = ROOT / "manifest.json"


def test_contract_is_versioned_and_canaries_are_unique() -> None:
    protocol = load_protocol(MANIFEST)

    assert protocol.schema_version == 1
    assert protocol.protocol_id == "deerflow-context-memory-comparison-v1"
    assert len(protocol.scope_isolation_cases) == 2
    assert len(protocol.turn_invalidation_cases) == 2
    assert len(protocol.token_overhead_cases) == 3

    seen_canaries: list[str] = []
    for case in protocol.scope_isolation_cases:
        seen_canaries.extend(case.expected_rejected_canaries)
        seen_canaries.extend(set(case.expected_thread_a_canaries) | set(case.expected_thread_b_canaries))
    for case in protocol.turn_invalidation_cases:
        seen_canaries.extend(set(case.expected_turn_1_canaries) | set(case.expected_turn_2_present_canaries) | set(case.expected_turn_2_absent_canaries))

    assert len(seen_canaries) == len(set(seen_canaries))


def test_contract_rejects_duplicate_canary(tmp_path: Path) -> None:
    raw = json.loads(MANIFEST.read_text(encoding="utf-8"))
    reused_canary = raw["scope_isolation_cases"][0]["expected_rejected_canaries"][0]
    raw["turn_invalidation_cases"][0]["expected_turn_1_canaries"].append(reused_canary)

    bad_manifest = tmp_path / "bad_manifest.json"
    bad_manifest.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError, match="is reused across cases"):
        load_protocol(bad_manifest)


def test_offline_runner_executes_all_checks_successfully(tmp_path: Path) -> None:
    protocol = load_protocol(MANIFEST)
    result = run(protocol, manifest_path=MANIFEST, output_dir=tmp_path, mode="offline")

    assert result.executed == 7
    assert result.reused == 0

    marker = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    scope_rows, inv_rows, tok_rows = collect_rows(protocol, tmp_path, marker)

    assert len(scope_rows) == 2
    assert len(inv_rows) == 2
    assert len(tok_rows) == 3

    # Check 1: Scope Isolation
    scope_grade = grade_scope_isolation_rows(scope_rows)
    assert scope_grade["scope_isolation_passed"] is True
    assert scope_grade["cross_thread_crosstalk_rate"] == 0.0
    assert scope_grade["project_to_global_contamination_rate"] == 0.0
    assert scope_grade["thread_a_retention_rate"] == 1.0
    assert scope_grade["thread_b_retention_rate"] == 1.0

    # Check 2: Turn Invalidation
    inv_grade = grade_turn_invalidation_rows(inv_rows)
    assert inv_grade["instant_invalidation_passed"] is True
    assert inv_grade["stale_prompt_injection_rate"] == 0.0
    assert inv_grade["atomic_replacement_success_rate"] == 1.0
    assert inv_grade["turn_1_retention_rate"] == 1.0

    # Check 3: Token Overhead
    tok_grade = grade_token_overhead_rows(tok_rows)
    assert tok_grade["cases"] == 3
    assert tok_grade["avg_memory_tokens"] > 0
    assert tok_grade["avg_total_tokens"] > tok_grade["avg_memory_tokens"]
    assert len(tok_grade["cases_breakdown"]) == 3

    # Overall Summary
    overall = grade_all_rows(scope_rows, inv_rows, tok_rows)
    assert overall["all_checks_passed"] is True


def test_resume_reuses_protocol_bound_rows_and_rejects_changed_manifest(tmp_path: Path) -> None:
    protocol = load_protocol(MANIFEST)
    run_dir = tmp_path / "run"

    first = run(protocol, manifest_path=MANIFEST, output_dir=run_dir, mode="offline")
    assert first.executed == 7
    assert first.reused == 0

    second = run(protocol, manifest_path=MANIFEST, output_dir=run_dir, mode="offline")
    assert second.executed == 0
    assert second.reused == 7

    changed_manifest = tmp_path / "changed.json"
    raw = json.loads(MANIFEST.read_text(encoding="utf-8"))
    raw["protocol_id"] = "changed-protocol-id"
    changed_manifest.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError, match="belongs to a different protocol"):
        ensure_run_identity(run_dir, mode="offline", protocol=load_protocol(changed_manifest), manifest_path=changed_manifest)


def test_tampered_row_fails_integrity_hash(tmp_path: Path) -> None:
    protocol = load_protocol(MANIFEST)
    run(protocol, manifest_path=MANIFEST, output_dir=tmp_path, mode="offline")
    marker = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))

    # Tamper with scope isolation row
    tamper_file = tmp_path / "rows" / "scope_isolation" / "thread-isolation-project-alpha-beta.json"
    row = json.loads(tamper_file.read_text(encoding="utf-8"))
    row["thread_a_canaries_present"] = []
    tamper_file.write_text(json.dumps(row), encoding="utf-8")

    with pytest.raises(RowIntegrityError, match="result-integrity"):
        collect_rows(protocol, tmp_path, marker)


def test_report_refuses_to_overwrite_existing_evidence(tmp_path: Path) -> None:
    protocol = load_protocol(MANIFEST)
    run(protocol, manifest_path=MANIFEST, output_dir=tmp_path, mode="offline")

    report_path = write_report(protocol, manifest_path=MANIFEST, output_dir=tmp_path)
    assert report_path.exists()
    original_bytes = report_path.read_bytes()

    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        write_report(protocol, manifest_path=MANIFEST, output_dir=tmp_path)

    assert report_path.read_bytes() == original_bytes


def test_crosstalk_leak_detection_fails_grading() -> None:
    synthetic_row = {
        "expected_thread_a_canaries": ["CANARY-A"],
        "expected_thread_b_canaries": ["CANARY-B"],
        "thread_a_canaries_present": ["CANARY-A"],
        "thread_b_canaries_present": ["CANARY-B"],
        "crosstalk_canaries_leaked": ["leak_b_to_a:CANARY-B"],
        "persisted_rejected_canaries": [],
        "expected_rejected_canaries": [],
    }
    graded = grade_scope_isolation_rows([synthetic_row])
    assert graded["scope_isolation_passed"] is False
    assert graded["cross_thread_crosstalk_rate"] == 1.0


def test_rejected_canary_leak_to_thread_b_fails_grading() -> None:
    synthetic_row = {
        "expected_thread_a_canaries": ["CANARY-A"],
        "expected_thread_b_canaries": ["CANARY-B"],
        "thread_a_canaries_present": ["CANARY-A"],
        "thread_b_canaries_present": ["CANARY-B"],
        "crosstalk_canaries_leaked": ["leak_rejected_to_thread_b:CANARY-REJECT"],
        "persisted_rejected_canaries": [],
        "expected_rejected_canaries": ["CANARY-REJECT"],
    }
    graded = grade_scope_isolation_rows([synthetic_row])
    assert graded["scope_isolation_passed"] is False
    assert graded["cross_thread_crosstalk_rate"] == 1.0


def test_stale_prompt_injection_fails_grading() -> None:
    synthetic_row = {
        "expected_turn_1_canaries": ["CANARY-STALE"],
        "turn_1_canaries_present": ["CANARY-STALE"],
        "expected_turn_2_present_canaries": ["CANARY-FRESH"],
        "turn_2_fresh_canaries_present": ["CANARY-FRESH"],
        "expected_turn_2_absent_canaries": ["CANARY-STALE"],
        "turn_2_stale_canaries_present": ["CANARY-STALE"],
    }
    graded = grade_turn_invalidation_rows([synthetic_row])
    assert graded["instant_invalidation_passed"] is False
    assert graded["stale_prompt_injection_rate"] == 1.0


def test_cli_subcommands(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # 1. CLI validate
    code = main(["validate", "--manifest", str(MANIFEST)])
    assert code == 0
    out, _ = capsys.readouterr()
    assert "Validated 2 scope isolation cases" in out

    # 2. CLI run-offline
    out_dir = tmp_path / "cli_run"
    code = main(["run-offline", "--manifest", str(MANIFEST), "--output-dir", str(out_dir)])
    assert code == 0
    out, _ = capsys.readouterr()
    assert "7 executed, 0 reused" in out

    # 3. CLI report
    code = main(["report", "--manifest", str(MANIFEST), "--output-dir", str(out_dir)])
    assert code == 0
    out, _ = capsys.readouterr()
    assert "Wrote benchmark report" in out
    assert (out_dir / "report.json").exists()
