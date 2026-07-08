"""Build citation / provenance records from RAGFlow retrieval chunks."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple)):
        parts = [_as_text(item) for item in value]
        return "\n".join(part for part in parts if part)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value).strip()


def normalize_chunk(chunk: dict[str, Any]) -> dict[str, Any]:
    """Unify search (/datasets/search) and retrieve (/retrieval) chunk shapes."""
    normalized = dict(chunk)
    normalized.setdefault("id", chunk.get("chunk_id"))
    normalized.setdefault("document_id", chunk.get("doc_id"))
    normalized.setdefault("document_keyword", chunk.get("docnm_kwd"))
    normalized.setdefault("content", chunk.get("content_with_weight"))
    meta = chunk.get("meta_fields") or chunk.get("metadata")
    if meta:
        normalized.setdefault("meta_fields", meta)
    return normalized


def _chunk_document_name(chunk: dict[str, Any]) -> str:
    for key in (
        "document_keyword",
        "document_name",
        "doc_name",
        "docnm_kwd",
        "docnm",
    ):
        value = chunk.get(key)
        if value:
            return str(value)
    return str(chunk.get("document_id") or chunk.get("doc_id") or "unknown")


def _chunk_content(chunk: dict[str, Any]) -> str:
    for key in ("content", "content_with_weight", "highlight"):
        text = _as_text(chunk.get(key))
        if text:
            return text
    questions = chunk.get("question_kwd") or chunk.get("questions")
    text = _as_text(questions)
    if text:
        return text
    return _as_text(chunk.get("content_ltks"))


def build_citations(
    chunks: list[dict[str, Any]],
    *,
    max_content_chars: int = 800,
    max_items: int | None = None,
) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    items = chunks if max_items is None else chunks[:max_items]
    for idx, chunk in enumerate(items, start=1):
        normalized = normalize_chunk(chunk)
        content = _chunk_content(normalized)
        if len(content) > max_content_chars:
            content = content[: max_content_chars - 1] + "…"
        citations.append(
            {
                "ref": idx,
                "chunk_id": normalized.get("id") or normalized.get("chunk_id"),
                "document_id": normalized.get("document_id") or normalized.get("doc_id"),
                "document_name": _chunk_document_name(normalized),
                "similarity": normalized.get("similarity"),
                "vector_similarity": normalized.get("vector_similarity"),
                "term_similarity": normalized.get("term_similarity"),
                "content": content,
                "snippet": content,
                "highlight": normalized.get("highlight"),
                "meta_fields": normalized.get("meta_fields") or normalized.get("metadata") or {},
                "positions": normalized.get("positions") or [],
                "kb_id": normalized.get("kb_id") or normalized.get("dataset_id"),
            }
        )
    return citations


def render_citations_markdown(
    citations: list[dict[str, Any]],
    *,
    title: str = "参考来源",
    question: str = "",
) -> str:
    lines: list[str] = [f"# {title}", ""]
    if question:
        lines.extend([f"**问题**：{question}", ""])
    if not citations:
        lines.append("_未检索到可用片段。_")
        lines.append("")
        return "\n".join(lines)

    for item in citations:
        ref = item.get("ref")
        doc = item.get("document_name", "unknown")
        sim = item.get("similarity")
        sim_text = f"{sim:.4f}" if isinstance(sim, (int, float)) else "—"
        meta = item.get("meta_fields") or {}
        meta_bits = []
        if isinstance(meta, dict):
            for key in ("部门", "department", "author", "文号", "生效日期"):
                if meta.get(key):
                    meta_bits.append(f"{key}={meta[key]}")
        meta_text = " | ".join(meta_bits) if meta_bits else ""
        snippet = _as_text(item.get("snippet") or item.get("content"))

        lines.append(f"## [{ref}] {doc}")
        lines.append("")
        lines.append(f"- 相似度：`{sim_text}`")
        if item.get("chunk_id"):
            lines.append(f"- chunk_id：`{item['chunk_id']}`")
        if item.get("document_id"):
            lines.append(f"- document_id：`{item['document_id']}`")
        if meta_text:
            lines.append(f"- metadata：{meta_text}")
        lines.append("")
        lines.append("**片段正文**")
        lines.append("")
        lines.append("```text")
        lines.append(snippet or "(empty)")
        lines.append("```")
        lines.append("")

    return "\n".join(lines)


def load_retrieval_payload(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("code") != 0:
        raise ValueError(f"retrieval payload code != 0: {payload.get('message')}")
    return payload


def citations_from_retrieval_file(
    path: str | Path,
    *,
    max_content_chars: int = 800,
    max_items: int | None = None,
) -> list[dict[str, Any]]:
    payload = load_retrieval_payload(path)
    chunks = (payload.get("data") or {}).get("chunks") or []
    if chunks:
        return build_citations(
            chunks,
            max_content_chars=max_content_chars,
            max_items=max_items,
        )
    existing = payload.get("citations") or []
    if max_items is not None:
        return existing[:max_items]
    return existing


def write_citation_artifacts(
    *,
    citations: list[dict[str, Any]],
    question: str = "",
    json_out: str | Path | None = None,
    markdown_out: str | Path | None = None,
) -> None:
    if json_out:
        Path(json_out).write_text(
            json.dumps({"citations": citations}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if markdown_out:
        Path(markdown_out).write_text(
            render_citations_markdown(citations, question=question),
            encoding="utf-8",
        )
