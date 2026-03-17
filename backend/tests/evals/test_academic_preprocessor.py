"""Tests for low-risk auto-fix preprocessor."""

from __future__ import annotations

from src.evals.academic.preprocessor import preprocess_accept_reject_payload


def test_preprocessor_maps_aliases_and_wraps_arrays():
    raw = {
        "records": [
            {
                "manuscript_id": "MS-1",
                "outcome": "accepted",
                "journal": "Nature",
                "output_citations": "10.1000/demo",
                "ground_truth_citations": ["10.1000/demo", "10.1000/demo2"],
                "claim_annotations": {
                    "type": "strong",
                    "has_evidence": True,
                    "has_citation": True,
                },
                "reviewer_comments": [{"id": "R1"}, {"comment_id": "R2"}],
                "addressed_comment_ids": "R1",
                "acceptance_checklist": ["ethics"],
                "satisfied_checklist": "ethics",
            }
        ]
    }

    result = preprocess_accept_reject_payload(raw, apply_autofix=True)
    fixed = result["fixed_payload"]["records"][0]
    report = result["report"]

    assert fixed["decision"] == "accepted"
    assert fixed["venue"] == "Nature"
    assert fixed["generated_citations"] == ["10.1000/demo"]
    assert fixed["verified_citations"] == ["10.1000/demo", "10.1000/demo2"]
    assert isinstance(fixed["claims"], list)
    assert fixed["reviewer_comment_ids"] == ["R1", "R2"]
    assert fixed["rebuttal_addressed_ids"] == ["R1"]
    assert fixed["venue_checklist_items"] == ["ethics"]
    assert fixed["venue_satisfied_items"] == ["ethics"]
    assert report["modified_record_count"] == 1
    assert "merge:reviewer_comments->reviewer_comment_ids" in report["fix_counts"]


def test_preprocessor_safe_level_keeps_high_risk_claim_shape():
    raw = {
        "records": [
            {
                "manuscript_id": "MS-safe",
                "outcome": "accepted",
                "journal": "Nature",
                "claim_annotations": {
                    "type": "strong",
                    "has_evidence": True,
                    "has_citation": True,
                },
            }
        ]
    }

    result = preprocess_accept_reject_payload(
        raw,
        apply_autofix=True,
        autofix_level="safe",
    )
    fixed = result["fixed_payload"]["records"][0]
    assert fixed["decision"] == "accepted"
    assert fixed["venue"] == "Nature"
    # safe level should not wrap claim object into array
    assert isinstance(fixed["claims"], dict)


def test_preprocessor_aggressive_level_splits_scalar_fields():
    raw = {
        "records": [
            {
                "manuscript_id": "MS-aggr",
                "decision": "accepted",
                "venue": "NeurIPS",
                "output_citations": "10.1/a; 10.1/b",
                "review_comments": "R1;R2",
                "claims": "claim one; claim two",
            }
        ]
    }

    result = preprocess_accept_reject_payload(
        raw,
        apply_autofix=True,
        autofix_level="aggressive",
    )
    fixed = result["fixed_payload"]["records"][0]
    report = result["report"]

    assert fixed["generated_citations"] == ["10.1/a", "10.1/b"]
    assert fixed["reviewer_comment_ids"] == ["R1", "R2"]
    assert isinstance(fixed["claims"], list)
    assert len(fixed["claims"]) == 2
    assert report["autofix_level"] == "aggressive"
    assert "split:claims" in report["fix_counts"]

