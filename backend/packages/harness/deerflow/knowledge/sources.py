"""Shared validation, evidence-preserving budgets, and delegation forwarding."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from pydantic import ValidationError

from .contract import KnowledgeSource, RetrievalResult

ARTIFACT_VERSION = 1
TRUNCATION_MARKER = "… (response truncated)"


def redact_strings(value: Any, secret: str | None) -> Any:
    """Redact before normalization so text and artifact never expose secrets."""
    if isinstance(value, str):
        return value.replace(secret, "[REDACTED]") if secret else value
    if isinstance(value, Mapping):
        return {key: redact_strings(item, secret) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_strings(item, secret) for item in value]
    return value


def strip_source_artifact(artifact: Any) -> Any:
    """Remove only server-owned evidence keys from untrusted writes."""
    if isinstance(artifact, Mapping) and ("knowledge_sources" in artifact or "knowledge_sources_version" in artifact or "retrieval_sources" in artifact):
        return {key: value for key, value in artifact.items() if key not in {"knowledge_sources", "knowledge_sources_version", "retrieval_sources"}}
    return artifact


def prune_sources(content: str, artifact: Any) -> tuple[str, Any]:
    """Budget transformations retain only evidence still visible to the model."""
    if not isinstance(artifact, Mapping) or artifact.get("knowledge_sources_version") != ARTIFACT_VERSION:
        return content, artifact
    sources = sources_from_messages([{"type": "tool", "content": content, "artifact": artifact}])
    allowed = {source.id for source in sources}
    pattern = r"\[citation:((?:\\.|[^\]\\])*)\]\(#knowledge-source-([a-f0-9]{32})\)"
    content = re.sub(pattern, lambda match: match[0] if match[2] in allowed else match[1], content)
    if "retrieval_sources" in artifact:
        return content, {**artifact, "retrieval_sources": [source.model_dump(mode="json", exclude_none=True) for source in sources]}
    return content, {**artifact, **source_artifact(sources)}


def truncate(value: str, max_chars: int, *, marker: str = "…") -> str:
    max_chars = max(0, max_chars)
    if len(value) <= max_chars:
        return value
    if max_chars <= len(marker):
        return marker[:max_chars]
    return f"{value[: max_chars - len(marker)].rstrip()}{marker}"


def source_artifact(sources: Iterable[KnowledgeSource]) -> dict[str, Any]:
    return {"knowledge_sources_version": ARTIFACT_VERSION, "knowledge_sources": [source.model_dump(mode="json", exclude_none=True) for source in sources]}


def citation(source: KnowledgeSource) -> str:
    # Escape labels before inserting provider-controlled titles into markdown.
    title = source.title.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]").replace("\n", " ")
    return f"[citation:{title}](#knowledge-source-{source.id})"


def format_result(result: RetrievalResult, *, max_chars_per_chunk: int = 800, max_total_chars: int = 8000) -> tuple[str, dict[str, Any]]:
    """Budget text and its evidence together; never cut a citation in half."""
    entries: list[str] = []
    sources: list[KnowledgeSource] = []
    used_chars = 0
    budget = max(0, max_total_chars)
    truncated = False
    for index, hit in enumerate(result.hits, 1):
        if index > 100:
            truncated = True
            break  # Match the bounded artifact readers and delegation ledger.
        content = truncate(hit.content.strip(), max_chars_per_chunk)
        if not content:
            continue
        source = hit.source
        # Evidence must be from this hit. Adapters cannot attach unrelated text.
        if source is not None and source.excerpt != hit.content.strip():
            source = None
        if content == "…" and len(hit.content.strip()) > len(content):
            source = None  # A truncation marker alone is not retrieved evidence.
        if source is not None:
            source = KnowledgeSource.model_validate({**source.model_dump(exclude={"id"}), "excerpt": content})
        header = f"[{index}] {citation(source) if source else 'Unattributed content'}\n"
        separator = "\n\n" if entries else ""
        remaining = budget - used_chars - len(separator)
        entry = header + content
        if len(entry) > remaining:
            # Drop the entire hit when it cannot fit with real evidence. This
            # keeps the stable source identity independent of total budget.
            truncated = True
            break
        entries.append(separator + entry)
        used_chars += len(separator) + len(entry)
        if source is not None:
            sources.append(source)
    text = "".join(entries)
    if truncated:
        remaining = budget - len(text)
        text += truncate(TRUNCATION_MARKER, remaining, marker="")
    elif not text:
        text = truncate("No relevant content found.", budget, marker="")
    return text, source_artifact(sources)


def sources_from_messages(messages: Iterable[Any]) -> list[KnowledgeSource]:
    """Accept native and serialized ToolMessages, never assistant claims.

    Child values accumulation scans changed message suffixes and retains bounded
    evidence across compaction. Replay deduplicates by evidence identity.
    """
    sources: dict[str, KnowledgeSource] = {}
    for message in messages:
        if isinstance(message, Mapping):
            kind, artifact, content = message.get("type"), message.get("artifact"), message.get("content")
        else:
            kind, artifact, content = getattr(message, "type", None), getattr(message, "artifact", None), getattr(message, "content", None)
        if kind != "tool" or not isinstance(content, str) or not isinstance(artifact, Mapping) or type(artifact.get("knowledge_sources_version")) is not int or artifact.get("knowledge_sources_version") != ARTIFACT_VERSION:
            continue
        raw_sources = artifact.get("knowledge_sources") if isinstance(artifact.get("knowledge_sources"), list) else artifact.get("retrieval_sources")
        if not isinstance(raw_sources, list):
            continue
        for raw in raw_sources[:100]:
            try:
                source = KnowledgeSource.model_validate(raw)
            except (ValidationError, TypeError):
                continue
            if not isinstance(raw, Mapping) or raw.get("id") != source.id:
                continue
            if source.excerpt in content and f"#knowledge-source-{source.id}" in content:
                sources[source.id] = source
    return list(sources.values())[-100:]


def forward_sources(report: str, raw_sources: Iterable[Any], *, max_total_chars: int = 8000) -> tuple[str, dict[str, Any]]:
    """Forward only citations backed by child tool evidence, with excerpts."""
    hits = []
    from .contract import RetrievalHit

    for raw in raw_sources:
        try:
            source = KnowledgeSource.model_validate(raw)
        except (ValidationError, TypeError):
            continue
        if isinstance(raw, Mapping) and raw.get("id") == source.id and f"#knowledge-source-{source.id}" in report:
            hits.append(RetrievalHit(content=source.excerpt, source=source))
    if not hits:
        return prune_sources(report, source_artifact([]))
    evidence, artifact = format_result(RetrievalResult(hits=hits), max_chars_per_chunk=100_000, max_total_chars=max_total_chars)
    return prune_sources(f"{report}\n\nKnowledge evidence:\n{evidence}", artifact)
