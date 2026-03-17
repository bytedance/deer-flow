"""Full-text literature ingestion for biomed and AI/CS domains."""

from __future__ import annotations

import json
import logging
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import combinations
from typing import Literal

from src.research_writing.evidence_store import EvidenceUnit

LiteratureDomain = Literal["biomed", "ai_cs", "cross"]
LiteratureSource = Literal["pubmed", "europe_pmc", "openalex", "dblp", "arxiv"]
ClaimStance = Literal["support", "refute", "reconcile"]

logger = logging.getLogger(__name__)


@dataclass
class LiteratureRecord:
    """Normalized literature record for downstream evidence extraction."""

    source: LiteratureSource
    external_id: str
    title: str
    abstract: str
    year: int | None
    url: str
    doi: str | None = None
    full_text: str | None = None


@dataclass
class FullTextIngestResult:
    """Output of literature ingestion and evidence extraction."""

    record: LiteratureRecord
    evidence_units: list[EvidenceUnit]
    citation_graph: CitationGraphRag | None = None
    literature_graph: DynamicLiteratureGraph | None = None


@dataclass
class CitationGraphNode:
    """One paper node in citation graph RAG."""

    node_id: str
    title: str
    year: int | None
    source: str
    doi: str | None = None
    url: str | None = None
    citation_count: int | None = None


@dataclass
class CitationGraphEdge:
    """Edge describing co-citation or shared-reference signal."""

    source_id: str
    target_id: str
    relation: Literal["co_citation", "shared_reference"]
    weight: int
    supporting_paper_ids: list[str] = field(default_factory=list)


@dataclass
class CitationGraphRag:
    """Dynamic academic graph for citation-aware RAG."""

    seed_record_id: str
    nodes: list[CitationGraphNode] = field(default_factory=list)
    edges: list[CitationGraphEdge] = field(default_factory=list)
    narrative_threads: list[str] = field(default_factory=list)
    sources_used: list[str] = field(default_factory=list)


@dataclass
class LiteratureClaimNode:
    """Claim-centric node used in dynamic literature GraphRAG."""

    claim_id: str
    claim_text: str
    support_paper_ids: list[str] = field(default_factory=list)
    refute_paper_ids: list[str] = field(default_factory=list)
    reconcile_paper_ids: list[str] = field(default_factory=list)
    representative_titles: list[str] = field(default_factory=list)


@dataclass
class LiteratureClaimEdge:
    """Paper-to-claim stance edge."""

    paper_id: str
    paper_title: str
    claim_id: str
    relation: Literal["supports", "refutes", "reconciles"]
    evidence_text: str


@dataclass
class DynamicLiteratureGraph:
    """Debate-oriented literature graph for critical synthesis writing."""

    anchor_claim_id: str
    claims: list[LiteratureClaimNode] = field(default_factory=list)
    edges: list[LiteratureClaimEdge] = field(default_factory=list)
    synthesis_threads: list[str] = field(default_factory=list)
    sources_used: list[str] = field(default_factory=list)


def _http_get_text(url: str, *, timeout: int = 15, headers: dict[str, str] | None = None) -> str:
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "DeerFlow/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def _http_get_json(url: str, *, timeout: int = 15, headers: dict[str, str] | None = None) -> dict:
    payload = _http_get_text(url, timeout=timeout, headers=headers)
    parsed = json.loads(payload)
    if not isinstance(parsed, dict):
        raise ValueError("Expected JSON object response")
    return parsed


def _safe_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _normalize_doi(raw: str | None) -> str | None:
    if not isinstance(raw, str):
        return None
    doi = raw.strip()
    if not doi:
        return None
    doi = doi.replace("https://doi.org/", "").replace("http://doi.org/", "")
    doi = doi.removeprefix("doi:")
    return doi or None


def _normalize_openalex_work_id(raw: str | None) -> str | None:
    if not isinstance(raw, str):
        return None
    value = raw.strip()
    if not value:
        return None
    if "openalex.org/" in value:
        value = value.rsplit("/", maxsplit=1)[-1]
    if value.startswith("W"):
        return value
    return None


def _parse_semantic_scholar_node(payload: dict[str, object]) -> CitationGraphNode | None:
    paper_id = payload.get("paperId")
    if not isinstance(paper_id, str) or not paper_id.strip():
        return None
    external_ids = payload.get("externalIds")
    doi = None
    if isinstance(external_ids, dict):
        doi = _normalize_doi(external_ids.get("DOI") if isinstance(external_ids.get("DOI"), str) else None)
    title = str(payload.get("title") or paper_id).strip()
    return CitationGraphNode(
        node_id=paper_id,
        title=title,
        year=_safe_int(payload.get("year")),
        source="semantic_scholar",
        doi=doi,
        url=str(payload.get("url")).strip() if isinstance(payload.get("url"), str) and str(payload.get("url")).strip() else f"https://www.semanticscholar.org/paper/{paper_id}",
        citation_count=_safe_int(payload.get("citationCount")),
    )


def _parse_openalex_node(payload: dict[str, object]) -> CitationGraphNode | None:
    node_id_raw = payload.get("id")
    openalex_work_id = _normalize_openalex_work_id(node_id_raw if isinstance(node_id_raw, str) else None)
    if not openalex_work_id:
        return None
    title = str(payload.get("title") or openalex_work_id).strip()
    doi = _normalize_doi(payload.get("doi") if isinstance(payload.get("doi"), str) else None)
    url = node_id_raw if isinstance(node_id_raw, str) else f"https://openalex.org/{openalex_work_id}"
    return CitationGraphNode(
        node_id=f"openalex:{openalex_work_id}",
        title=title,
        year=_safe_int(payload.get("publication_year")),
        source="openalex",
        doi=doi,
        url=url,
        citation_count=_safe_int(payload.get("cited_by_count")),
    )


def _search_semantic_scholar_seed_nodes(query: str, *, limit: int = 4) -> list[CitationGraphNode]:
    if not query.strip():
        return []
    endpoint = "https://api.semanticscholar.org/graph/v1/paper/search"
    params = {
        "query": query.strip(),
        "limit": str(max(1, min(limit, 8))),
        "fields": "paperId,title,year,citationCount,url,externalIds",
    }
    url = f"{endpoint}?{urllib.parse.urlencode(params)}"
    payload = _http_get_json(url)
    rows = payload.get("data")
    if not isinstance(rows, list):
        return []
    nodes: list[CitationGraphNode] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        node = _parse_semantic_scholar_node(row)
        if node is not None:
            nodes.append(node)
    return nodes


def _fetch_semantic_scholar_detail(paper_id: str) -> tuple[CitationGraphNode | None, set[str], set[str]]:
    endpoint = f"https://api.semanticscholar.org/graph/v1/paper/{urllib.parse.quote(paper_id, safe='')}"
    params = {
        "fields": (
            "paperId,title,year,citationCount,url,externalIds,"
            "citations.paperId,references.paperId"
        )
    }
    url = f"{endpoint}?{urllib.parse.urlencode(params)}"
    payload = _http_get_json(url)
    node = _parse_semantic_scholar_node(payload)
    citing_ids: set[str] = set()
    reference_ids: set[str] = set()

    citations = payload.get("citations")
    if isinstance(citations, list):
        for item in citations:
            if not isinstance(item, dict):
                continue
            cid = item.get("paperId")
            if isinstance(cid, str) and cid.strip():
                citing_ids.add(cid.strip())

    references = payload.get("references")
    if isinstance(references, list):
        for item in references:
            if not isinstance(item, dict):
                continue
            rid = item.get("paperId")
            if isinstance(rid, str) and rid.strip():
                reference_ids.add(rid.strip())
    return node, citing_ids, reference_ids


def _fetch_openalex_related_nodes(record: LiteratureRecord, *, limit: int = 6) -> list[CitationGraphNode]:
    if record.source != "openalex":
        return []
    work_id = _normalize_openalex_work_id(record.external_id) or _normalize_openalex_work_id(record.url)
    if not work_id:
        return []

    root_payload = _http_get_json(f"https://api.openalex.org/works/{urllib.parse.quote(work_id, safe='')}")
    related_ids = root_payload.get("related_works")
    if not isinstance(related_ids, list):
        return []

    nodes: list[CitationGraphNode] = []
    for raw_related in related_ids[: max(1, min(limit, 12))]:
        if not isinstance(raw_related, str):
            continue
        related_work_id = _normalize_openalex_work_id(raw_related)
        if not related_work_id:
            continue
        try:
            payload = _http_get_json(f"https://api.openalex.org/works/{urllib.parse.quote(related_work_id, safe='')}")
        except Exception:
            continue
        parsed = _parse_openalex_node(payload)
        if parsed is not None:
            nodes.append(parsed)
    return nodes


def _build_narrative_threads(record: LiteratureRecord, nodes: list[CitationGraphNode], edges: list[CitationGraphEdge]) -> list[str]:
    threads: list[str] = []
    dated = sorted((node for node in nodes if node.year is not None), key=lambda item: item.year or 0)
    if len(dated) >= 2:
        earliest = dated[0]
        latest = dated[-1]
        if earliest.node_id != latest.node_id:
            threads.append(
                f"Timeline: the line of work evolves from '{earliest.title}' ({earliest.year}) "
                f"to '{latest.title}' ({latest.year})."
            )

    strongest_edge = max(edges, key=lambda item: item.weight, default=None)
    if strongest_edge is not None and strongest_edge.weight > 0:
        node_map = {node.node_id: node for node in nodes}
        source = node_map.get(strongest_edge.source_id)
        target = node_map.get(strongest_edge.target_id)
        if source is not None and target is not None:
            if strongest_edge.relation == "co_citation":
                threads.append(
                    f"Co-citation signal: '{source.title}' and '{target.title}' are co-cited by "
                    f"{strongest_edge.weight} downstream paper(s)."
                )
            else:
                threads.append(
                    f"Shared-reference signal: '{source.title}' and '{target.title}' reuse "
                    f"{strongest_edge.weight} reference(s)."
                )

    comparator = next((node for node in nodes if node.title and node.title != record.title), None)
    if comparator is not None:
        threads.append(
            f"Narrative contrast candidate: compare '{record.title}' with '{comparator.title}' "
            "to discuss alternative interpretations."
        )
    return threads[:3]


_SUPPORT_KEYWORDS = (
    "support",
    "improv",
    "outperform",
    "effective",
    "benefit",
    "increase",
    "enhance",
    "promot",
    "robust",
)
_REFUTE_KEYWORDS = (
    "refut",
    "contradict",
    "challenge",
    "fail",
    "ineffective",
    "null",
    "no effect",
    "negative",
    "not ",
)
_RECONCILE_KEYWORDS = (
    "reconcile",
    "bridge",
    "integrat",
    "hybrid",
    "unif",
    "context-dependent",
    "trade-off",
    "heterogeneous",
)


def _split_sentences(text: str) -> list[str]:
    if not text.strip():
        return []
    chunks = re.split(r"(?<=[.!?。！？])\s+", text.strip())
    return [chunk.strip() for chunk in chunks if chunk.strip()]


def _extract_anchor_claim(record: LiteratureRecord) -> str:
    sentences = _split_sentences(record.abstract or "")
    for sentence in sentences:
        if len(sentence.split()) >= 5:
            return sentence.rstrip(".。")
    title = (record.title or "").strip()
    if title:
        return f"{title} defines the central claim trajectory."
    return f"The study {record.source}:{record.external_id} defines the central claim trajectory."


def _infer_claim_stance(text: str) -> ClaimStance:
    lowered = text.lower()
    if any(token in lowered for token in _RECONCILE_KEYWORDS):
        return "reconcile"
    if any(token in lowered for token in _REFUTE_KEYWORDS):
        return "refute"
    if any(token in lowered for token in _SUPPORT_KEYWORDS):
        return "support"
    return "support"


def build_dynamic_literature_graph(
    record: LiteratureRecord,
    citation_graph: CitationGraphRag | None,
    *,
    max_threads: int = 4,
) -> DynamicLiteratureGraph:
    """Build a claim-centric literature debate map (support/refute/reconcile)."""
    anchor_claim = _extract_anchor_claim(record)
    anchor_claim_id = f"claim:{record.source}:{record.external_id}:anchor"
    claim_node = LiteratureClaimNode(
        claim_id=anchor_claim_id,
        claim_text=anchor_claim,
    )
    edges: list[LiteratureClaimEdge] = []

    candidate_nodes = list(citation_graph.nodes) if citation_graph is not None else []
    for node in candidate_nodes:
        paper_id = str(node.node_id or "").strip()
        title = str(node.title or "").strip()
        if not paper_id or not title:
            continue
        stance = _infer_claim_stance(title)
        if stance == "support":
            relation: Literal["supports", "refutes", "reconciles"] = "supports"
        elif stance == "refute":
            relation = "refutes"
        else:
            relation = "reconciles"
        edges.append(
            LiteratureClaimEdge(
                paper_id=paper_id,
                paper_title=title,
                claim_id=anchor_claim_id,
                relation=relation,
                evidence_text=title,
            )
        )
        if stance == "support":
            claim_node.support_paper_ids.append(paper_id)
        elif stance == "refute":
            claim_node.refute_paper_ids.append(paper_id)
        else:
            claim_node.reconcile_paper_ids.append(paper_id)
        if title not in claim_node.representative_titles:
            claim_node.representative_titles.append(title)

    if not edges:
        fallback_id = f"{record.source}:{record.external_id}"
        fallback_title = (record.title or fallback_id).strip()
        claim_node.reconcile_paper_ids.append(fallback_id)
        claim_node.representative_titles.append(fallback_title)
        edges.append(
            LiteratureClaimEdge(
                paper_id=fallback_id,
                paper_title=fallback_title,
                claim_id=anchor_claim_id,
                relation="reconciles",
                evidence_text=anchor_claim,
            )
        )

    synthesis_threads: list[str] = []
    if claim_node.support_paper_ids and claim_node.refute_paper_ids:
        support_title = claim_node.representative_titles[0]
        refute_title = claim_node.representative_titles[min(1, len(claim_node.representative_titles) - 1)]
        synthesis_threads.append(
            f"Debate map: '{support_title}' supports the anchor claim, while '{refute_title}' refutes it."
        )
        synthesis_threads.append(
            f"Synthesis route: our study can reconcile this conflict by boundary conditions around '{anchor_claim}'."
        )
    elif claim_node.support_paper_ids:
        exemplar = claim_node.representative_titles[0]
        synthesis_threads.append(
            f"Consensus thread: '{exemplar}' supports '{anchor_claim}', indicating an aligned literature front."
        )
    elif claim_node.refute_paper_ids:
        exemplar = claim_node.representative_titles[0]
        synthesis_threads.append(
            f"Contrarian thread: '{exemplar}' challenges '{anchor_claim}', requiring explicit reconciliation."
        )
    if citation_graph is not None:
        for thread in citation_graph.narrative_threads:
            if isinstance(thread, str) and thread.strip():
                synthesis_threads.append(f"Graph context: {thread.strip()}")

    sources_used = list(citation_graph.sources_used) if citation_graph is not None else []
    if "dynamic_literature_graph" not in sources_used:
        sources_used.append("dynamic_literature_graph")
    return DynamicLiteratureGraph(
        anchor_claim_id=anchor_claim_id,
        claims=[claim_node],
        edges=edges,
        synthesis_threads=synthesis_threads[: max(1, min(max_threads, 8))],
        sources_used=sources_used,
    )


def build_citation_graph_rag(
    record: LiteratureRecord,
    *,
    max_seed_papers: int = 4,
    max_related_papers: int = 6,
    max_edges: int = 8,
) -> CitationGraphRag | None:
    """Build citation-graph RAG context (including co-citation links)."""
    query = (record.title or "").strip() or (record.abstract or "").strip()
    if not query:
        return None

    sources_used: list[str] = []
    seed_nodes = _search_semantic_scholar_seed_nodes(query, limit=max_seed_papers)
    if seed_nodes:
        sources_used.append("semantic_scholar")

    node_map: dict[str, CitationGraphNode] = {node.node_id: node for node in seed_nodes}
    citing_to_seed: dict[str, set[str]] = defaultdict(set)
    reference_to_seed: dict[str, set[str]] = defaultdict(set)

    for node in seed_nodes:
        try:
            detailed_node, citing_ids, reference_ids = _fetch_semantic_scholar_detail(node.node_id)
        except Exception as exc:
            logger.debug("Failed to fetch Semantic Scholar detail for '%s': %s", node.node_id, exc)
            continue
        if detailed_node is not None:
            node_map[detailed_node.node_id] = detailed_node
        for citing_id in citing_ids:
            citing_to_seed[citing_id].add(node.node_id)
        for ref_id in reference_ids:
            reference_to_seed[ref_id].add(node.node_id)

    try:
        related_nodes = _fetch_openalex_related_nodes(record, limit=max_related_papers)
    except Exception as exc:
        related_nodes = []
        logger.debug("Failed to fetch OpenAlex related works for '%s': %s", record.external_id, exc)
    if related_nodes:
        sources_used.append("openalex")
        for node in related_nodes:
            node_map.setdefault(node.node_id, node)

    seed_record_id = f"{record.source}:{record.external_id}"
    anchor_node = CitationGraphNode(
        node_id=seed_record_id,
        title=record.title,
        year=record.year,
        source=record.source,
        doi=_normalize_doi(record.doi),
        url=record.url,
        citation_count=None,
    )
    node_map.setdefault(seed_record_id, anchor_node)

    pair_to_edge: dict[tuple[str, str], CitationGraphEdge] = {}
    for citing_id, seed_ids in citing_to_seed.items():
        if len(seed_ids) < 2:
            continue
        for source_id, target_id in combinations(sorted(seed_ids), 2):
            key = (source_id, target_id)
            edge = pair_to_edge.get(key)
            if edge is None:
                edge = CitationGraphEdge(source_id=source_id, target_id=target_id, relation="co_citation", weight=0)
                pair_to_edge[key] = edge
            edge.weight += 1
            if len(edge.supporting_paper_ids) < 12:
                edge.supporting_paper_ids.append(citing_id)

    edges: list[CitationGraphEdge] = sorted(pair_to_edge.values(), key=lambda item: item.weight, reverse=True)
    if not edges:
        for reference_id, seed_ids in reference_to_seed.items():
            if len(seed_ids) < 2:
                continue
            for source_id, target_id in combinations(sorted(seed_ids), 2):
                key = (source_id, target_id)
                edge = pair_to_edge.get(key)
                if edge is None:
                    edge = CitationGraphEdge(source_id=source_id, target_id=target_id, relation="shared_reference", weight=0)
                    pair_to_edge[key] = edge
                edge.weight += 1
                if len(edge.supporting_paper_ids) < 12:
                    edge.supporting_paper_ids.append(reference_id)
        edges = sorted(
            (edge for edge in pair_to_edge.values() if edge.relation == "shared_reference"),
            key=lambda item: item.weight,
            reverse=True,
        )
    edges = edges[: max(1, min(max_edges, 20))]

    nodes_sorted = sorted(
        node_map.values(),
        key=lambda item: (item.node_id != seed_record_id, -(item.citation_count or -1), item.title.lower()),
    )
    node_limit = max(8, max_seed_papers + max_related_papers + 1)
    nodes = nodes_sorted[:node_limit]
    allowed_node_ids = {node.node_id for node in nodes}
    edges = [edge for edge in edges if edge.source_id in allowed_node_ids and edge.target_id in allowed_node_ids]

    if not nodes:
        return None

    narrative_threads = _build_narrative_threads(record, nodes, edges)
    return CitationGraphRag(
        seed_record_id=seed_record_id,
        nodes=nodes,
        edges=edges,
        narrative_threads=narrative_threads,
        sources_used=sources_used,
    )


def _chunk_full_text(full_text: str) -> list[tuple[str, str]]:
    """Chunk full text by major section headings."""
    normalized = full_text.strip()
    if not normalized:
        return []
    pattern = re.compile(r"(?im)^(abstract|introduction|methods?|materials and methods|results?|discussion|conclusion|limitations)\s*$")
    matches = list(pattern.finditer(normalized))
    if not matches:
        return [("body", normalized)]

    chunks: list[tuple[str, str]] = []
    for idx, match in enumerate(matches):
        section_name = match.group(1).lower()
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(normalized)
        text = normalized[start:end].strip()
        if text:
            chunks.append((section_name, text))
    return chunks or [("body", normalized)]


def extract_passage_evidence(record: LiteratureRecord, *, max_units: int = 8) -> list[EvidenceUnit]:
    """Convert literature full text/abstract into passage-level evidence units."""
    base_text = record.full_text or record.abstract
    chunks = _chunk_full_text(base_text)
    evidence_units: list[EvidenceUnit] = []

    for idx, (section, text) in enumerate(chunks[:max_units], start=1):
        snippet = text[:800].strip()
        if not snippet:
            continue
        evidence_units.append(
            EvidenceUnit(
                evidence_id=f"{record.source}:{record.external_id}:p{idx}",
                evidence_type="paper_passage",
                summary=f"{section.title()} evidence from {record.title}",
                source_ref=record.url,
                quote=snippet,
                location={"section": section, "source": record.source, "external_id": record.external_id},
                citation_ids=[record.doi] if record.doi else [],
                confidence=0.9 if record.full_text else 0.75,
                metadata={"title": record.title, "year": record.year, "doi": record.doi},
            )
        )
    return evidence_units


def fetch_pubmed_record(pmid: str) -> LiteratureRecord:
    """Fetch PubMed summary + abstract."""
    summary_url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
        f"?db=pubmed&id={urllib.parse.quote(pmid)}&retmode=json"
    )
    summary = _http_get_json(summary_url)
    result = summary.get("result", {})
    item = result.get(str(pmid), {})
    title = item.get("title") or f"PubMed {pmid}"
    pubdate = str(item.get("pubdate") or "")
    year_match = re.search(r"\b(19|20)\d{2}\b", pubdate)
    year = int(year_match.group(0)) if year_match else None
    article_ids = item.get("articleids") or []
    doi = next((i.get("value") for i in article_ids if i.get("idtype") == "doi"), None)

    abstract_url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
        f"?db=pubmed&id={urllib.parse.quote(pmid)}&retmode=xml"
    )
    xml_text = _http_get_text(abstract_url)
    root = ET.fromstring(xml_text)
    abstract_nodes = root.findall(".//AbstractText")
    abstract = " ".join((node.text or "").strip() for node in abstract_nodes if (node.text or "").strip())

    return LiteratureRecord(
        source="pubmed",
        external_id=pmid,
        title=title,
        abstract=abstract,
        year=year,
        url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        doi=doi,
        full_text=None,
    )


def fetch_europe_pmc_record(pmcid: str) -> LiteratureRecord:
    """Fetch Europe PMC record with full text when available."""
    api_url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{urllib.parse.quote(pmcid)}/fullTextXML"
    xml_text = _http_get_text(api_url)
    root = ET.fromstring(xml_text)

    title = (root.findtext(".//article-title") or root.findtext(".//title") or pmcid).strip()
    abstract_nodes = root.findall(".//abstract//p")
    abstract = " ".join((node.text or "").strip() for node in abstract_nodes if (node.text or "").strip())
    body_nodes = root.findall(".//body//p")
    full_text = "\n\n".join((node.text or "").strip() for node in body_nodes if (node.text or "").strip())

    year_text = root.findtext(".//pub-date/year")
    year = int(year_text) if year_text and year_text.isdigit() else None
    doi = root.findtext(".//article-id[@pub-id-type='doi']")

    return LiteratureRecord(
        source="europe_pmc",
        external_id=pmcid,
        title=title,
        abstract=abstract,
        year=year,
        url=f"https://europepmc.org/article/PMC/{pmcid}",
        doi=doi,
        full_text=full_text or None,
    )


def fetch_openalex_record(work_id: str) -> LiteratureRecord:
    """Fetch OpenAlex work metadata (AI/CS friendly)."""
    api_url = f"https://api.openalex.org/works/{urllib.parse.quote(work_id)}"
    payload = _http_get_json(api_url)
    title = (payload.get("title") or work_id).strip()
    abstract_inv = payload.get("abstract_inverted_index") or {}
    if isinstance(abstract_inv, dict) and abstract_inv:
        words = []
        max_idx = max((max(v) for v in abstract_inv.values() if isinstance(v, list)), default=-1)
        arr = [""] * (max_idx + 1)
        for word, idxs in abstract_inv.items():
            if not isinstance(idxs, list):
                continue
            for i in idxs:
                if isinstance(i, int) and 0 <= i < len(arr):
                    arr[i] = word
        words = [w for w in arr if w]
        abstract = " ".join(words)
    else:
        abstract = ""
    year = payload.get("publication_year")
    doi = payload.get("doi")

    return LiteratureRecord(
        source="openalex",
        external_id=work_id,
        title=title,
        abstract=abstract,
        year=int(year) if isinstance(year, int) else None,
        url=payload.get("id") or f"https://openalex.org/{work_id}",
        doi=doi.replace("https://doi.org/", "") if isinstance(doi, str) else None,
        full_text=None,
    )


def fetch_dblp_record(dblp_key: str) -> LiteratureRecord:
    """Fetch DBLP publication metadata."""
    api_url = f"https://dblp.org/rec/{urllib.parse.quote(dblp_key)}.xml"
    xml_text = _http_get_text(api_url)
    root = ET.fromstring(xml_text)
    title = (root.findtext(".//title") or dblp_key).strip()
    year_text = root.findtext(".//year")
    year = int(year_text) if year_text and year_text.isdigit() else None
    ee = root.findtext(".//ee") or ""
    doi = None
    if "doi.org/" in ee:
        doi = ee.split("doi.org/")[-1]
    return LiteratureRecord(
        source="dblp",
        external_id=dblp_key,
        title=title,
        abstract="",
        year=year,
        url=ee or f"https://dblp.org/rec/{dblp_key}",
        doi=doi,
        full_text=None,
    )


def fetch_arxiv_record(arxiv_id: str) -> LiteratureRecord:
    """Fetch arXiv record with abstract."""
    api_url = f"http://export.arxiv.org/api/query?id_list={urllib.parse.quote(arxiv_id)}"
    xml_text = _http_get_text(api_url)
    root = ET.fromstring(xml_text)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    entry = root.find("atom:entry", ns)
    if entry is None:
        raise ValueError(f"arXiv record not found for '{arxiv_id}'")
    title = (entry.findtext("atom:title", default="", namespaces=ns) or arxiv_id).strip()
    summary = (entry.findtext("atom:summary", default="", namespaces=ns) or "").strip()
    published = entry.findtext("atom:published", default="", namespaces=ns)
    year = int(published[:4]) if len(published) >= 4 and published[:4].isdigit() else None
    url = f"https://arxiv.org/abs/{arxiv_id}"
    return LiteratureRecord(
        source="arxiv",
        external_id=arxiv_id,
        title=title,
        abstract=summary,
        year=year,
        url=url,
        doi=None,
        full_text=None,
    )


class FullTextEvidenceIngestor:
    """Domain-aware ingestion orchestrator for biomed and AI/CS."""

    @staticmethod
    def fetch_record(source: LiteratureSource, external_id: str) -> LiteratureRecord:
        if source == "pubmed":
            return fetch_pubmed_record(external_id)
        if source == "europe_pmc":
            return fetch_europe_pmc_record(external_id)
        if source == "openalex":
            return fetch_openalex_record(external_id)
        if source == "dblp":
            return fetch_dblp_record(external_id)
        if source == "arxiv":
            return fetch_arxiv_record(external_id)
        raise ValueError(f"Unsupported source: {source}")

    @staticmethod
    def preferred_sources(domain: LiteratureDomain) -> list[LiteratureSource]:
        if domain == "biomed":
            return ["pubmed", "europe_pmc"]
        if domain == "ai_cs":
            return ["openalex", "dblp", "arxiv"]
        return ["pubmed", "europe_pmc", "openalex", "dblp", "arxiv"]

    @classmethod
    def ingest(cls, source: LiteratureSource, external_id: str) -> FullTextIngestResult:
        record = cls.fetch_record(source, external_id)
        evidence = extract_passage_evidence(record)
        citation_graph: CitationGraphRag | None = None
        literature_graph: DynamicLiteratureGraph | None = None
        try:
            citation_graph = build_citation_graph_rag(record)
        except Exception as exc:
            logger.debug("Citation graph RAG build failed for '%s:%s': %s", source, external_id, exc)
        try:
            literature_graph = build_dynamic_literature_graph(record, citation_graph)
        except Exception as exc:
            logger.debug("Dynamic literature graph build failed for '%s:%s': %s", source, external_id, exc)
        return FullTextIngestResult(
            record=record,
            evidence_units=evidence,
            citation_graph=citation_graph,
            literature_graph=literature_graph,
        )
