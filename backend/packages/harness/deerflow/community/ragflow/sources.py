"""Bounded source-artifact forwarding across ordinary subagent results."""

import re
from collections.abc import Mapping
from typing import Any


def budget_source_artifact(content: str, artifact: object, max_chars: int, *, summary: str = "") -> tuple[str, dict[str, Any] | None] | None:
    """Keep whole evidence records and their links together within a tool budget.

    Never shorten an excerpt under its existing source ID: those IDs also occur
    in persisted child messages. Oversized records are omitted atomically, and
    unrelated artifact fields survive. A task result can retain a short synopsis
    before the evidence; its old knowledge links are replaced by retained ones.
    """
    if not isinstance(artifact, dict) or max_chars <= 0:
        return None
    payload = artifact.get("knowledge_sources")
    if not isinstance(payload, dict) or payload.get("version") != 1 or not isinstance(payload.get("sources"), list):
        return None
    sources = []
    seen = set()
    for source in payload["sources"][:100]:
        if not isinstance(source, dict):
            continue
        source_id = source.get("id")
        if not isinstance(source_id, str) or not re.fullmatch(r"[a-f0-9]{32}-[1-9][0-9]{0,2}", source_id):
            continue
        if source_id in seen or f"](#knowledge-{source_id})" not in content:
            continue
        if source.get("provider") != "ragflow" or not all(isinstance(source.get(field), str) for field in ("text", "dataset_name", "document_name")):
            continue
        seen.add(source_id)
        sources.append(source)
    if not sources:
        return None

    notice = "Knowledge sources omitted to fit output budget; request smaller excerpts."
    # Remove old destinations before shortening the report, including any link
    # fragments left by the generic synopsis/truncation transform.
    summary = re.sub(r"\[([^\]\n]*)\]\(#(?:user-content-)?knowledge-[^)\s]*\)", r"\1", summary)
    summary = re.sub(r"#(?:user-content-)?knowledge-[\w-]*", "", summary)
    summary_limit = min(1000, max_chars // 4) if max_chars >= 160 else 0
    if not summary_limit:
        summary = ""
    elif len(summary) > summary_limit:
        # Keep the synopsis tail too: it can contain the read_file reference
        # for the full externalized task report.
        head = (summary_limit - 3) // 2
        summary = summary[:head] + "\n…\n" + summary[-(summary_limit - head - 3) :]
    summary = summary.rstrip()
    entries = [summary] if summary else []
    used = len(summary)
    retained = []
    for source in sources:
        entry = f"[citation:{len(retained) + 1}](#knowledge-{source['id']}) {source['dataset_name']} / {source['document_name']}\n{source['text']}"
        cost = len(entry) + (2 if entries else 0)
        # Reserve a complete omission notice; never emit a partial source link.
        if used + cost + len(notice) + 2 > max_chars:
            continue
        entries.append(entry)
        used += cost
        retained.append(source)
    if len(retained) != len(sources):
        entries.append(notice[:max_chars])
    updated = dict(artifact)
    if retained:
        updated["knowledge_sources"] = {**payload, "sources": retained}
    else:
        updated.pop("knowledge_sources", None)
    return "\n\n".join(entries), updated or None


def cited_source_artifact(messages: list[dict[str, Any]], content: str) -> dict[str, Any] | None:
    """Carry only actual captured sources cited in the child's final result."""
    sources: dict[str, dict[str, Any]] = {}
    remaining = 1_000_000
    for message in messages:
        if message.get("type") != "tool" or message.get("name") not in {"knowledge_search", "task"}:
            continue
        artifact = message.get("artifact")
        payload = artifact.get("knowledge_sources") if isinstance(artifact, Mapping) else None
        if not isinstance(payload, Mapping) or payload.get("version") != 1:
            continue
        raw_sources = payload.get("sources")
        if not isinstance(raw_sources, list):
            continue
        for source in raw_sources[:100]:
            if not isinstance(source, dict):
                continue
            source_id = source.get("id")
            text = source.get("text")
            if not isinstance(source_id, str) or not isinstance(text, str) or f"](#knowledge-{source_id})" not in content:
                continue
            if source_id in sources:
                continue
            if len(sources) >= 100 or len(text) > remaining:
                continue
            sources[source_id] = dict(source)
            remaining -= len(text)
    return {"knowledge_sources": {"version": 1, "sources": list(sources.values())}} if sources else None
