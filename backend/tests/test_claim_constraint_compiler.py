"""Tests for claim hard-constraint compiler."""

from __future__ import annotations

from src.research_writing import (
    CitationRecord,
    CitationRegistry,
    Claim,
    Claim_Constraint_Compiler,
    ClaimConstraintCompiler,
    EvidenceStore,
    EvidenceUnit,
    classify_claim_sentence,
    enforce_claim_constraints,
)


def test_classify_claim_sentence():
    assert classify_claim_sentence("This improves AUROC by 5.2%.") == "numeric"
    assert classify_claim_sentence("Method A outperforms Method B.") == "comparative"
    assert classify_claim_sentence("X causes Y in cohort Z.") == "causal"
    assert classify_claim_sentence("This is the first framework for this task.") == "novelty"
    assert classify_claim_sentence("We discuss related work.") == "general"


def test_enforce_constraints_flags_missing_support(tmp_path):
    evidence_store = EvidenceStore(tmp_path / "evidence.json")
    citation_registry = CitationRegistry(tmp_path / "citations.json")
    claim = Claim(
        claim_id="c1",
        text="Our method demonstrates 15% better performance than baseline.",
        claim_type="strong",
        evidence_ids=[],
        citation_ids=[],
    )
    compiled, issues = enforce_claim_constraints(claim, evidence_store, citation_registry, mode="strict")
    assert "insufficient data" in compiled
    assert "citation needed" in compiled
    assert "grounding required" in compiled
    assert len(issues) >= 2


def test_enforce_constraints_passes_when_grounded(tmp_path):
    evidence_store = EvidenceStore(tmp_path / "evidence.json")
    citation_registry = CitationRegistry(tmp_path / "citations.json")
    evidence_store.upsert(
        EvidenceUnit(
            evidence_id="ev1",
            evidence_type="raw_data",
            summary="Benchmark result table",
            source_ref="/mnt/user-data/outputs/results.json",
        )
    )
    citation_registry.upsert(
        CitationRecord(
            citation_id="cit1",
            title="Benchmark paper",
            doi="10.1000/example",
            authors=["A. Author"],
            year=2023,
            source="crossref",
            verified=True,
        )
    )
    claim = Claim(
        claim_id="c2",
        text="Our method demonstrates 15% better performance than baseline.",
        claim_type="strong",
        evidence_ids=["ev1"],
        citation_ids=["cit1"],
    )
    compiled, issues = enforce_claim_constraints(claim, evidence_store, citation_registry, mode="strict")
    assert "baseline." in compiled
    assert "[data:ev1]" in compiled
    assert "[citation:cit1]" in compiled
    assert issues == []


def test_claim_compiler_detects_unknown_explicit_ids(tmp_path):
    evidence_store = EvidenceStore(tmp_path / "evidence.json")
    citation_registry = CitationRegistry(tmp_path / "citations.json")
    claim = Claim(
        claim_id="c3",
        text="This result is robust [data:missing_data] [citation:missing_citation].",
        claim_type="result",
    )
    compiled, issues = enforce_claim_constraints(claim, evidence_store, citation_registry, mode="strict")
    assert "grounding required" in compiled
    assert any("unknown Data ID" in issue.message for issue in issues)
    assert any("unknown Citation ID" in issue.message for issue in issues)


def test_claim_constraint_compiler_alias_and_direct_usage(tmp_path):
    evidence_store = EvidenceStore(tmp_path / "evidence.json")
    citation_registry = CitationRegistry(tmp_path / "citations.json")
    evidence_store.upsert(
        EvidenceUnit(
            evidence_id="fcs:run-1",
            evidence_type="raw_data",
            summary="FCS gating statistics",
            source_ref="/mnt/user-data/outputs/gating.csv",
        )
    )
    compiler = ClaimConstraintCompiler(evidence_store=evidence_store, citation_registry=citation_registry, mode="strict")
    alias_compiler = Claim_Constraint_Compiler(evidence_store=evidence_store, citation_registry=citation_registry, mode="strict")
    claim = Claim(
        claim_id="c4",
        text="Cell population improves by 8.1% after treatment.",
        claim_type="result",
        evidence_ids=["fcs:run-1"],
        citation_ids=[],
    )

    result = compiler.compile(claim)
    alias_result = alias_compiler.compile(claim)
    assert result.compiled_text == alias_result.compiled_text
    assert "[data:fcs:run-1]" in result.compiled_text
    assert any("Missing Citation ID grounding" in issue.message for issue in result.issues)


def test_claim_map_entry_prefers_data_and_citation_markers(tmp_path):
    evidence_store = EvidenceStore(tmp_path / "evidence.json")
    citation_registry = CitationRegistry(tmp_path / "citations.json")
    evidence_store.upsert(
        EvidenceUnit(
            evidence_id="ev-1",
            evidence_type="raw_data",
            summary="Primary benchmark table",
            source_ref="/mnt/user-data/outputs/results.csv",
        )
    )
    evidence_store.upsert(
        EvidenceUnit(
            evidence_id="ev-2",
            evidence_type="raw_data",
            summary="Secondary benchmark table",
            source_ref="/mnt/user-data/outputs/results2.csv",
        )
    )
    citation_registry.upsert(
        CitationRecord(
            citation_id="cit-1",
            title="Primary baseline paper",
            doi="10.1000/primary",
            authors=["A. Author"],
            year=2022,
            source="crossref",
            verified=True,
        )
    )
    citation_registry.upsert(
        CitationRecord(
            citation_id="cit-2",
            title="Secondary baseline paper",
            doi="10.1000/secondary",
            authors=["B. Author"],
            year=2021,
            source="crossref",
            verified=True,
        )
    )
    compiler = ClaimConstraintCompiler(evidence_store=evidence_store, citation_registry=citation_registry, mode="strict")
    claim = Claim(
        claim_id="c5",
        text="Our method outperforms the baseline by 5%.",
        claim_type="strong",
        evidence_ids=["ev-1", "ev-2"],
        citation_ids=["cit-1", "cit-2"],
    )

    entry = compiler.build_claim_map_entry(claim)
    assert entry.claim_id == "c5"
    assert entry.marker_count == 2
    assert "[data:ev-1]" in entry.sentence_draft
    assert "[citation:cit-1]" in entry.sentence_draft
    assert "[data:ev-2]" not in entry.sentence_draft
    assert "[citation:cit-2]" not in entry.sentence_draft


def test_claim_map_entry_requires_rewrite_for_unknown_ids(tmp_path):
    evidence_store = EvidenceStore(tmp_path / "evidence.json")
    citation_registry = CitationRegistry(tmp_path / "citations.json")
    compiler = ClaimConstraintCompiler(evidence_store=evidence_store, citation_registry=citation_registry, mode="strict")
    claim = Claim(
        claim_id="c6",
        text="This result is definitive [data:missing] [citation:missing-cit].",
        claim_type="strong",
        evidence_ids=[],
        citation_ids=[],
    )

    entry = compiler.build_claim_map_entry(claim)
    issues = compiler.validate_claim_map_entry(entry)
    assert entry.rewrite_required is True
    assert entry.rewrite_reason is not None
    assert "missing" in entry.rewrite_reason.lower()
    assert any(issue.severity == "error" for issue in issues)
    assert any("Rewrite required" in issue.message for issue in issues)
