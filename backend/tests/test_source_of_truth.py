"""Tests for single-source-of-truth manifest and fact compilation."""

from __future__ import annotations

from src.research_writing import (
    CitationRegistry,
    ClaimGraph,
    EvidenceStore,
    FigureArtifact,
    NumericFact,
    SectionCompiler,
    SectionDraft,
    SourceOfTruthStore,
    TableArtifact,
)


def test_source_of_truth_manifest_and_consistency(tmp_path):
    store = SourceOfTruthStore(tmp_path / "sot.json")
    store.upsert_fact(
        NumericFact(
            fact_id="f1",
            metric="AUROC",
            value=0.912,
            unit="",
            context="validation cohort",
            source_artifact="/mnt/user-data/outputs/results.json",
        )
    )
    store.upsert_figure(
        FigureArtifact(
            figure_id="fig1",
            caption="Model performance overview",
            artifact_path="/mnt/user-data/outputs/figures/fig1.png",
            linked_fact_ids=["f1"],
        )
    )
    store.upsert_table(
        TableArtifact(
            table_id="tab1",
            title="Main results",
            artifact_path="/mnt/user-data/outputs/tables/tab1.csv",
            linked_fact_ids=["f1"],
        )
    )

    manifest = store.build_manifest()
    assert len(manifest["numeric_facts"]) == 1
    assert len(manifest["figures"]) == 1
    assert len(manifest["tables"]) == 1

    mismatches = store.consistency_check("AUROC is 0.912 while another metric is 0.700.")
    assert "0.700" in mismatches


def test_section_compiler_includes_fact_sentences(tmp_path):
    claim_graph = ClaimGraph(tmp_path / "claims.json")
    evidence_store = EvidenceStore(tmp_path / "evidence.json")
    citation_registry = CitationRegistry(tmp_path / "citations.json")
    source_of_truth = SourceOfTruthStore(tmp_path / "sot.json")
    source_of_truth.upsert_fact(
        NumericFact(
            fact_id="f1",
            metric="Macro-F1",
            value=0.845,
            source_artifact="/mnt/user-data/outputs/results.json",
            context="external test set",
        )
    )

    section = SectionDraft(section_id="results", section_name="Results", fact_ids=["f1"], claim_ids=[])
    result = SectionCompiler.compile_section(
        section,
        claim_graph,
        evidence_store,
        citation_registry,
        source_of_truth_store=source_of_truth,
        mode="strict",
    )
    assert "Macro-F1 is 0.845" in result.compiled_text


def test_source_of_truth_semantic_check_normalizes_units_and_context(tmp_path):
    store = SourceOfTruthStore(tmp_path / "sot-semantic.json")
    store.upsert_fact(
        NumericFact(
            fact_id="f-base",
            metric="Baseline ratio",
            value=0.12,
            unit="ratio",
            source_artifact="/mnt/user-data/outputs/base.json",
        )
    )
    store.upsert_fact(
        NumericFact(
            fact_id="f-main",
            metric="Response ratio",
            value=0.05,
            unit="ratio",
            source_artifact="/mnt/user-data/outputs/main.json",
            population="treated cohort",
            condition="drug a",
            timepoint="week 4",
            p_value=0.03,
            derived_from=["f-base"],
        )
    )

    text = "In treated cohort under drug A at week 4, response reached 5% (p=0.03)."
    report = store.semantic_consistency_check(text)
    assert report["matches"] or report["mismatches"]
    assert any(item["fact_id"] == "f-main" for item in report["matches"])
    assert "5%" not in store.consistency_check(text)
