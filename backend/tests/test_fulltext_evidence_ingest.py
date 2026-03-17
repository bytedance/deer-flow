"""Tests for full-text literature ingestion and evidence extraction."""

from __future__ import annotations

from src.research_writing.fulltext_ingest import (
    CitationGraphEdge,
    CitationGraphNode,
    CitationGraphRag,
    DynamicLiteratureGraph,
    FullTextEvidenceIngestor,
    LiteratureClaimEdge,
    LiteratureClaimNode,
    LiteratureRecord,
    build_dynamic_literature_graph,
    build_citation_graph_rag,
    extract_passage_evidence,
    fetch_arxiv_record,
    fetch_openalex_record,
)


def test_preferred_sources_by_domain():
    assert FullTextEvidenceIngestor.preferred_sources("biomed") == ["pubmed", "europe_pmc"]
    assert FullTextEvidenceIngestor.preferred_sources("ai_cs") == ["openalex", "dblp", "arxiv"]


def test_extract_passage_evidence_from_structured_text():
    record = LiteratureRecord(
        source="openalex",
        external_id="W1",
        title="Example Work",
        abstract="Introduction\nA. Methods\nB.",
        year=2025,
        url="https://openalex.org/W1",
        full_text="Introduction\nThis is intro.\n\nMethods\nThis is methods.\n\nResults\nThis is results.",
    )
    items = extract_passage_evidence(record, max_units=4)
    assert len(items) >= 2
    assert all(item.evidence_type == "paper_passage" for item in items)
    assert all(item.source_ref == "https://openalex.org/W1" for item in items)


def test_fetch_openalex_record_with_mock(monkeypatch):
    payload = {
        "id": "https://openalex.org/W123",
        "title": "Structured Writing Paper",
        "publication_year": 2024,
        "doi": "https://doi.org/10.1234/abc",
        "abstract_inverted_index": {"Hello": [0], "world": [1]},
    }
    monkeypatch.setattr("src.research_writing.fulltext_ingest._http_get_json", lambda *_args, **_kwargs: payload)
    rec = fetch_openalex_record("W123")
    assert rec.external_id == "W123"
    assert rec.title == "Structured Writing Paper"
    assert rec.abstract == "Hello world"
    assert rec.doi == "10.1234/abc"


def test_fetch_arxiv_record_with_mock(monkeypatch):
    xml_payload = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2501.00001v1</id>
    <title>Evidence Grounding for Academic Writing</title>
    <summary>We propose a grounded writing framework.</summary>
    <published>2025-01-02T00:00:00Z</published>
  </entry>
</feed>
"""
    monkeypatch.setattr("src.research_writing.fulltext_ingest._http_get_text", lambda *_args, **_kwargs: xml_payload)
    rec = fetch_arxiv_record("2501.00001")
    assert rec.title == "Evidence Grounding for Academic Writing"
    assert rec.year == 2025
    assert "grounded writing framework" in rec.abstract


def test_build_citation_graph_rag_constructs_co_citation_network(monkeypatch):
    def _mock_get_json(url: str, **_kwargs):
        if "paper/search" in url:
            return {
                "data": [
                    {"paperId": "S1", "title": "Seed Paper 1", "year": 2021, "citationCount": 12},
                    {"paperId": "S2", "title": "Seed Paper 2", "year": 2023, "citationCount": 10},
                ]
            }
        if "/paper/S1?" in url:
            return {
                "paperId": "S1",
                "title": "Seed Paper 1",
                "year": 2021,
                "citationCount": 12,
                "citations": [{"paperId": "CIT-A"}, {"paperId": "CIT-B"}],
                "references": [{"paperId": "REF-1"}],
            }
        if "/paper/S2?" in url:
            return {
                "paperId": "S2",
                "title": "Seed Paper 2",
                "year": 2023,
                "citationCount": 10,
                "citations": [{"paperId": "CIT-A"}, {"paperId": "CIT-C"}],
                "references": [{"paperId": "REF-2"}],
            }
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr("src.research_writing.fulltext_ingest._http_get_json", _mock_get_json)
    record = LiteratureRecord(
        source="arxiv",
        external_id="2501.00001",
        title="A seeded graph paper",
        abstract="Graph-aware retrieval for literature review.",
        year=2025,
        url="https://arxiv.org/abs/2501.00001",
    )

    graph = build_citation_graph_rag(record, max_seed_papers=2, max_related_papers=0, max_edges=4)
    assert graph is not None
    assert len(graph.nodes) >= 2
    co_citation_edges = [edge for edge in graph.edges if edge.relation == "co_citation"]
    assert len(co_citation_edges) >= 1
    assert co_citation_edges[0].weight >= 1


def test_fulltext_ingestor_includes_citation_graph(monkeypatch):
    record = LiteratureRecord(
        source="openalex",
        external_id="W42",
        title="Dynamic Graph",
        abstract="...",
        year=2024,
        url="https://openalex.org/W42",
        doi="10.1234/demo",
    )
    graph = CitationGraphRag(
        seed_record_id="openalex:W42",
        nodes=[CitationGraphNode(node_id="openalex:W42", title="Dynamic Graph", year=2024, source="openalex")],
        edges=[CitationGraphEdge(source_id="openalex:W42", target_id="openalex:W42", relation="shared_reference", weight=1)],
        narrative_threads=["Timeline ..."],
        sources_used=["openalex"],
    )
    literature_graph = DynamicLiteratureGraph(
        anchor_claim_id="claim:openalex:W42:anchor",
        claims=[
            LiteratureClaimNode(
                claim_id="claim:openalex:W42:anchor",
                claim_text="Model A improves calibration on cohort B",
                support_paper_ids=["openalex:W42"],
            )
        ],
        edges=[
            LiteratureClaimEdge(
                paper_id="openalex:W42",
                paper_title="Dynamic Graph",
                claim_id="claim:openalex:W42:anchor",
                relation="supports",
                evidence_text="Dynamic Graph",
            )
        ],
        synthesis_threads=["Consensus thread ..."],
        sources_used=["dynamic_literature_graph"],
    )

    monkeypatch.setattr(FullTextEvidenceIngestor, "fetch_record", staticmethod(lambda _source, _external_id: record))
    monkeypatch.setattr("src.research_writing.fulltext_ingest.extract_passage_evidence", lambda _record: [])
    monkeypatch.setattr("src.research_writing.fulltext_ingest.build_citation_graph_rag", lambda _record: graph)
    monkeypatch.setattr("src.research_writing.fulltext_ingest.build_dynamic_literature_graph", lambda _record, _graph: literature_graph)

    result = FullTextEvidenceIngestor.ingest("openalex", "W42")
    assert result.citation_graph is not None
    assert result.literature_graph is not None
    assert result.citation_graph.seed_record_id == "openalex:W42"


def test_build_dynamic_literature_graph_extracts_support_refute_reconcile_threads():
    record = LiteratureRecord(
        source="arxiv",
        external_id="2501.12345",
        title="Anchor study",
        abstract="Our approach reconciles conflicting findings.",
        year=2025,
        url="https://arxiv.org/abs/2501.12345",
    )
    citation_graph = CitationGraphRag(
        seed_record_id="arxiv:2501.12345",
        nodes=[
            CitationGraphNode(node_id="P-support", title="Study supports robust improvement", year=2022, source="semantic_scholar"),
            CitationGraphNode(node_id="P-refute", title="Study refutes performance gains", year=2023, source="semantic_scholar"),
            CitationGraphNode(node_id="P-reconcile", title="Hybrid model reconciles trade-off", year=2024, source="semantic_scholar"),
        ],
        edges=[],
        narrative_threads=["Timeline context thread"],
        sources_used=["semantic_scholar"],
    )

    graph = build_dynamic_literature_graph(record, citation_graph)
    assert graph.claims
    assert graph.edges
    claim = graph.claims[0]
    assert "P-support" in claim.support_paper_ids
    assert "P-refute" in claim.refute_paper_ids
    assert "P-reconcile" in claim.reconcile_paper_ids
    assert any("Debate map" in item for item in graph.synthesis_threads)
