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
    PROMPT_PATH,
    ROOT,
    ensure_run_identity,
    run,
)

MANIFEST = ROOT / "manifest.json"


@pytest.fixture(scope="module")
def shared_run_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out_dir = tmp_path_factory.mktemp("shared_benchmark_run")
    protocol = load_protocol(MANIFEST)
    result = run(protocol, manifest_path=MANIFEST, output_dir=out_dir, mode="offline")
    assert result.executed == 7
    assert result.reused == 0
    return out_dir


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


def test_runner_and_cli_share_single_run(
    shared_run_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    protocol = load_protocol(MANIFEST)
    marker = json.loads((shared_run_dir / "run.json").read_text(encoding="utf-8"))
    assert marker["artifacts"]["prompt_path"] == PROMPT_PATH

    scope_rows, inv_rows, tok_rows = collect_rows(protocol, shared_run_dir, marker)
    assert len(scope_rows) == 2
    assert len(inv_rows) == 2
    assert len(tok_rows) == 3

    # Check 1: Scope Isolation
    scope_grade = grade_scope_isolation_rows(scope_rows)
    assert scope_grade["passed"] is True
    assert scope_grade["cross_thread_crosstalk_rate"] == 0.0
    assert scope_grade["project_to_global_contamination_rate"] == 0.0
    assert scope_grade["thread_a_retention_rate"] == 1.0
    assert scope_grade["thread_b_retention_rate"] == 1.0

    # Check 2: Turn Invalidation
    inv_grade = grade_turn_invalidation_rows(inv_rows)
    assert inv_grade["passed"] is True
    assert inv_grade["stale_prompt_injection_rate"] == 0.0
    assert inv_grade["atomic_replacement_success_rate"] == 1.0
    assert inv_grade["turn_1_retention_rate"] == 1.0

    # Check 3: Token Overhead
    tok_grade = grade_token_overhead_rows(tok_rows)
    assert tok_grade["cases"] == 3
    assert tok_grade["avg_memory_tokens"] > 0
    assert tok_grade["avg_total_tokens"] > tok_grade["avg_memory_tokens"]

    # Short Report Grading Summary
    overall = grade_all_rows(scope_rows, inv_rows, tok_rows)
    assert overall["all_checks_passed"] is True

    # CLI subcommands sharing this run
    # 1. CLI validate
    code_val = main(["validate", "--manifest", str(MANIFEST)])
    assert code_val == 0
    out_val, _ = capsys.readouterr()
    assert "Validated 2 scope isolation cases" in out_val

    # 2. CLI report writing short report into shared run directory
    code_rep = main(["report", "--manifest", str(MANIFEST), "--output-dir", str(shared_run_dir)])
    assert code_rep == 0
    out_rep, _ = capsys.readouterr()
    assert "Wrote benchmark report" in out_rep

    report_path = shared_run_dir / "report.json"
    assert report_path.exists()
    report_data = json.loads(report_path.read_text(encoding="utf-8"))
    assert report_data["artifacts"]["prompt_path"] == PROMPT_PATH
    assert report_data["summary"]["all_checks_passed"] is True
    assert "scope_isolation" in report_data["summary"]
    assert "instant_invalidation" in report_data["summary"]
    assert "token_overhead" in report_data["summary"]


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
        ensure_run_identity(
            run_dir,
            mode="offline",
            protocol=load_protocol(changed_manifest),
            manifest_path=changed_manifest,
        )


def test_tampered_row_fails_integrity_hash(tmp_path: Path) -> None:
    protocol = load_protocol(MANIFEST)
    run(protocol, manifest_path=MANIFEST, output_dir=tmp_path, mode="offline")
    marker = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))

    # Tamper with scope isolation row in flat rows directory
    tamper_file = tmp_path / "rows" / "thread-isolation-project-alpha-beta.json"
    row = json.loads(tamper_file.read_text(encoding="utf-8"))
    row["thread_a_canaries_present"] = []
    tamper_file.write_text(json.dumps(row), encoding="utf-8")

    with pytest.raises(RowIntegrityError, match="result-integrity"):
        collect_rows(protocol, tmp_path, marker)


def test_report_refuses_to_overwrite_existing_evidence(shared_run_dir: Path) -> None:
    protocol = load_protocol(MANIFEST)
    # shared_run_dir already has report.json written by test_runner_and_cli_share_single_run
    report_path = shared_run_dir / "report.json"
    assert report_path.exists()
    original_bytes = report_path.read_bytes()

    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        write_report(protocol, manifest_path=MANIFEST, output_dir=shared_run_dir)

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
    assert graded["passed"] is False
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
    assert graded["passed"] is False
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
    assert graded["passed"] is False
    assert graded["stale_prompt_injection_rate"] == 1.0
