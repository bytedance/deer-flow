"""Persistent artifact handle registry for tool outputs (issue #4676).

MCP tools (and other tools) return file paths, URLs, task ids, and other
references in ``ToolMessage.content``. When context compaction summarizes the
conversation, those structured references are reduced to natural-language prose
and the LLM can no longer deterministically resolve them.

This module provides a short, deterministic ``handle`` for each artifact so the
model can reference it across turns, plus extraction helpers that turn a
``ToolMessage`` into ``ArtifactEntry`` records for ``ThreadState.tool_artifacts``.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from langchain_core.messages import ToolMessage

from deerflow.agents.thread_state import ArtifactEntry

_HANDLE_PREFIX = "art_"
_HANDLE_LENGTH = 8

# Virtual sandbox path prefix (used by local stdio MCP servers whose files live
# inside the mounted user-data tree).
_SANDBOX_PATH_PATTERN = re.compile(r"/mnt/user-data/\S+")

# Conservative URL-with-file-extension match for remote references.
_REMOTE_FILE_URL_PATTERN = re.compile(r"https?://[^\s\"'`<>]+\.(?:png|jpg|jpeg|gif|html|pdf|csv|json|txt|log|md|xlsx?|docx?|zip)(?:[?#][^\s\"'`<>]*)?")

# Structured-content keys whose string values are treated as concrete
# references (paths, URLs, remote task ids) rather than opaque payload.
# Deliberately excludes generic result keys such as `output`/`outputs`: their
# values are usually prose, and path-shaped refs inside them are already caught
# by the free-text scan over tool content.
_STRUCTURED_REF_KEYS = frozenset({"file", "files", "file_path", "path", "url", "urls"})
_STRUCTURED_TASK_KEYS = frozenset({"task_id", "job_id"})

# Characters stripped from detected refs: prose punctuation plus the closing
# quotes/brackets/backticks that markdown- and JSON-formatted tool output
# commonly wraps paths in. `\S+` would otherwise consume them into `real_ref`.
_REF_TRAILING_NOISE_CHARS = ".,;:)]}\"'`"

# Content-block and structured-key refs are trusted only in these shapes.
# `data:`/`blob:` URIs can carry arbitrarily large embedded payloads (MCP
# embedded resources) that must never enter thread state, tool args, or crowd
# out the render budget; other schemes are equally unresolvable downstream.

_ARTIFACT_RENDER_CHAR_BUDGET = 3000
_STRUCTURED_DATA_MAX_BYTES = 4096
_STRUCTURED_MAX_NODES = 1024
_STRUCTURED_MAX_DEPTH = 32
_WINDOWS_ABSOLUTE_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")


def _is_referenceable_url(url: str) -> bool:
    """Accept http(s) URLs and absolute paths; reject any other URI scheme
    (including protocol-relative `//host` forms)."""
    if not url or len(url) > _STRUCTURED_DATA_MAX_BYTES or url.startswith("//"):
        return False
    try:
        if len(url.encode("utf-8")) > _STRUCTURED_DATA_MAX_BYTES:
            return False
    except UnicodeError:
        return False
    if url.startswith(("http://", "https://")):
        try:
            return bool(urlsplit(url).netloc) and not any(char.isspace() for char in url)
        except ValueError:
            return False
    return url.startswith("/") or bool(_WINDOWS_ABSOLUTE_PATH_RE.match(url))


def _is_referenceable_task_id(value: str) -> bool:
    return bool(value) and len(value) <= 256 and not value.startswith(("data:", "blob:", "//")) and not any(char.isspace() for char in value)


def generate_handle(thread_id: str, tool_call_id: str, call_index: int, ref_ordinal: int = 0, *, occurrence_id: str | None = None) -> str:
    """Return a deterministic short handle for an artifact.

    Message IDs distinguish provider IDs reused across assistant turns and stay
    stable through checkpoint reload and compaction. ID-less standalone callers
    must supply an occurrence-specific ``call_index``. The ordinal distinguishes
    references within one result. Short hashes are identifiers, not credentials.
    """
    seed = f"{thread_id}:{tool_call_id}:{call_index}:{ref_ordinal}"
    if occurrence_id is not None:
        seed += f":{occurrence_id}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:_HANDLE_LENGTH]
    return f"{_HANDLE_PREFIX}{digest}"


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _make_entry(
    *,
    handle: str,
    tool_name: str,
    tool_call_id: str,
    call_index: int,
    artifact_type: str,
    display_name: str,
    real_ref: str,
    created_at: str,
    mime_type: str | None = None,
) -> ArtifactEntry:
    entry: ArtifactEntry = {
        "handle": handle,
        "tool_name": tool_name,
        "tool_call_id": tool_call_id,
        "call_index": call_index,
        "artifact_type": artifact_type,
        "display_name": display_name,
        "real_ref": real_ref,
        "created_at": created_at,
    }
    if mime_type:
        entry["mime_type"] = mime_type
    return entry


def _detect_refs_in_text(text: str) -> list[dict[str, str]]:
    """Conservatively detect file paths and remote file URLs in free text."""
    refs: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in _SANDBOX_PATH_PATTERN.finditer(text):
        raw = match.group(0).rstrip(_REF_TRAILING_NOISE_CHARS)
        if raw in seen or not _is_referenceable_url(raw):
            continue
        seen.add(raw)
        refs.append(
            {
                "type": "file",
                "ref": raw,
                "display": raw.split("/")[-1],
            }
        )
    for match in _REMOTE_FILE_URL_PATTERN.finditer(text):
        raw = match.group(0).rstrip(_REF_TRAILING_NOISE_CHARS)
        if raw in seen or not _is_referenceable_url(raw):
            continue
        seen.add(raw)
        refs.append(
            {
                "type": "file",
                "ref": raw,
                "display": raw.split("/")[-1],
            }
        )
    return refs


def _collect_structured_refs(value: Any, found: list[tuple[str, str]]) -> bool:
    """Collect reference keys with a bounded traversal; reject oversized shapes."""
    pending = [(None, value, 0)]
    visited = 0
    while pending:
        key, item, depth = pending.pop()
        visited += 1
        if visited > _STRUCTURED_MAX_NODES or depth > _STRUCTURED_MAX_DEPTH:
            return False
        if isinstance(item, (dict, list)) and len(item) + visited + len(pending) > _STRUCTURED_MAX_NODES:
            return False
        if isinstance(item, dict):
            pending.extend((child_key, child, depth + 1) for child_key, child in reversed(item.items()))
        elif isinstance(item, list):
            pending.extend((key, child, depth + 1) for child in reversed(item))
        elif isinstance(item, str) and (key in _STRUCTURED_REF_KEYS or key in _STRUCTURED_TASK_KEYS):
            found.append((key, item))
    return True


def _serialize_bounded_data(value: Any) -> str | None:
    """Keep complete JSON only when its shape and UTF-8 size fit the budget.

    Preflight strings and collection sizes before encoding, so an enormous
    unknown MCP payload cannot trigger unbounded json.dumps on the agent loop.
    """
    if not value:
        return None
    pending = [(value, 0)]
    visited = 0
    estimated_bytes = 0
    while pending:
        item, depth = pending.pop()
        visited += 1
        if visited > _STRUCTURED_MAX_NODES or depth > _STRUCTURED_MAX_DEPTH:
            return None
        if isinstance(item, str):
            if len(item) > _STRUCTURED_DATA_MAX_BYTES:
                return None
            try:
                estimated_bytes += len(item.encode("utf-8")) + 2
            except UnicodeError:
                return None
        elif isinstance(item, (dict, list)):
            if len(item) + visited + len(pending) > _STRUCTURED_MAX_NODES:
                return None
            estimated_bytes += 2 + len(item)
            if isinstance(item, dict):
                if any(not isinstance(key, str) for key in item):
                    return None
                pending.extend((child, depth + 1) for child in item.values())
                pending.extend((key, depth + 1) for key in item)
            else:
                pending.extend((child, depth + 1) for child in item)
        elif isinstance(item, int):
            if item.bit_length() > _STRUCTURED_DATA_MAX_BYTES:
                return None
        elif item is not None and not isinstance(item, float):
            return None
        if estimated_bytes > _STRUCTURED_DATA_MAX_BYTES:
            return None
    try:
        encoded = json.dumps(value, ensure_ascii=False)
        return encoded if len(encoded.encode("utf-8")) <= _STRUCTURED_DATA_MAX_BYTES else None
    except (ValueError, TypeError, UnicodeError):
        return None


def _display_name_for_ref(ref: str) -> str:
    return ref.replace("\\", "/").split("/")[-1] or ref


class _EntrySink:
    """Allocates sequential per-result ordinals so every extracted reference
    within one tool result gets a distinct handle."""

    def __init__(self, *, thread_id: str, tool_call_id: str, call_index: int, created_at: str, tool_name: str, occurrence_id: str | None):
        self._occurrence_id = occurrence_id
        self._thread_id = thread_id
        self._tool_call_id = tool_call_id
        self._call_index = call_index
        self._created_at = created_at
        self._tool_name = tool_name
        self._next_ordinal = 0

    def add(self, *, artifact_type: str, display_name: str, real_ref: str, mime_type: str | None = None) -> ArtifactEntry:
        entry = _make_entry(
            handle=generate_handle(self._thread_id, self._tool_call_id, self._call_index, self._next_ordinal, occurrence_id=self._occurrence_id),
            tool_name=self._tool_name,
            tool_call_id=self._tool_call_id,
            call_index=self._call_index,
            artifact_type=artifact_type,
            display_name=display_name,
            real_ref=real_ref,
            created_at=self._created_at,
            mime_type=mime_type,
        )
        self._next_ordinal += 1
        return entry


def extract_artifacts_from_result(
    result: ToolMessage,
    *,
    thread_id: str,
    call_index: int = 0,
    detect_refs_in_text: bool = True,
) -> list[ArtifactEntry]:
    """Extract artifact references from a ``ToolMessage``.

    Extraction sources, all combined (not mutually exclusive):

    1. ``ToolMessage.artifact["structured_content"]`` (MCP ``structuredContent``):
       string values under known keys (``file``/``path``/``url``/``task_id``/...)
       become concrete ``file``/``task`` entries; when no known key matches, the
       whole payload becomes a complete JSON ``data`` entry only within the
       4096-byte, 1024-node and 32-level limits. Empty/oversized payloads are skipped.
    2. ``artifact["resource_links"]`` — the ``{"name", "uri", "mime_type"}``
       entries the MCP conversion layer writes for downgraded ``ResourceLink``
       results — become ``file`` entries, subject to the same
       referenceability gate as every other ref source (``data:``/``blob:``
       and other unresolvable URIs are skipped).
    3. ``content`` blocks of type ``file`` / ``image`` with a URL source become
       ``file`` / ``image`` entries.
    4. ``content`` text blocks and plain-string results are scanned
       conservatively for sandbox paths and remote file URLs (gated by
       ``detect_refs_in_text``).

    Error results produce no entries. Every reference from one result gets a
    distinct handle via a sequential ordinal.
    """
    if result.status == "error":
        return []

    now = _utc_now_iso()
    tool_name = result.name or "unknown"
    tool_call_id = result.tool_call_id or ""
    sink = _EntrySink(thread_id=thread_id, tool_call_id=tool_call_id, call_index=call_index, created_at=now, tool_name=tool_name, occurrence_id=result.id)
    entries: list[ArtifactEntry] = []

    artifact = result.artifact
    if artifact is not None and isinstance(artifact, dict):
        structured = artifact.get("structured_content")
        if structured:
            found: list[tuple[str, str]] = []
            if _collect_structured_refs(structured, found):
                for key, value in found:
                    is_task = key in _STRUCTURED_TASK_KEYS
                    if not (_is_referenceable_task_id(value) if is_task else _is_referenceable_url(value)):
                        continue
                    entries.append(sink.add(artifact_type="task" if is_task else "file", display_name=_display_name_for_ref(value), real_ref=value))
                if not entries and not any(value.startswith(("data:", "blob:")) for _, value in found):
                    encoded = _serialize_bounded_data(structured)
                    if encoded is not None:
                        entries.append(sink.add(artifact_type="data", display_name=f"{tool_name} structured result", real_ref=encoded))

        resource_links = artifact.get("resource_links")
        if isinstance(resource_links, list):
            for link in resource_links:
                if not isinstance(link, dict):
                    continue
                uri = link.get("uri")
                if not isinstance(uri, str) or not _is_referenceable_url(uri):
                    continue
                name = link.get("name")
                mime = link.get("mime_type")
                entries.append(
                    sink.add(
                        artifact_type="file",
                        display_name=name if isinstance(name, str) and name else _display_name_for_ref(uri),
                        real_ref=uri,
                        mime_type=mime if isinstance(mime, str) and mime else None,
                    )
                )

    content = result.content
    if isinstance(content, str):
        if detect_refs_in_text and content:
            for ref in _detect_refs_in_text(content):
                entries.append(sink.add(artifact_type=ref["type"], display_name=ref["display"], real_ref=ref["ref"]))
        return entries
    if not isinstance(content, list):
        return entries

    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type", "")

        if block_type in {"file", "image"}:
            source = block.get("source") or {}
            if not isinstance(source, dict):
                continue
            url = source.get("url")
            if isinstance(url, str) and url and _is_referenceable_url(url):
                entries.append(
                    sink.add(
                        artifact_type="file" if block_type == "file" else "image",
                        display_name=_display_name_for_ref(url),
                        real_ref=url,
                        mime_type=source.get("mime_type") if isinstance(source.get("mime_type"), str) else None,
                    )
                )
            continue

        if block_type == "text" and detect_refs_in_text:
            text = block.get("text")
            if not isinstance(text, str):
                continue
            for ref in _detect_refs_in_text(text):
                entries.append(sink.add(artifact_type=ref["type"], display_name=ref["display"], real_ref=ref["ref"]))
    return entries


def render_artifact_registry(entries: list[ArtifactEntry], *, max_chars: int = _ARTIFACT_RENDER_CHAR_BUDGET) -> str:
    """Render the artifact registry as model-visible context.

    Shows each handle with its type, display name, and availability. Consumed
    handles are marked so the model prefers unused artifacts. The output is
    escaped so untrusted tool-provided values cannot forge framework context.
    """
    if not entries:
        return ""

    from html import escape

    lines = [
        "## Available artifact handles",
        "These are persistent handles for tool-produced artifacts. Reference them by handle in tool arguments; they resolve automatically.",
    ]
    lines.append("Handles are local to this agent; task subagents do not share this registry. Return concrete references in delegated reports, not local handles.")
    omitted_marker = f"... {len(entries)} more artifact handles not shown"
    if len("\n".join([*lines, omitted_marker])) > max_chars:
        return omitted_marker[: max(0, max_chars)]
    shown = 0
    for entry in reversed(entries):
        handle = escape(entry.get("handle", ""))
        artifact_type = escape(entry.get("artifact_type", ""))
        display_name = escape(entry.get("display_name", ""))
        consumed = bool(entry.get("consumed_by"))
        status = "consumed" if consumed else "available"
        mime = entry.get("mime_type")
        mime_suffix = f" ({escape(str(mime))})" if mime else ""
        tool_name = escape(entry.get("tool_name", ""))
        line = f"- `{handle}` -> {artifact_type}: {display_name}{mime_suffix} [{status}] (from {tool_name})"
        remaining = len(entries) - shown - 1
        marker = f"... {remaining} more artifact handles not shown"
        candidate = [*lines, line, *([marker] if remaining else [])]
        if len("\n".join(candidate)) > max_chars:
            break
        lines.append(line)
        shown += 1
    if shown < len(entries):
        lines.append(f"... {len(entries) - shown} more artifact handles not shown")
    return "\n".join(lines)
