"""Tests for structured research-writing domain models."""

from __future__ import annotations

from unittest.mock import patch

from src.config.paths import Paths
from src.research_writing import (
    CitationGraphEdge,
    CitationGraphNode,
    CitationGraphRag,
    CitationRecord,
    CitationRegistry,
    Claim,
    ClaimGraph,
    DynamicLiteratureGraph,
    EvidenceStore,
    EvidenceUnit,
    FullTextIngestResult,
    LiteratureClaimEdge,
    LiteratureClaimNode,
    LiteratureRecord,
    NarrativeWritingStrategy,
    ResearchProject,
    ResearchProjectStateStore,
    SectionCompiler,
    SectionDraft,
)
from src.research_writing.runtime_service import (
    compile_project_section,
    get_engineering_gates_metrics,
    get_section_traceability,
    ingest_fulltext_evidence,
    list_section_versions,
    plan_project_section_narrative,
    rollback_section_to_version,
    upsert_project,
    upsert_section,
)


def test_project_state_store_roundtrip(tmp_path):
    store = ResearchProjectStateStore(tmp_path / "project_state.json")
    project = ResearchProject(
        project_id="p1",
        title="Cross-domain evidence-aware writing",
        discipline="cross-biomed-ai",
        research_questions=["How to reduce unsupported claims?"],
        sections=[SectionDraft(section_id="intro", section_name="Introduction", status="outlined")],
    )
    store.upsert_project(project)
    loaded = store.get_project("p1")
    assert loaded is not None
    assert loaded.title == "Cross-domain evidence-aware writing"
    assert loaded.sections[0].section_id == "intro"


def test_evidence_and_citation_roundtrip(tmp_path):
    evidence_store = EvidenceStore(tmp_path / "evidence.json")
    citation_registry = CitationRegistry(tmp_path / "citations.json")

    evidence_store.upsert(
        EvidenceUnit(
            evidence_id="ev1",
            evidence_type="paper_passage",
            summary="Method A improves AUROC on benchmark B.",
            source_ref="doi:10.1000/example",
        )
    )
    citation_registry.upsert(
        CitationRecord(
            citation_id="c1",
            doi="10.1000/example",
            title="Example Paper",
            authors=["A. Author"],
            year=2025,
            source="crossref",
        )
    )

    assert evidence_store.get("ev1") is not None
    assert citation_registry.get("c1") is not None


def test_claim_graph_validation_detects_missing_grounding(tmp_path):
    evidence_store = EvidenceStore(tmp_path / "evidence.json")
    citation_registry = CitationRegistry(tmp_path / "citations.json")
    claim_graph = ClaimGraph(tmp_path / "claims.json")

    claim_graph.upsert(
        Claim(
            claim_id="cl1",
            text="Our method demonstrates robust gains across all cohorts.",
            claim_type="strong",
            evidence_ids=[],
            citation_ids=[],
        )
    )
    issues = claim_graph.validate_grounding(evidence_store, citation_registry)
    assert len(issues) >= 1
    assert any(issue.severity == "error" for issue in issues)
    assert any("at least one valid data/evidence ID or citation ID" in issue.message for issue in issues)


def test_claim_graph_validation_accepts_valid_explicit_binding_tags(tmp_path):
    evidence_store = EvidenceStore(tmp_path / "evidence.json")
    citation_registry = CitationRegistry(tmp_path / "citations.json")
    claim_graph = ClaimGraph(tmp_path / "claims.json")

    evidence_store.upsert(
        EvidenceUnit(
            evidence_id="ev-explicit",
            evidence_type="raw_data",
            summary="Explicit binding evidence",
            source_ref="/tmp/ev-explicit.json",
        )
    )
    citation_registry.upsert(
        CitationRecord(
            citation_id="cit-explicit",
            doi="10.1000/explicit",
            title="Explicit citation",
            authors=["A. Author"],
            year=2024,
            source="crossref",
        )
    )
    claim_graph.upsert(
        Claim(
            claim_id="cl-explicit",
            text="Result statement [data:ev-explicit] [citation:cit-explicit].",
            claim_type="strong",
            evidence_ids=[],
            citation_ids=[],
        )
    )

    issues = claim_graph.validate_grounding(evidence_store, citation_registry)
    assert not any(issue.severity == "error" for issue in issues)
    assert not any("unknown Data ID" in issue.message for issue in issues)
    assert not any("unknown Citation ID" in issue.message for issue in issues)


def test_claim_graph_validation_flags_unknown_explicit_binding_tags(tmp_path):
    evidence_store = EvidenceStore(tmp_path / "evidence.json")
    citation_registry = CitationRegistry(tmp_path / "citations.json")
    claim_graph = ClaimGraph(tmp_path / "claims.json")

    claim_graph.upsert(
        Claim(
            claim_id="cl-unknown-tags",
            text="Unsupported binding [data:missing] [citation:missing-cit].",
            claim_type="result",
            evidence_ids=[],
            citation_ids=[],
        )
    )
    issues = claim_graph.validate_grounding(evidence_store, citation_registry)
    assert any("unknown Data ID" in issue.message for issue in issues)
    assert any("unknown Citation ID" in issue.message for issue in issues)


def test_section_compiler_downgrades_unsupported_strong_claim(tmp_path):
    evidence_store = EvidenceStore(tmp_path / "evidence.json")
    citation_registry = CitationRegistry(tmp_path / "citations.json")
    claim_graph = ClaimGraph(tmp_path / "claims.json")

    claim_graph.upsert(
        Claim(
            claim_id="cl1",
            text="This result demonstrates definitive superiority.",
            claim_type="strong",
            evidence_ids=[],
            citation_ids=[],
        )
    )
    section = SectionDraft(section_id="results", section_name="Results", claim_ids=["cl1"])
    result = SectionCompiler.compile_section(section, claim_graph, evidence_store, citation_registry, mode="strict")

    assert "insufficient data" in result.compiled_text
    assert "grounding required" in result.compiled_text
    assert "citation needed" in result.compiled_text
    assert any(issue.severity == "error" for issue in result.issues)


def test_section_compiler_injects_professor_style_narrative_templates_with_graph_bindings(tmp_path):
    evidence_store = EvidenceStore(tmp_path / "evidence.json")
    citation_registry = CitationRegistry(tmp_path / "citations.json")
    claim_graph = ClaimGraph(tmp_path / "claims.json")

    citation_registry.upsert(
        CitationRecord(
            citation_id="cit-smith",
            title="Smith et al.",
            authors=["Smith"],
            year=2019,
            source="openalex",
        )
    )
    citation_registry.upsert(
        CitationRecord(
            citation_id="cit-jones",
            title="Jones et al.",
            authors=["Jones"],
            year=2024,
            source="openalex",
        )
    )
    evidence_store.upsert(
        EvidenceUnit(
            evidence_id="graph:openalex:W1:thread1",
            evidence_type="manual_note",
            summary="Thread 1",
            source_ref="/mnt/user-data/outputs/research-writing/artifacts/ingest-openalex-W1.json",
            quote="Co-citation signal: 'Smith et al.' and 'Jones et al.' are co-cited by 6 downstream paper(s).",
            location={"kind": "citation_graph_narrative", "thread_index": 1, "source": "openalex", "external_id": "W1"},
            citation_ids=["cit-smith"],
        )
    )
    evidence_store.upsert(
        EvidenceUnit(
            evidence_id="graph:openalex:W1:thread2",
            evidence_type="manual_note",
            summary="Thread 2",
            source_ref="/mnt/user-data/outputs/research-writing/artifacts/ingest-openalex-W1.json",
            quote="Timeline: the line of work evolves from 'Smith et al.' (2019) to 'Jones et al.' (2024).",
            location={"kind": "citation_graph_narrative", "thread_index": 2, "source": "openalex", "external_id": "W1"},
            citation_ids=["cit-jones"],
        )
    )

    section = SectionDraft(
        section_id="discussion",
        section_name="Discussion",
        content="Draft discussion content.",
        evidence_ids=["graph:openalex:W1:thread1", "graph:openalex:W1:thread2"],
    )
    result = SectionCompiler.compile_section(section, claim_graph, evidence_store, citation_registry, mode="strict")

    assert "### Literature Lineage Templates" in result.compiled_text
    assert "Although Smith et al." in result.compiled_text
    assert "[data:graph:openalex:W1:thread1]" in result.compiled_text
    assert "[data:graph:openalex:W1:thread2]" in result.compiled_text
    assert "[citation:cit-smith]" in result.compiled_text or "[citation:cit-jones]" in result.compiled_text


def test_section_compiler_falls_back_to_latest_graph_narrative_units(tmp_path):
    evidence_store = EvidenceStore(tmp_path / "evidence.json")
    citation_registry = CitationRegistry(tmp_path / "citations.json")
    claim_graph = ClaimGraph(tmp_path / "claims.json")
    evidence_store.upsert(
        EvidenceUnit(
            evidence_id="graph:arxiv:2501.00001:thread1",
            evidence_type="manual_note",
            summary="Thread 1",
            source_ref="/mnt/user-data/outputs/research-writing/artifacts/ingest-arxiv-2501.00001.json",
            quote="Narrative contrast candidate: compare 'Smith et al.' with 'Jones et al.' to discuss alternative interpretations.",
            location={"kind": "citation_graph_narrative", "thread_index": 1, "source": "arxiv", "external_id": "2501.00001"},
            citation_ids=[],
        )
    )

    section = SectionDraft(section_id="related_work", section_name="Related Work", content="Background context.", evidence_ids=[])
    result = SectionCompiler.compile_section(section, claim_graph, evidence_store, citation_registry, mode="strict")
    assert "### Literature Lineage Templates" in result.compiled_text
    assert "[data:graph:arxiv:2501.00001:thread1]" in result.compiled_text


def test_section_compiler_strategy_controls_count_and_density(tmp_path):
    evidence_store = EvidenceStore(tmp_path / "evidence.json")
    citation_registry = CitationRegistry(tmp_path / "citations.json")
    claim_graph = ClaimGraph(tmp_path / "claims.json")
    citation_registry.upsert(
        CitationRecord(
            citation_id="cit-one",
            title="One citation",
            authors=["A"],
            year=2020,
            source="openalex",
        )
    )
    for idx in range(1, 4):
        evidence_store.upsert(
            EvidenceUnit(
                evidence_id=f"graph:openalex:W2:thread{idx}",
                evidence_type="manual_note",
                summary=f"Thread {idx}",
                source_ref="/mnt/user-data/outputs/research-writing/artifacts/ingest-openalex-W2.json",
                quote="Co-citation signal: 'Smith et al.' and 'Jones et al.' are co-cited by 4 downstream paper(s).",
                location={"kind": "citation_graph_narrative", "thread_index": idx, "source": "openalex", "external_id": "W2"},
                citation_ids=["cit-one"],
            )
        )

    section = SectionDraft(
        section_id="discussion",
        section_name="Discussion",
        content="Discussion draft.",
        evidence_ids=[f"graph:openalex:W2:thread{idx}" for idx in range(1, 4)],
    )
    strategy = NarrativeWritingStrategy(tone="conservative", max_templates=1, evidence_density="high")
    result = SectionCompiler.compile_section(
        section,
        claim_graph,
        evidence_store,
        citation_registry,
        mode="strict",
        narrative_strategy=strategy,
    )
    assert result.narrative_sentence_count == 1
    assert result.narrative_strategy is not None
    assert result.narrative_strategy.tone == "conservative"
    assert result.compiled_text.count("[data:graph:openalex:W2:thread") == 1
    assert any("evidence density target unmet" in issue.message.lower() for issue in result.issues)


def test_section_compiler_supports_paragraph_level_mixed_tones(tmp_path):
    evidence_store = EvidenceStore(tmp_path / "evidence.json")
    citation_registry = CitationRegistry(tmp_path / "citations.json")
    claim_graph = ClaimGraph(tmp_path / "claims.json")
    citation_registry.upsert(
        CitationRecord(
            citation_id="cit-mix",
            title="Mix citation",
            authors=["A"],
            year=2020,
            source="openalex",
        )
    )
    evidence_store.upsert(
        EvidenceUnit(
            evidence_id="graph:openalex:W4:thread1",
            evidence_type="manual_note",
            summary="Thread 1",
            source_ref="/mnt/user-data/outputs/research-writing/artifacts/ingest-openalex-W4.json",
            quote="Co-citation signal: 'Smith et al.' and 'Jones et al.' are co-cited by 4 downstream paper(s).",
            location={"kind": "citation_graph_narrative", "thread_index": 1, "source": "openalex", "external_id": "W4"},
            citation_ids=["cit-mix"],
        )
    )
    evidence_store.upsert(
        EvidenceUnit(
            evidence_id="graph:openalex:W4:thread2",
            evidence_type="manual_note",
            summary="Thread 2",
            source_ref="/mnt/user-data/outputs/research-writing/artifacts/ingest-openalex-W4.json",
            quote="Co-citation signal: 'Smith et al.' and 'Jones et al.' are co-cited by 4 downstream paper(s).",
            location={"kind": "citation_graph_narrative", "thread_index": 2, "source": "openalex", "external_id": "W4"},
            citation_ids=["cit-mix"],
        )
    )

    section = SectionDraft(
        section_id="discussion",
        section_name="Discussion",
        content="Discussion draft.",
        evidence_ids=["graph:openalex:W4:thread1", "graph:openalex:W4:thread2"],
    )
    strategy = NarrativeWritingStrategy(
        tone="balanced",
        max_templates=2,
        evidence_density="medium",
        paragraph_tones=["conservative", "aggressive"],
        paragraph_evidence_densities=["low", "high"],
    )
    result = SectionCompiler.compile_section(
        section,
        claim_graph,
        evidence_store,
        citation_registry,
        mode="strict",
        narrative_strategy=strategy,
    )
    assert "Although Smith et al. may outline one explanatory path" in result.compiled_text
    assert "strongly suggest a competing mechanism" in result.compiled_text
    assert "[citation:cit-mix]" in result.compiled_text


def test_runtime_compile_section_auto_strategy_by_target_venue(tmp_path):
    paths_instance = Paths(base_dir=tmp_path)
    thread_id = "thread_strategy"
    project_id = "p_strategy"
    section_id = "discussion"
    with patch("src.research_writing.runtime_service.get_paths", return_value=paths_instance):
        upsert_project(
            thread_id,
            ResearchProject(
                project_id=project_id,
                title="Venue-aware strategy",
                discipline="biomed",
                target_venue="Nature",
                sections=[
                    SectionDraft(
                        section_id=section_id,
                        section_name="Discussion",
                        evidence_ids=["graph:openalex:W3:thread1", "graph:openalex:W3:thread2"],
                    )
                ],
            ),
        )
        evidence_store = EvidenceStore(paths_instance.sandbox_outputs_dir(thread_id) / "research-writing" / "evidence.json")
        citation_registry = CitationRegistry(paths_instance.sandbox_outputs_dir(thread_id) / "research-writing" / "citations.json")
        citation_registry.upsert(
            CitationRecord(
                citation_id="cit-nature",
                title="Nature citation",
                authors=["N"],
                year=2023,
                source="openalex",
            )
        )
        evidence_store.upsert(
            EvidenceUnit(
                evidence_id="graph:openalex:W3:thread1",
                evidence_type="manual_note",
                summary="Thread1",
                source_ref="/mnt/user-data/outputs/research-writing/artifacts/ingest-openalex-W3.json",
                quote="Timeline: the line of work evolves from 'Smith et al.' (2019) to 'Jones et al.' (2024).",
                location={"kind": "citation_graph_narrative", "thread_index": 1, "source": "openalex", "external_id": "W3"},
                citation_ids=["cit-nature"],
            )
        )
        evidence_store.upsert(
            EvidenceUnit(
                evidence_id="graph:openalex:W3:thread2",
                evidence_type="manual_note",
                summary="Thread2",
                source_ref="/mnt/user-data/outputs/research-writing/artifacts/ingest-openalex-W3.json",
                quote="Co-citation signal: 'Smith et al.' and 'Jones et al.' are co-cited by 5 downstream paper(s).",
                location={"kind": "citation_graph_narrative", "thread_index": 2, "source": "openalex", "external_id": "W3"},
                citation_ids=["cit-nature"],
            )
        )
        payload = compile_project_section(
            thread_id,
            project_id,
            section_id,
            mode="strict",
            journal_style_enabled=False,
            policy_snapshot_auto_adjust_narrative=False,
        )

    assert payload["resolved_venue"] == "Nature"
    assert payload["narrative_strategy"]["section_type"] == "discussion"
    assert payload["narrative_strategy"]["auto_by_section_type"] is True
    assert payload["narrative_strategy"]["tone"] == "aggressive"
    assert payload["narrative_strategy"]["paragraph_tones"][:2] == ["conservative", "aggressive"]
    assert payload["narrative_strategy"]["paragraph_tones"][-1] == "balanced"
    assert payload["narrative_sentence_count"] == 2
    assert "[data:graph:openalex:W3:thread1]" in payload["compiled_text"] or "[data:graph:openalex:W3:thread2]" in payload["compiled_text"]


def test_runtime_compile_section_position_based_recommended_sequence(tmp_path):
    paths_instance = Paths(base_dir=tmp_path)
    thread_id = "thread_positioned_strategy"
    project_id = "p_positioned_strategy"
    section_id = "results"
    with patch("src.research_writing.runtime_service.get_paths", return_value=paths_instance):
        upsert_project(
            thread_id,
            ResearchProject(
                project_id=project_id,
                title="Position-aware narrative strategy",
                discipline="ai_cs",
                target_venue="NeurIPS",
                sections=[
                    SectionDraft(
                        section_id=section_id,
                        section_name="Results",
                        evidence_ids=[f"graph:openalex:W6:thread{idx}" for idx in range(1, 5)],
                    )
                ],
            ),
        )
        evidence_store = EvidenceStore(paths_instance.sandbox_outputs_dir(thread_id) / "research-writing" / "evidence.json")
        citation_registry = CitationRegistry(paths_instance.sandbox_outputs_dir(thread_id) / "research-writing" / "citations.json")
        citation_registry.upsert(
            CitationRecord(
                citation_id="cit-pos-a",
                title="Position citation A",
                authors=["A"],
                year=2022,
                source="openalex",
            )
        )
        citation_registry.upsert(
            CitationRecord(
                citation_id="cit-pos-b",
                title="Position citation B",
                authors=["B"],
                year=2023,
                source="openalex",
            )
        )
        for idx in range(1, 5):
            evidence_store.upsert(
                EvidenceUnit(
                    evidence_id=f"graph:openalex:W6:thread{idx}",
                    evidence_type="manual_note",
                    summary=f"Thread{idx}",
                    source_ref="/mnt/user-data/outputs/research-writing/artifacts/ingest-openalex-W6.json",
                    quote="Co-citation signal: 'Smith et al.' and 'Jones et al.' are co-cited by 7 downstream paper(s).",
                    location={"kind": "citation_graph_narrative", "thread_index": idx, "source": "openalex", "external_id": "W6"},
                    citation_ids=["cit-pos-a", "cit-pos-b"],
                )
            )
        payload = compile_project_section(
            thread_id,
            project_id,
            section_id,
            mode="strict",
            narrative_style="auto",
            narrative_auto_by_section_type=True,
            narrative_max_templates=4,
        )

    assert payload["narrative_strategy"]["section_type"] == "results"
    assert payload["narrative_strategy"]["paragraph_tones"] == [
        "conservative",
        "aggressive",
        "aggressive",
        "balanced",
    ]
    assert payload["narrative_strategy"]["paragraph_evidence_densities"] == [
        "medium",
        "high",
        "high",
        "medium",
    ]
    assert payload["narrative_sentence_count"] == 4


def test_runtime_compile_section_can_disable_section_type_auto_strategy(tmp_path):
    paths_instance = Paths(base_dir=tmp_path)
    thread_id = "thread_strategy_no_section_auto"
    project_id = "p_strategy_no_section_auto"
    section_id = "discussion"
    with patch("src.research_writing.runtime_service.get_paths", return_value=paths_instance):
        upsert_project(
            thread_id,
            ResearchProject(
                project_id=project_id,
                title="Venue-only strategy",
                discipline="biomed",
                target_venue="Nature",
                sections=[
                    SectionDraft(
                        section_id=section_id,
                        section_name="Discussion",
                        evidence_ids=["graph:openalex:W5:thread1", "graph:openalex:W5:thread2"],
                    )
                ],
            ),
        )
        evidence_store = EvidenceStore(paths_instance.sandbox_outputs_dir(thread_id) / "research-writing" / "evidence.json")
        citation_registry = CitationRegistry(paths_instance.sandbox_outputs_dir(thread_id) / "research-writing" / "citations.json")
        citation_registry.upsert(
            CitationRecord(
                citation_id="cit-nature-disable-auto",
                title="Nature citation",
                authors=["N"],
                year=2023,
                source="openalex",
            )
        )
        evidence_store.upsert(
            EvidenceUnit(
                evidence_id="graph:openalex:W5:thread1",
                evidence_type="manual_note",
                summary="Thread1",
                source_ref="/mnt/user-data/outputs/research-writing/artifacts/ingest-openalex-W5.json",
                quote="Timeline: the line of work evolves from 'Smith et al.' (2019) to 'Jones et al.' (2024).",
                location={"kind": "citation_graph_narrative", "thread_index": 1, "source": "openalex", "external_id": "W5"},
                citation_ids=["cit-nature-disable-auto"],
            )
        )
        evidence_store.upsert(
            EvidenceUnit(
                evidence_id="graph:openalex:W5:thread2",
                evidence_type="manual_note",
                summary="Thread2",
                source_ref="/mnt/user-data/outputs/research-writing/artifacts/ingest-openalex-W5.json",
                quote="Co-citation signal: 'Smith et al.' and 'Jones et al.' are co-cited by 5 downstream paper(s).",
                location={"kind": "citation_graph_narrative", "thread_index": 2, "source": "openalex", "external_id": "W5"},
                citation_ids=["cit-nature-disable-auto"],
            )
        )
        payload = compile_project_section(
            thread_id,
            project_id,
            section_id,
            mode="strict",
            narrative_auto_by_section_type=False,
            journal_style_enabled=False,
            policy_snapshot_auto_adjust_narrative=False,
        )

    assert payload["resolved_venue"] == "Nature"
    assert payload["narrative_strategy"]["auto_by_section_type"] is False
    assert payload["narrative_strategy"]["tone"] == "conservative"
    assert payload["narrative_sentence_count"] == 1


def test_runtime_plan_project_section_narrative_outputs_storyboard_and_questions(tmp_path):
    paths_instance = Paths(base_dir=tmp_path)
    thread_id = "thread_plan_narrative"
    project_id = "p_plan_narrative"
    section_id = "introduction"
    with patch("src.research_writing.runtime_service.get_paths", return_value=paths_instance):
        upsert_project(
            thread_id,
            ResearchProject(
                project_id=project_id,
                title="Narrative planner demo",
                discipline="ai_cs",
                target_venue="NeurIPS",
                research_questions=["How to reconcile contradictory evidence on scaling laws?"],
                sections=[
                    SectionDraft(
                        section_id=section_id,
                        section_name="Introduction",
                        content="This section introduces the unresolved debate.",
                    )
                ],
            ),
        )
        claim_graph = ClaimGraph(paths_instance.sandbox_outputs_dir(thread_id) / "research-writing" / "claims.json")
        claim_graph.upsert(
            Claim(
                claim_id="c-plan",
                text="Scaling improvements are context dependent.",
                claim_type="strong",
                evidence_ids=["graph:openalex:W9:thread1"],
                citation_ids=["cit-plan"],
            )
        )
        project_store = ResearchProjectStateStore(paths_instance.sandbox_outputs_dir(thread_id) / "research-writing" / "projects.json")
        project = project_store.get_project(project_id)
        assert project is not None
        project.sections = [
            SectionDraft(
                section_id=section_id,
                section_name="Introduction",
                content="This section introduces the unresolved debate.",
                claim_ids=["c-plan"],
                evidence_ids=["graph:openalex:W9:thread1"],
                citation_ids=["cit-plan"],
            )
        ]
        project_store.upsert_project(project)
        evidence_store = EvidenceStore(paths_instance.sandbox_outputs_dir(thread_id) / "research-writing" / "evidence.json")
        evidence_store.upsert(
            EvidenceUnit(
                evidence_id="graph:openalex:W9:thread1",
                evidence_type="manual_note",
                summary="Debate thread",
                source_ref="/mnt/user-data/outputs/research-writing/artifacts/ingest-openalex-W9.json",
                quote="Debate map: 'Paper A' supports the anchor claim, while 'Paper B' refutes it.",
                location={"kind": "literature_graph_synthesis", "thread_index": 1, "source": "openalex", "external_id": "W9"},
                citation_ids=["cit-plan"],
            )
        )
        citation_registry = CitationRegistry(paths_instance.sandbox_outputs_dir(thread_id) / "research-writing" / "citations.json")
        citation_registry.upsert(
            CitationRecord(
                citation_id="cit-plan",
                title="Planning citation",
                authors=["Author"],
                year=2024,
                source="openalex",
            )
        )
        payload = plan_project_section_narrative(
            thread_id=thread_id,
            project_id=project_id,
            section_id=section_id,
            self_question_rounds=4,
            include_storyboard=True,
        )

    assert payload["project_id"] == project_id
    assert payload["section_id"] == section_id
    assert payload["takeaway_message"]
    assert len(payload["logical_flow"]) >= 3
    assert len(payload["self_questioning"]) == 4
    assert len(payload["figure_storyboard"]) >= 1
    assert len(payload["introduction_cars"]) == 3
    assert payload["introduction_cars"][0]["move"].startswith("Move 1")
    assert len(payload["meal_outline"]) >= 1
    assert {"main_point", "evidence", "analysis", "link"}.issubset(payload["meal_outline"][0].keys())
    assert len(payload["discussion_five_layers"]) == 5
    assert payload["discussion_five_layers"][0]["layer"] == "Findings"
    assert payload["artifact_path"].startswith("/mnt/user-data/outputs/research-writing/narrative-plans/")
    assert payload["runtime_stage_context"]["operation"] == "plan_narrative"
    assert payload["runtime_stage_context"]["active_stage_ids"] == ["plan"]


def test_runtime_ingest_fulltext_persists_graph_context(tmp_path):
    paths_instance = Paths(base_dir=tmp_path)
    ingest_result = FullTextIngestResult(
        record=LiteratureRecord(
            source="arxiv",
            external_id="2501.00001",
            title="Graph-grounded manuscript writing",
            abstract="...",
            year=2025,
            url="https://arxiv.org/abs/2501.00001",
            doi="10.1234/graph",
        ),
        evidence_units=[
            EvidenceUnit(
                evidence_id="arxiv:2501.00001:p1",
                evidence_type="paper_passage",
                summary="Intro evidence",
                source_ref="https://arxiv.org/abs/2501.00001",
            )
        ],
        citation_graph=CitationGraphRag(
            seed_record_id="arxiv:2501.00001",
            nodes=[
                CitationGraphNode(node_id="S2-1", title="Seed 1", year=2022, source="semantic_scholar", doi="10.2000/seed1"),
                CitationGraphNode(node_id="S2-2", title="Seed 2", year=2024, source="semantic_scholar"),
            ],
            edges=[
                CitationGraphEdge(
                    source_id="S2-1",
                    target_id="S2-2",
                    relation="co_citation",
                    weight=3,
                    supporting_paper_ids=["CIT-X"],
                )
            ],
            narrative_threads=["Timeline: 2022 -> 2024", "Co-citation signal between Seed 1 and Seed 2"],
            sources_used=["semantic_scholar"],
        ),
        literature_graph=DynamicLiteratureGraph(
            anchor_claim_id="claim:arxiv:2501.00001:anchor",
            claims=[
                LiteratureClaimNode(
                    claim_id="claim:arxiv:2501.00001:anchor",
                    claim_text="Model generalization improves under domain shift",
                    support_paper_ids=["S2-1"],
                    refute_paper_ids=["S2-2"],
                    reconcile_paper_ids=["arxiv:2501.00001"],
                )
            ],
            edges=[
                LiteratureClaimEdge(
                    paper_id="S2-1",
                    paper_title="Seed 1",
                    claim_id="claim:arxiv:2501.00001:anchor",
                    relation="supports",
                    evidence_text="Seed 1",
                ),
                LiteratureClaimEdge(
                    paper_id="S2-2",
                    paper_title="Seed 2",
                    claim_id="claim:arxiv:2501.00001:anchor",
                    relation="refutes",
                    evidence_text="Seed 2",
                ),
            ],
            synthesis_threads=["Debate map: Seed 1 supports while Seed 2 refutes."],
            sources_used=["dynamic_literature_graph"],
        ),
    )

    with (
        patch("src.research_writing.runtime_service.get_paths", return_value=paths_instance),
        patch("src.research_writing.runtime_service.FullTextEvidenceIngestor.ingest", return_value=ingest_result),
    ):
        payload = ingest_fulltext_evidence("thread_graph", source="arxiv", external_id="2501.00001", persist=True)

    assert payload["co_citation_edge_count"] == 1
    assert len(payload["graph_evidence_ids"]) >= 1
    assert "10.1234/graph" in payload["persisted_citation_ids"]
    assert any(citation_id.startswith("s2:") for citation_id in payload["persisted_citation_ids"])
    assert any(evidence_id.startswith("graph:arxiv:2501.00001") for evidence_id in payload["persisted_evidence_ids"])
    assert payload["literature_graph_claim_count"] == 1
    assert payload["literature_graph_edge_count"] == 2
    assert payload["literature_synthesis_threads"]


def test_runtime_section_version_governance_and_traceability(tmp_path):
    paths_instance = Paths(base_dir=tmp_path)
    thread_id = "thread_version_governance"
    project_id = "p_version"
    section_id = "discussion"
    first_content = "Initial discussion with cautious interpretation."

    with patch("src.research_writing.runtime_service.get_paths", return_value=paths_instance):
        upsert_project(
            thread_id,
            ResearchProject(
                project_id=project_id,
                title="Version-governed manuscript",
                discipline="ai_cs",
                target_venue="Nature",
                sections=[
                    SectionDraft(
                        section_id=section_id,
                        section_name="Discussion",
                        status="drafting",
                        version=1,
                        content=first_content,
                    )
                ],
            ),
        )
        upsert_section(
            thread_id,
            project_id,
            SectionDraft(
                section_id=section_id,
                section_name="Discussion",
                status="drafting",
                version=1,
                content=first_content,
            ),
        )

        compile_payload = compile_project_section(
            thread_id,
            project_id,
            section_id,
            mode="strict",
            auto_peer_review=False,
            auto_hypothesis=False,
        )
        assert compile_payload["version_diff"]["schema_version"] == "deerflow.section_change_diff.v1"
        assert "triplets" in compile_payload["version_diff"]
        assert compile_payload["trace"]["trace_schema_version"] == "deerflow.section_trace.v1"
        assert compile_payload["engineering_gates"]["schema_version"] == "deerflow.engineering_gates.v1"
        assert "constraint_violation" in compile_payload["engineering_gates"]
        assert "traceability_coverage" in compile_payload["engineering_gates"]
        assert "delivery_completeness" in compile_payload["engineering_gates"]
        assert compile_payload["engineering_gate_artifact_path"].endswith(".engineering-gates.json")
        assert compile_payload["runtime_stage_context"]["operation"] == "compile_section"
        assert "plan" in compile_payload["runtime_stage_context"]["active_stage_ids"]
        assert "draft" in compile_payload["runtime_stage_context"]["active_stage_ids"]
        assert compile_payload["venue_style_adapter"]["schema_version"] == "deerflow.venue_style_adapter.v1"
        assert "control_knobs" in compile_payload["venue_style_adapter"]

        versions_payload = list_section_versions(thread_id, project_id, section_id, limit=20)
        assert versions_payload["version_schema_version"] == "deerflow.section_versions.v1"
        assert versions_payload["total_count"] >= 2
        first_version_id = str(versions_payload["versions"][0]["version_id"])

        trace_payload = get_section_traceability(thread_id, project_id, section_id)
        assert trace_payload["trace_schema_version"] == "deerflow.section_trace.v1"
        assert len(trace_payload["sentence_links"]) >= 1

        rollback_payload = rollback_section_to_version(
            thread_id,
            project_id,
            section_id,
            version_id=first_version_id,
        )
        assert rollback_payload["rolled_back_to_version_id"] == first_version_id
        assert rollback_payload["section"]["content"] == first_content


def test_runtime_engineering_gates_metrics_payload(tmp_path):
    paths_instance = Paths(base_dir=tmp_path)
    thread_id = "thread_engineering_gates"
    project_id = "p_engineering"
    section_id = "discussion"

    with patch("src.research_writing.runtime_service.get_paths", return_value=paths_instance):
        upsert_project(
            thread_id,
            ResearchProject(
                project_id=project_id,
                title="Engineering Gates Runtime",
                discipline="ai_cs",
                target_venue="Nature",
                sections=[
                    SectionDraft(
                        section_id=section_id,
                        section_name="Discussion",
                        status="drafting",
                        version=1,
                        content="This is a controlled runtime compile sample.",
                    )
                ],
            ),
        )
        compile_project_section(
            thread_id,
            project_id,
            section_id,
            mode="lenient",
            auto_peer_review=False,
            auto_hypothesis=False,
        )
        payload = get_engineering_gates_metrics(
            thread_id,
            project_id=project_id,
            run_limit=120,
            max_constraint_violation_rate=0.2,
            max_safety_valve_trigger_rate=0.4,
            max_hitl_block_rate=0.35,
            min_traceability_coverage_rate=0.8,
            min_delivery_completeness_rate=1.0,
            min_latex_success_rate=0.75,
        )

    assert payload["metrics_schema_version"] == "deerflow.engineering_gates_runtime_metrics.v1"
    assert payload["thread_id"] == thread_id
    assert payload["project_id"] == project_id
    assert payload["run_limit"] == 120
    assert isinstance(payload["compile_runs"], list)
    assert isinstance(payload["latex_runs"], list)
    assert payload["compile_summary"]["run_count"] >= 1
    assert "alerts" in payload
    assert payload["status"] in {"pass", "warn"}
