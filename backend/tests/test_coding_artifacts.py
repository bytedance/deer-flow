import json

import pytest

from deerflow.subagents.coding_artifacts import (
    AnalysisReport,
    CodingArtifactError,
    parse_coding_artifact,
)


def _analysis_payload() -> dict:
    return {
        "report_type": "analysis_report",
        "summary": "The discount formula is wrong.",
        "relevant_files": ["pricing.py"],
        "implementation_steps": ["Fix the formula."],
        "risks": ["Boolean quantities remain accepted."],
        "test_plan": ["Run pricing unit tests."],
        "implementer_input": "Change only calculate_total.",
    }


def test_parse_coding_artifact_accepts_exact_json_contract() -> None:
    artifact = parse_coding_artifact(json.dumps(_analysis_payload()), expected_type="analysis_report")

    assert isinstance(artifact, AnalysisReport)
    assert artifact.relevant_files == ["pricing.py"]


def test_parse_coding_artifact_accepts_json_code_fence() -> None:
    payload = json.dumps(_analysis_payload())

    artifact = parse_coding_artifact(f"```json\n{payload}\n```", expected_type="analysis_report")

    assert artifact.report_type == "analysis_report"


@pytest.mark.parametrize(
    "payload",
    [
        "not json",
        json.dumps({"report_type": "analysis_report", "summary": "incomplete"}),
        json.dumps({**_analysis_payload(), "unexpected": "field"}),
    ],
)
def test_parse_coding_artifact_rejects_invalid_contract(payload: str) -> None:
    with pytest.raises(CodingArtifactError, match="Invalid analysis_report"):
        parse_coding_artifact(payload, expected_type="analysis_report")


def test_parse_coding_artifact_rejects_wrong_report_type() -> None:
    payload = {
        "report_type": "review_report",
        "verdict": "PASS",
        "summary": "done",
        "acceptance_results": [],
        "issues": [],
        "test_evidence": [],
        "required_changes": [],
    }

    with pytest.raises(CodingArtifactError, match="Expected analysis_report"):
        parse_coding_artifact(json.dumps(payload), expected_type="analysis_report")
