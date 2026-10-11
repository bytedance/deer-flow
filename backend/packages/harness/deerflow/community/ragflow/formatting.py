"""Compact, citation-friendly formatting for RAGFlow retrieval results."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from deerflow.knowledge import KnowledgeCapabilities, KnowledgeSource, RetrievalHit, RetrievalResult
from deerflow.knowledge.sources import truncate as _truncate

CAPABILITIES = KnowledgeCapabilities(operations=frozenset({"search", "sources"}))


def normalize_retrieval_result(result: Mapping[str, Any], *, dataset_names_by_id: Mapping[str, str]) -> RetrievalResult:
    """Map public retrieval fields to attributable evidence, without locators."""
    aggregates = _document_aggregates(result.get("doc_aggs"))
    names = {str(item["doc_id"]): item["doc_name"] for item in aggregates if item.get("doc_id") and isinstance(item.get("doc_name"), str)}
    hits = []
    chunks = result.get("chunks")
    for chunk in chunks if isinstance(chunks, list) else []:
        if not isinstance(chunk, Mapping) or not isinstance(chunk.get("content"), str):
            continue
        content = chunk["content"].strip()
        if not content:
            continue
        title = chunk.get("document_keyword") or names.get(str(chunk.get("document_id")))
        source = None
        if isinstance(title, str) and title.strip():
            source = KnowledgeSource(provider="ragflow", title=title.strip()[:500], excerpt=content[:100_000], dataset_name=dataset_names_by_id.get(str(chunk.get("dataset_id"))))
        score = _score(chunk.get("similarity"))
        hits.append(RetrievalHit(content=content[:100_000], source=source, score=score if score is not None and math.isfinite(score) else None))
    return RetrievalResult(hits=hits)


def _document_aggregates(value: object) -> list[Mapping[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, Mapping)]
    if isinstance(value, Mapping):
        return [item for item in value.values() if isinstance(item, Mapping)]
    return []


def _score(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def format_retrieval_result(
    result: Mapping[str, Any],
    *,
    dataset_names_by_id: Mapping[str, str],
    max_chars_per_chunk: int = 800,
    max_total_chars: int = 8000,
) -> str:
    """Format one RAGFlow retrieval response into compact cited text.

    Verified against RAGFlow v0.26.4 and v0.27.0: the REST retrieval endpoint
    normalizes response chunk fields before returning them (for example,
    ``kb_id`` becomes ``dataset_id``). Only those public response field names
    are consumed, and dataset IDs are mapped back to the operator-configured
    names before anything reaches the model.
    """
    raw_chunks = result.get("chunks")
    if not isinstance(raw_chunks, list):
        raw_chunks = []
    chunks = [chunk for chunk in raw_chunks if isinstance(chunk, Mapping)]
    if not chunks:
        return "No relevant content found."

    aggregates = _document_aggregates(result.get("doc_aggs"))
    document_names_by_id = {str(item["doc_id"]): str(item["doc_name"]) for item in aggregates if item.get("doc_id") and item.get("doc_name")}

    entries: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        dataset_id = chunk.get("dataset_id")
        dataset_name = dataset_names_by_id.get(str(dataset_id), "Unknown dataset")

        document_id = chunk.get("document_id")
        document_name = chunk.get("document_keyword")
        if not document_name and document_id:
            document_name = document_names_by_id.get(str(document_id))
        document_name = str(document_name or "Unknown document")

        similarity = _score(chunk.get("similarity"))
        score_suffix = f"  (score {similarity:.2f})" if similarity is not None else ""
        content = str(chunk.get("content") or "").strip()
        content = _truncate(content, max_chars_per_chunk)
        entries.append(f"[{index}] {dataset_name} / {document_name}{score_suffix}\n{content}")

    if aggregates:
        summaries: list[str] = []
        for item in aggregates:
            name = item.get("doc_name")
            if not name:
                continue
            count = item.get("count")
            count_text = str(count) if isinstance(count, int) and not isinstance(count, bool) else "?"
            unit = "chunk" if count == 1 else "chunks"
            summaries.append(f"{name} ({count_text} {unit})")
        if summaries:
            entries.append(f"Matched documents: {', '.join(summaries)}")

    formatted = "\n\n".join(entries)
    truncation_marker = "… (response truncated)"
    if len(formatted) <= max_total_chars:
        return formatted
    if max_total_chars <= len(truncation_marker):
        return truncation_marker[:max_total_chars]
    prefix_length = max_total_chars - len(truncation_marker)
    return f"{formatted[:prefix_length].rstrip()}{truncation_marker}"
