"""Tests for real accept/reject dataset import pipeline."""

from __future__ import annotations

from pathlib import Path

from src.evals.academic.importer import import_accept_reject_dataset


def test_import_accept_reject_dataset_anonymization_and_versioning():
    fixture = (
        Path(__file__).parent
        / "fixtures"
        / "academic_raw_accept_reject_records.json"
    )
    payload = import_accept_reject_dataset(
        fixture,
        dataset_name="top_tier_accept_reject_real",
        dataset_version="2026.03",
        benchmark_split="top_tier_real_v2026_03",
        source_name="curated-real-corpus",
        anonymize=True,
    )

    assert payload["imported_case_count"] == 2
    assert payload["accepted_case_count"] == 1
    assert payload["rejected_case_count"] == 1
    assert payload["dataset_version"] == "2026.03"
    dataset = payload["dataset_payload"]
    assert dataset["metadata"]["schema_version"] == "academic_eval_dataset.v2"
    assert dataset["metadata"]["pipeline_version"] == "accept_reject_importer.v1"
    assert dataset["metadata"]["anonymized"] is True
    cases = dataset["cases"]
    assert cases[0]["case_id"].startswith("anon_")
    claim_text = cases[0]["claims"][0].get("text", "")
    assert "[EMAIL]" in claim_text or "[ORCID]" in claim_text
    assert cases[1]["failure_modes"] == ["overclaim", "numeric_drift"]
    assert isinstance(cases[1]["manuscript_text"], str)

