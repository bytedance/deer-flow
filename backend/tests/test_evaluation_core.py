from __future__ import annotations

import json
import sys
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from deerflow.evaluation import (
    build_evaluation_report,
    build_metrics_summary,
    render_markdown_report,
    report_to_json,
    run_check,
)
from deerflow.evaluation.metrics import compare_paired_variants
from deerflow.evaluation.results import CheckResult, FailureKind, normalize_attempt_result, normalize_failure_kind
from deerflow.evaluation.schema import (
    CommandExitZeroCheck,
    EvalSuite,
    RunEventExistsCheck,
    WorkspaceFileContainsCheck,
)


def _suite() -> EvalSuite:
    return EvalSuite.model_validate(
        {
            "name": "eval_core",
            "version": 1,
            "variants": [
                {"id": "baseline", "label": "Baseline"},
                {"id": "candidate", "label": "Candidate"},
            ],
            "items": [
                {
                    "id": "write-report",
                    "type": "task",
                    "metric_tags": ["task_success"],
                    "input": {"prompt": "write the report"},
                }
            ],
        }
    )


def test_suite_rejects_duplicate_item_id():
    with pytest.raises(ValidationError, match="duplicate item id: duplicated"):
        EvalSuite.model_validate(
            {
                "name": "duplicates",
                "items": [
                    {"id": "duplicated", "type": "task", "input": {"prompt": "first"}},
                    {"id": "duplicated", "type": "task", "input": {"prompt": "second"}},
                ],
            }
        )


def test_workspace_file_contains_passes_and_reports_content_mismatch(tmp_path):
    (tmp_path / "report.md").write_text("hello stable output\n", encoding="utf-8")
    check = WorkspaceFileContainsCheck(
        type="workspace_file_contains",
        path="report.md",
        contains="stable output",
        not_contains=["forbidden"],
    )

    result = run_check(check, workspace_path=tmp_path)

    assert result.passed is True
    assert result.failure_kind is None
    assert result.metadata["missing"] == []
    assert result.metadata["forbidden_present"] == []

    failed = run_check(
        WorkspaceFileContainsCheck(
            type="workspace_file_contains",
            path="report.md",
            contains=["missing phrase"],
            not_contains=["hello"],
        ),
        workspace_path=tmp_path,
    )

    assert failed.passed is False
    assert "missing phrase" in failed.message
    assert "hello" in failed.message
    assert failed.metadata["missing"] == ["missing phrase"]
    assert failed.metadata["forbidden_present"] == ["hello"]


def test_command_exit_zero_runs_argv_inside_workspace(tmp_path):
    (tmp_path / "artifact.txt").write_text("ok", encoding="utf-8")
    check = CommandExitZeroCheck(
        type="command_exit_zero",
        command=[
            sys.executable,
            "-c",
            "from pathlib import Path; assert Path('artifact.txt').read_text() == 'ok'; print('done')",
        ],
        stdout_limit=20,
        stderr_limit=20,
    )

    result = run_check(check, workspace_path=tmp_path)

    assert result.passed is True
    assert result.exit_code == 0
    assert result.stdout == "done\n"


def test_run_event_exists_matches_type_count_and_metadata(tmp_path):
    check = RunEventExistsCheck(type="run_event_exists", event_type="llm.ai.response", min_count=2, metadata={"model": "fast"})
    events = [
        {"event_type": "llm.ai.response", "metadata": {"model": "fast"}},
        {"event_type": "llm.ai.response", "metadata": {"model": "fast", "tokens": 10}},
        {"event_type": "llm.ai.response", "metadata": {"model": "slow"}},
    ]

    result = run_check(check, workspace_path=tmp_path, run_events=events)

    assert result.passed is True
    assert result.metadata["count"] == 2


def test_paired_comparison_reports_insufficient_data_when_candidate_is_missing():
    comparison = compare_paired_variants(
        _suite(),
        [
            normalize_attempt_result(
                suite_item_id="write-report",
                variant_id="baseline",
                sample_index=0,
                status="passed",
            )
        ],
    )

    assert comparison.status == "insufficient_data"
    assert comparison.conclusion_label == "insufficient_data"
    assert comparison.missing_pairs == [
        {
            "suite_item_id": "write-report",
            "sample_index": 0,
            "missing_variants": ["candidate"],
        }
    ]


def test_failure_kind_normalization_distinguishes_agent_trace_external_and_platform_failures():
    assert normalize_failure_kind(status="failed", error="agent produced the wrong final answer") == FailureKind.AGENT_ERROR.value
    assert normalize_failure_kind(status="failed", trace_gate={"passed": False}) == FailureKind.TRACE_GATE.value
    assert (
        normalize_failure_kind(
            status="failed",
            check_results=[
                CheckResult(
                    type="run_event_exists",
                    passed=False,
                    failure_kind=FailureKind.PLATFORM_EVIDENCE_MISSING.value,
                )
            ],
        )
        == FailureKind.PLATFORM_EVIDENCE_MISSING.value
    )
    assert normalize_failure_kind(status="error", error="missing credential for external service") == FailureKind.EXTERNAL_BLOCKED.value
    assert normalize_failure_kind(status="error", error="eval platform run_events provider failed") == FailureKind.PLATFORM_DEFECT.value


def test_failure_kind_normalization_prioritizes_external_errors_over_check_failures():
    assert (
        normalize_failure_kind(
            status="failed",
            check_results=[
                CheckResult(
                    type="workspace_file_contains",
                    passed=False,
                    failure_kind=FailureKind.CHECK_FAILED.value,
                    message="policy state was not updated",
                )
            ],
            error="Error code: 401 - authentication_error: invalid api key",
        )
        == FailureKind.EXTERNAL_BLOCKED.value
    )


def test_failure_kind_normalization_keeps_forbidden_content_as_check_failure():
    assert (
        normalize_failure_kind(
            status="failed",
            check_results=[
                CheckResult(
                    type="workspace_file_contains",
                    passed=False,
                    failure_kind=FailureKind.CHECK_FAILED.value,
                    message="forbidden present: KB-ARCHIVE-2025-ATLAS, KB-RUMOR-UNVERIFIED",
                )
            ],
            error="forbidden present: KB-ARCHIVE-2025-ATLAS, KB-RUMOR-UNVERIFIED",
        )
        == FailureKind.CHECK_FAILED.value
    )


def test_normalize_attempt_result_reclassifies_persisted_check_failure_with_llm_error_summary():
    result = normalize_attempt_result(
        suite_item_id="complex-policy-refund",
        variant_id="baseline",
        sample_index=0,
        attempt_index=0,
        status="failed",
        check_results=[
            CheckResult(
                type="command_exit_zero",
                passed=False,
                failure_kind=FailureKind.CHECK_FAILED.value,
                message="assert_policy_state failed after model error",
            )
        ],
        run_event_summary={
            "event_count": 4,
            "event_types": {
                "run.start": 1,
                "llm.human.input": 1,
                "llm.error": 1,
                "run.end": 1,
            },
        },
        failure_kind=FailureKind.CHECK_FAILED.value,
        error="llm.error event present before agent response; assert_policy_state failed",
    )

    assert result.failure_kind == FailureKind.EXTERNAL_BLOCKED.value


def test_json_and_markdown_report_render_from_metrics_summary():
    suite = _suite()
    attempts = [
        normalize_attempt_result(
            suite_item_id="write-report",
            variant_id="baseline",
            sample_index=0,
            status="passed",
            thread_id="thread-baseline",
            run_id="run-baseline",
            run_event_summary={
                "event_count": 3,
                "event_types": {
                    "run.start": 1,
                    "llm.ai.response": 1,
                    "run.end": 1,
                },
            },
            metrics={"task_success": True},
        ),
        normalize_attempt_result(
            suite_item_id="write-report",
            variant_id="candidate",
            sample_index=0,
            status="passed",
            metrics={"task_success": True},
        ),
    ]
    metrics_summary = build_metrics_summary(suite, attempts)
    report = build_evaluation_report(
        suite,
        attempts,
        eval_run_id="eval-run-1",
        dataset_digest="sha256:abc",
        generated_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        metrics_summary=metrics_summary,
    )

    payload = json.loads(report_to_json(report))
    markdown = render_markdown_report(report)

    assert payload["schema_version"] == "deerflow.evaluation.report.v1"
    assert payload["summary"]["pass_rate"] == 1.0
    assert payload["effect_summary"]["comparison"]["conclusion_label"] == "neutral"
    baseline_item = next(item for item in payload["items"] if item["variant_id"] == "baseline")
    assert baseline_item["trace"]["thread_id"] == "thread-baseline"
    assert baseline_item["trace"]["run_id"] == "run-baseline"
    assert baseline_item["trace"]["event_types"]["llm.ai.response"] == 1
    assert baseline_item["trace"]["events_api_path"] == "/api/threads/thread-baseline/runs/run-baseline/events"
    assert "# DeerFlow Evaluation Report: eval_core" in markdown
    assert "## Comparison" in markdown
    assert "## Trace" in markdown
    assert "thread-baseline" in markdown
    assert "llm.ai.response:1, run.end:1, run.start:1" in markdown
    assert "`write-report`" in markdown


def test_report_item_payload_and_markdown_include_failure_kind_categories():
    suite = _suite()
    attempts = [
        normalize_attempt_result(
            suite_item_id="write-report",
            variant_id="baseline",
            sample_index=0,
            status="failed",
            failure_kind=FailureKind.EXTERNAL_BLOCKED.value,
            error="missing credential for external service",
        ),
        normalize_attempt_result(
            suite_item_id="write-report",
            variant_id="candidate",
            sample_index=0,
            status="failed",
            failure_kind=FailureKind.PLATFORM_DEFECT.value,
            error="eval platform report builder failed",
        ),
    ]

    report = build_evaluation_report(suite, attempts, eval_run_id="eval-run-failures")
    payload = json.loads(report_to_json(report))
    markdown = render_markdown_report(report)

    assert {item["failure_kind"] for item in payload["items"]} == {
        FailureKind.EXTERNAL_BLOCKED.value,
        FailureKind.PLATFORM_DEFECT.value,
    }
    assert f"`{FailureKind.EXTERNAL_BLOCKED.value}`" in markdown
    assert f"`{FailureKind.PLATFORM_DEFECT.value}`" in markdown
