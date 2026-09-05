"""Compact, citation-friendly formatting for LightRAG retrieval results."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _truncate(value: str, max_chars: int, *, marker: str = "…") -> str:
    if len(value) <= max_chars:
        return value
    if max_chars <= len(marker):
        return marker[:max_chars]
    return f"{value[: max_chars - len(marker)].rstrip()}{marker}"


def _chunks(value: object) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [chunk for chunk in value if isinstance(chunk, Mapping)]


def _reference_file_paths(value: object) -> dict[str, str]:
    if not isinstance(value, list):
        return {}
    file_paths: dict[str, str] = {}
    for reference in value:
        if not isinstance(reference, Mapping):
            continue
        reference_id = reference.get("reference_id")
        file_path = reference.get("file_path")
        if isinstance(reference_id, str) and isinstance(file_path, str) and file_path.strip():
            file_paths.setdefault(reference_id, file_path.strip())
    return file_paths


def format_retrieval_result(
    result: Mapping[str, Any],
    *,
    max_chars_per_chunk: int = 800,
    max_total_chars: int = 8000,
) -> str:
    """Format one LightRAG ``/query/data`` payload into compact cited text.

    The consumed field names (``chunks[].content/file_path/chunk_id/reference_id``
    and ``references[].reference_id/file_path``) are cross-checked against the
    LightRAG v1.5.7 source tree; the endpoint first shipped in v1.4.8. Opaque
    internal identifiers (``chunk_id`` and the response-local
    ``reference_id``) are never emitted; the operator-readable ``file_path``
    labels each citation instead. Entities and relationships are deliberately
    dropped: the chunks are the document text the selected query mode already
    ranked as relevant, and keeping the output compact preserves the citation
    shape shared with the RAGFlow provider.
    """
    raw_chunks = _chunks(result.get("chunks"))
    if not raw_chunks:
        return "No relevant content found."

    file_paths_by_reference = _reference_file_paths(result.get("references"))

    entries: list[str] = []
    matched_documents: list[str] = []
    counts_by_document: dict[str, int] = {}
    for index, chunk in enumerate(raw_chunks, start=1):
        file_path = chunk.get("file_path")
        if not isinstance(file_path, str) or not file_path.strip():
            reference_id = chunk.get("reference_id")
            file_path = file_paths_by_reference.get(str(reference_id)) if reference_id is not None else None
        document_name = str(file_path).strip() if file_path and str(file_path).strip() else "Unknown document"

        counts_by_document[document_name] = counts_by_document.get(document_name, 0) + 1
        content = str(chunk.get("content") or "").strip()
        content = _truncate(content, max_chars_per_chunk)
        entries.append(f"[{index}] {document_name}\n{content}")

    for document_name, count in counts_by_document.items():
        unit = "chunk" if count == 1 else "chunks"
        matched_documents.append(f"{document_name} ({count} {unit})")
    entries.append(f"Matched documents: {', '.join(matched_documents)}")

    formatted = "\n\n".join(entries)
    truncation_marker = "… (response truncated)"
    if len(formatted) <= max_total_chars:
        return formatted
    if max_total_chars <= len(truncation_marker):
        return truncation_marker[:max_total_chars]
    prefix_length = max_total_chars - len(truncation_marker)
    return f"{formatted[:prefix_length].rstrip()}{truncation_marker}"
