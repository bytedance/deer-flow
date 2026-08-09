"""Coding 子 Agent 的结构化交接产物。"""

import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError


class _StrictReport(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TestEvidence(_StrictReport):
    command: str
    status: Literal["passed", "failed", "not_run"]
    evidence: str


class AnalysisReport(_StrictReport):
    report_type: Literal["analysis_report"]
    summary: str
    relevant_files: list[str]
    implementation_steps: list[str]
    risks: list[str]
    test_plan: list[str]
    implementer_input: str


class ImplementationReport(_StrictReport):
    report_type: Literal["implementation_report"]
    summary: str
    changed_files: list[str]
    key_changes: list[str]
    tests: list[TestEvidence]
    remaining_risks: list[str]
    review_focus: list[str]


class ReviewReport(_StrictReport):
    report_type: Literal["review_report"]
    verdict: Literal["PASS", "FAIL"]
    summary: str
    acceptance_results: list[str]
    issues: list[str]
    test_evidence: list[str]
    required_changes: list[str]


CodingArtifact = Annotated[
    AnalysisReport | ImplementationReport | ReviewReport,
    Field(discriminator="report_type"),
]
_ARTIFACT_ADAPTER = TypeAdapter(CodingArtifact)


class CodingArtifactError(ValueError):
    """子 Agent 输出不满足结构化交接契约。"""


def _strip_json_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped

    lines = stripped.splitlines()
    if len(lines) < 3 or lines[-1].strip() != "```":
        return stripped
    return "\n".join(lines[1:-1]).strip()


def parse_coding_artifact(text: str, *, expected_type: str):
    """解析并验证子 Agent 返回的 JSON 产物。"""
    payload = _strip_json_fence(text)
    try:
        raw = json.loads(payload)
        artifact = _ARTIFACT_ADAPTER.validate_python(raw)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise CodingArtifactError(f"Invalid {expected_type}: {exc}") from exc

    if artifact.report_type != expected_type:
        raise CodingArtifactError(f"Expected {expected_type}, got {artifact.report_type}")
    return artifact


def render_upstream_artifacts(artifacts: list[dict]) -> str:
    """把已验证的上游产物渲染成下游 Agent 的数据输入。"""
    return json.dumps(artifacts, ensure_ascii=False, indent=2)
