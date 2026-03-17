"""Tests for capability catalog and scoring framework."""

from __future__ import annotations

from src.research_writing.capability_framework import capability_catalog, evaluate_capabilities
from src.research_writing.citation_registry import CitationRecord
from src.research_writing.claim_graph import Claim
from src.research_writing.evidence_store import EvidenceUnit
from src.research_writing.project_state import ResearchProject, SectionDraft
from src.research_writing.source_of_truth import NumericFact


def test_capability_catalog_contains_eight_capabilities():
    payload = capability_catalog()
    assert payload["schema_version"] == "deerflow.capability_catalog.v1"
    assert len(payload["capabilities"]) == 8
    capability_ids = [item["capability_id"] for item in payload["capabilities"]]
    assert "claim_engineering" in capability_ids
    assert "long_horizon_consistency" in capability_ids


def test_evaluate_capabilities_returns_scorecards():
    project = ResearchProject(
        project_id="p1",
        title="Capability test",
        discipline="ai_cs",
        target_venue="NeurIPS",
        research_questions=["Can we improve sample efficiency?"],
        hypotheses=["If we use adapter tuning, then sample efficiency improves."],
        sections=[
            SectionDraft(
                section_id="discussion",
                section_name="Discussion",
                content="We show a 12.0% improvement [data:ev1] [citation:cit1]. However, limitations remain.",
                claim_ids=["c1"],
                evidence_ids=["ev1"],
                citation_ids=["cit1"],
                fact_ids=["f1"],
            )
        ],
    )
    section = project.sections[0]
    claims = [Claim(claim_id="c1", text="Model improves by 12.0%.", claim_type="result", evidence_ids=["ev1"], citation_ids=["cit1"])]
    evidence_units = [
        EvidenceUnit(
            evidence_id="ev1",
            evidence_type="raw_data",
            summary="Primary benchmark result.",
            source_ref="/tmp/raw.csv",
            citation_ids=["cit1"],
        )
    ]
    citations = [CitationRecord(citation_id="cit1", title="Demo paper", source="arxiv", verified=True)]
    facts = [NumericFact(fact_id="f1", metric="improvement", value=12.0, unit="%", source_artifact="/tmp/raw.csv")]

    payload = evaluate_capabilities(
        project=project,
        section=section,
        claims=claims,
        evidence_units=evidence_units,
        citations=citations,
        facts=facts,
        hitl_decisions=[],
        compliance_payload={"compliance_audit": {"risk_level": "low"}, "safety_valve_triggered": False},
        latex_payload={"tex_path": "/mnt/user-data/outputs/research-writing/latex/p1.tex", "compile_status": "success", "compile_log_path": "/tmp/log"},
        section_versions={"versions": [{"version_id": "discussion-v1"}]},
    )
    assert payload["schema_version"] == "deerflow.capability_snapshot.v1"
    assert payload["status"] in {"pass", "warn", "fail"}
    assert len(payload["scorecards"]) == 8
    assert payload["inputs"]["project_id"] == "p1"
