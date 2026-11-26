"""Shared validation, evidence-preserving budgets, and delegation forwarding."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping
from typing import Annotated, Any

from pydantic import BaseModel, Field, ValidationError

from .contract import KnowledgeSource, RetrievalResult

ARTIFACT_VERSION = 1
TRUNCATION_MARKER = "… (response truncated)"
_RESULT_LAYOUT_KEY = "knowledge_result_layout"
_SOURCE_ARTIFACT_KEYS = frozenset({"knowledge_sources", "knowledge_sources_version", "retrieval_sources", _RESULT_LAYOUT_KEY})
_ResultPosition = Annotated[int, Field(strict=True, ge=1, le=100)]
_CITATION_PATTERN = re.compile(r"\[citation:((?:\\.|[^\]\\])*)\]\(#knowledge-source-([a-f0-9]{32})\)")


class _ResultEntry(BaseModel):
    position: _ResultPosition
    start: int = Field(strict=True, ge=0)
    end: int = Field(strict=True, gt=0)
    source_id: str | None = None
    depends_on: list[_ResultPosition] = Field(max_length=99)


class _ResultLayout(BaseModel):
    digest: str
    entries: list[_ResultEntry] = Field(max_length=100)
    # An empty notice denotes a saved file whose path did not fit the budget.
    file_notice: str | None = None


_ResultCandidate = tuple[_ResultEntry, str, KnowledgeSource | None]


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
    if isinstance(artifact, Mapping) and not _SOURCE_ARTIFACT_KEYS.isdisjoint(artifact):
        return {key: value for key, value in artifact.items() if key not in _SOURCE_ARTIFACT_KEYS}
    return artifact


def _prune_citations(content: str, allowed: set[str]) -> str:
    return _CITATION_PATTERN.sub(lambda match: match[0] if match[2] in allowed else match[1], content)


def prune_sources(content: str, artifact: Any) -> tuple[str, Any]:
    """Budget transformations retain only evidence still visible to the model."""
    if not isinstance(artifact, Mapping) or artifact.get("knowledge_sources_version") != ARTIFACT_VERSION:
        return content, artifact
    sources = sources_from_messages([{"type": "tool", "content": content, "artifact": artifact}])
    allowed = {source.id for source in sources}
    content = _prune_citations(content, allowed)
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


def _evidence_line(positions: list[int]) -> str:
    if not positions:
        return ""
    references = ", ".join(f"result [{position}]" for position in positions)
    return f"Evidence: {references}.\n"


def _content_digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8", errors="surrogatepass")).hexdigest()


def _set_result_layout(artifact: dict[str, Any], content: str, entries: list[dict[str, Any]], *, file_notice: str | None = None, preserve: bool = False) -> None:
    if preserve or file_notice is not None or any(entry["depends_on"] for entry in entries):
        artifact[_RESULT_LAYOUT_KEY] = {"digest": _content_digest(content), "entries": entries}
        if file_notice is not None:
            artifact[_RESULT_LAYOUT_KEY]["file_notice"] = file_notice


def format_result(result: RetrievalResult, *, max_chars_per_chunk: int = 800, max_total_chars: int = 8000) -> tuple[str, dict[str, Any]]:
    """Budget text and its evidence together; never cut a citation in half."""
    entries: list[str] = []
    layout: list[dict[str, Any]] = []
    sources: list[KnowledgeSource] = []
    retained_evidence: set[int] = set()
    used_chars = 0
    budget = max(0, max_total_chars)
    truncated = False
    for index, hit in enumerate(result.hits, 1):
        if index > 100:
            truncated = True
            break  # Match the bounded artifact readers and delegation ledger.
        if not retained_evidence.issuperset(hit.depends_on):
            truncated = True
            continue
        evidence_line = _evidence_line(hit.depends_on)
        raw_content = hit.content.strip()
        content = truncate(raw_content, max_chars_per_chunk - len(evidence_line))
        if not content or (evidence_line and content == "…"):
            truncated |= bool(evidence_line)
            continue
        source = hit.source
        # Evidence must be from this hit. Adapters cannot attach unrelated text.
        if source is not None and source.excerpt != raw_content:
            source = None
        if content == "…" and len(raw_content) > len(content):
            source = None  # A truncation marker alone is not retrieved evidence.
        if source is not None:
            source = KnowledgeSource.model_validate({**source.model_dump(exclude={"id"}), "excerpt": content})
        header = f"[{index}] {citation(source) if source else 'Unattributed content'}\n"
        separator = "\n\n" if entries else ""
        remaining = budget - used_chars - len(separator)
        entry = header + evidence_line + content
        if len(entry) > remaining:
            # Skip this hit without changing its excerpt or source identity;
            # a later, shorter entry may still fit the remaining budget.
            truncated = True
            continue
        entries.append(separator + entry)
        layout.append({"position": index, "start": used_chars + len(separator), "end": used_chars + len(separator) + len(entry), "source_id": source.id if source is not None else None, "depends_on": hit.depends_on.copy()})
        used_chars += len(separator) + len(entry)
        if source is not None:
            sources.append(source)
            retained_evidence.add(index)
    text = "".join(entries)
    if truncated:
        remaining = budget - len(text)
        text += truncate(TRUNCATION_MARKER, remaining, marker="")
    elif not text:
        text = truncate("No relevant content found.", budget, marker="")
    artifact = source_artifact(sources)
    _set_result_layout(artifact, text, layout)
    return text, artifact


def _project_result_entries(candidates: list[_ResultCandidate]) -> tuple[str, list[dict[str, Any]], dict[str, KnowledgeSource]]:
    """Reconcile one proposed selection without mutating its original excerpts."""
    source_ids = {entry.position: source.id for entry, _, source in candidates if source is not None}
    allowed = set(source_ids.values())
    while True:
        cleaned = []
        unchanged_ids: set[str] = set()
        evidence: set[int] = set()
        for entry, body, source in candidates:
            if not evidence.issuperset(entry.depends_on):
                continue
            body = _prune_citations(body, allowed).strip()
            if not body:
                continue
            if source is not None:
                evidence.add(entry.position)
                if source.excerpt == body:
                    unchanged_ids.add(source_ids[entry.position])
            cleaned.append((entry, body, source))
        stable = unchanged_ids == allowed and cleaned == candidates
        candidates = cleaned
        if stable:
            break
        # Changed excerpts cannot support their original citation handles.
        # Only remove handles/entries here; rebuild source IDs once at the end.
        allowed = unchanged_ids

    entries, layout = [], []
    retained_sources: dict[str, KnowledgeSource] = {}
    used = 0
    for entry, body, source in candidates:
        if source is not None:
            if source.excerpt != body:
                source = KnowledgeSource.model_validate({**source.model_dump(exclude={"id"}), "excerpt": body})
            retained_sources[source.id] = source
        text = f"[{entry.position}] {citation(source) if source else 'Unattributed content'}\n{_evidence_line(entry.depends_on)}{body}"
        start = used + (2 if entries else 0)
        used = start + len(text)
        entries.append(text)
        layout.append(entry.model_dump() | {"start": start, "end": used, "source_id": source.id if source else None})
    return "\n\n".join(entries), layout, retained_sources


def _result_trial(candidate: _ResultCandidate, selected: list[_ResultCandidate], by_position: dict[int, _ResultCandidate], by_source: dict[str, _ResultCandidate]) -> list[_ResultCandidate]:
    trial = {item[0].position: item for item in selected}
    required = [candidate]
    visited: set[int] = set()
    while required:
        item = required.pop()
        if item[0].position in visited:
            continue
        visited.add(item[0].position)
        trial[item[0].position] = item
        required.extend(by_position[position] for position in item[0].depends_on if position in by_position)
        if by_source:
            required.extend(by_source[match[2]] for match in _CITATION_PATTERN.finditer(item[1]) if match[2] in by_source)
    return sorted(trial.values(), key=lambda item: item[0].position)


def budget_dependent_result(content: str, artifact: Any, max_chars: int, *, file_notice: str = "", max_total_chars: int | None = None) -> tuple[str, dict[str, Any]] | None:
    """Project whole retrieval entries and their evidence into a later budget."""
    if not isinstance(artifact, Mapping) or _RESULT_LAYOUT_KEY not in artifact:
        return None
    updated = {key: value for key, value in artifact.items() if key != _RESULT_LAYOUT_KEY}
    try:
        layout = _ResultLayout.model_validate(artifact[_RESULT_LAYOUT_KEY])
    except ValidationError:
        layout = None
    if layout is not None and layout.digest != _content_digest(content):
        layout = None
    if not file_notice and layout is not None:
        tail = content[layout.entries[-1].end if layout.entries else 0 :]
        if layout.file_notice and tail.endswith(layout.file_notice):
            file_notice = layout.file_notice
        elif layout.file_notice is None:
            # Older previews kept the generated notice after the last entry span.
            _, prefix, notice = tail.partition("[Full output saved to /mnt/user-data/outputs/")
            if prefix and notice.endswith(". Use read_file to inspect it.]"):
                file_notice = prefix + notice
    file_backed = bool(file_notice) or (layout is not None and layout.file_notice is not None)
    total_chars = max_chars if max_total_chars is None else max_total_chars
    omitted_notice = file_backed and (not file_notice or len(file_notice) > total_chars)
    if omitted_notice:
        file_notice = ""
    notice_cost = len(file_notice) + 2 if file_notice else 0
    max_chars = min(max_chars, max(0, total_chars - notice_cost))
    candidates: list[_ResultCandidate] = []
    previous_position = previous_end = 0
    if layout is not None:
        available = {source.id: source for source in sources_from_messages([{"type": "tool", "content": content, "artifact": artifact}])}
        for entry in layout.entries:
            if not (entry.position > previous_position and previous_end <= entry.start < entry.end <= len(content)):
                continue
            previous_position, previous_end = entry.position, entry.end
            text = content[entry.start : entry.end]
            source = available.get(entry.source_id) if entry.source_id is not None else None
            if entry.source_id is not None and source is None:
                continue
            label = citation(source) if source is not None else "Unattributed content"
            prefix = f"[{entry.position}] {label}\n" + _evidence_line(entry.depends_on)
            if not text.startswith(prefix) or (source is not None and text[len(prefix) :] != source.excerpt):
                continue
            body = text[len(prefix) :]
            minimum = body
            while (pruned := _prune_citations(minimum, set()).strip()) != minimum:
                minimum = pruned
            # Even removing every destination cannot make this entry fit.
            if len(prefix) >= max_chars or len(prefix) + len(minimum) > max_chars:
                continue
            candidates.append((entry, body, source))

    selected: list[_ResultCandidate] = []
    positions: set[int] = set()
    by_position = {item[0].position: item for item in candidates}
    by_source = {item[2].id: item for item in candidates if item[2] is not None}
    # Admit the complete valid group when it fits, including entries whose
    # inline citations and explicit dependencies need each other to survive.
    text, retained_layout, retained_sources = _project_result_entries(candidates)
    if len(text) <= max_chars:
        candidates = []
    else:
        text, retained_layout, retained_sources = "", [], {}
    while candidates:
        pending = []
        for candidate in candidates:
            entry = candidate[0]
            if entry.position in positions:
                continue
            # Usually declared dependencies suffice. An otherwise empty entry
            # may also need its inline citation's evidence admitted with it.
            for support in ({}, by_source):
                trial = _result_trial(candidate, selected, by_position, support)
                projected, projected_layout, projected_sources = _project_result_entries(trial)
                projected_positions = {item["position"] for item in projected_layout}
                if entry.position in projected_positions:
                    if positions.issubset(projected_positions) and len(projected) <= max_chars:
                        selected = [item for item in trial if item[0].position in projected_positions]
                        positions = projected_positions
                        text, retained_layout, retained_sources = projected, projected_layout, projected_sources
                    break  # Restoring more links cannot rescue an oversized group.
            if entry.position not in positions:
                pending.append(candidate)
        if len(pending) == len(candidates):
            break
        # Accepted positions only grow (at most 100). Retry earlier empty or
        # dependent entries after later evidence makes their citations valid.
        # Every trial starts from original bodies: restored links and changed
        # source IDs must fit too, not just the newly admitted entry's text.
        candidates = pending

    separator = "\n\n" if text else ""
    if omitted_notice or layout is None or len(retained_layout) < len(layout.entries) or content.endswith(TRUNCATION_MARKER):
        remaining = max_chars - len(text) - len(separator)
        if remaining > 0:
            text += separator + TRUNCATION_MARKER[:remaining]
    if file_notice:
        text = f"{text}\n\n{file_notice}" if text else file_notice
    updated.update(source_artifact(retained_sources.values()))
    _set_result_layout(updated, text, retained_layout, file_notice=file_notice if file_backed else None, preserve=bool(retained_layout))
    return text, updated


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
