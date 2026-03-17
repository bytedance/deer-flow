"""Tests for OpenReview offline benchmark importer."""

from __future__ import annotations

from src.evals.academic import build_openreview_raw_payload
from src.evals.academic.offline_benchmark_suite import REQUIRED_RAW_RECORD_FIELDS


def test_build_openreview_raw_payload_produces_required_fields():
    payload = build_openreview_raw_payload(
        [
            {
                "id": "or-1",
                "venue": "NeurIPS",
                "decision": "Reject",
                "reviews": [
                    {
                        "text": (
                            "The rebuttal is superficial and does not address baseline concerns. "
                            "There is a style mismatch for this venue."
                        )
                    }
                ],
            }
        ],
        dataset_name="openreview_unit",
    )
    assert payload["metadata"]["dataset_name"] == "openreview_unit"
    assert len(payload["records"]) == 1
    record = payload["records"][0]
    assert set(REQUIRED_RAW_RECORD_FIELDS).issubset(set(record.keys()))
    assert record["decision"] == "rejected"
    assert record["domain"] == "ai_cs"
    assert "style_mismatch" in record["failure_modes"]
    assert "superficial_rebuttal" in record["failure_modes"]


def test_openreview_importer_infers_ethics_gap_and_citation_hallucination():
    payload = build_openreview_raw_payload(
        [
            {
                "forum": "or-2",
                "venue": "Nature",
                "decision": "Reject",
                "reviews": [
                    {
                        "text": (
                            "Potential fabricated reference 10.9999/fake-doi appears in rebuttal. "
                            "Ethics and consent statements are missing."
                        )
                    }
                ],
            }
        ],
        dataset_name="openreview_unit_2",
    )
    record = payload["records"][0]
    assert record["domain"] == "biomed"
    assert "citation_hallucination" in record["failure_modes"]
    assert "ethics_gap" in record["failure_modes"]
    assert "10.9999/fake-doi" in record["generated_citations"]
