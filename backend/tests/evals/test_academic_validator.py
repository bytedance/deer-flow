"""Tests for raw dataset pre-import validator."""

from __future__ import annotations

import json
from pathlib import Path

from src.evals.academic.validator import (
    render_validation_report_markdown,
    validate_accept_reject_dataset,
)


def test_validate_accept_reject_dataset_reports_missing_fields(tmp_path: Path):
    payload = {
        "records": [
            {
                "manuscript_id": "MS-1",
                "claims": [{"type": "strong", "has_evidence": True}],
            },
            {
                "manuscript_id": "MS-2",
                "decision": "accepted",
                "venue": "Nature",
                "claims": "invalid-claims-shape",
                "reviewer_comment_ids": ["R1", "R2"],
                "rebuttal_addressed_ids": [],
                "cross_modal_items_expected": 2,
                "cross_modal_items_used": 5,
            },
        ]
    }
    source = tmp_path / "raw.json"
    source.write_text(json.dumps(payload), encoding="utf-8")

    report = validate_accept_reject_dataset(source)
    assert report["status"] == "has_errors"
    assert report["error_count"] >= 2
    assert report["warning_count"] >= 1
    fields = {item["field"] for item in report["issues"]}
    assert "decision" in fields
    assert "venue" in fields
    assert "claims" in fields
    suggestions = report.get("repair_suggestions", [])
    assert isinstance(suggestions, list)
    assert any(item.get("field") == "rebuttal_addressed_ids" for item in suggestions)
    rebuttal_fix = next(
        item for item in suggestions if item.get("field") == "rebuttal_addressed_ids"
    )
    assert any(
        "reviewer_comments" in action for action in rebuttal_fix.get("actions", [])
    )


def test_render_validation_report_markdown_contains_summary(tmp_path: Path):
    payload = {
        "records": [
            {
                "manuscript_id": "MS-1",
                "decision": "accepted",
                "venue": "NeurIPS",
                "claims": [{"type": "strong", "has_evidence": True, "has_citation": True}],
            }
        ]
    }
    source = tmp_path / "raw-ok.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    report = validate_accept_reject_dataset(source)
    markdown = render_validation_report_markdown(report)

    assert "# Raw Dataset Validation Report" in markdown
    assert "## Summary" in markdown
    assert "## Field Issue Counts" in markdown
    assert "## Repair Suggestions" in markdown

