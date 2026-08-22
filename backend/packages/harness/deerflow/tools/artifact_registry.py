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

from langchain_core.messages import ToolMessage

from deerflow.agents.thread_state import ArtifactEntry

_HANDLE_PREFIX = "art_"
_HANDLE_LENGTH = 8

# Virtual sandbox path prefix (used by local stdio MCP servers whose files live
# inside the mounted user-data tree).
_SANDBOX_PATH_PATTERN = re.compile(r"/mnt/user-data/\S+")

# Conservative URL-with-file-extension match for remote references.
_REMOTE_FILE_URL_PATTERN = re.compile(r"https?://\S+\.(?:png|jpg|jpeg|gif|html|pdf|csv|json|txt|log|md|xlsx?|docx?|zip)")

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
_ACCEPTED_URL_SHAPES = ("http://", "https://", "/")
_REJECTED_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:")

_ARTIFACT_RENDER_CHAR_BUDGET = 3000


def _is_referenceable_url(url: str) -> bool:
    """Accept http(s) URLs and absolute paths; reject any other URI scheme
    (including protocol-relative `//host` forms)."""
    if url.startswith("//"):
        return False
    return not _REJECTED_SCHEME_RE.match(url) or url.startswith(_ACCEPTED_URL_SHAPES)


def generate_handle(thread_id: str, tool_call_id: str, call_index: int, ref_ordinal: int = 0) -> str:
    """Return a deterministic short handle for an artifact.

    The same ``(thread_id, tool_call_id, call_index, ref_ordinal)`` always
    produces the same handle. ``tool_call_id`` is unique within an ``AIMessage``
    and ``ref_ordinal`` distinguishes multiple references extracted from one
    result, so collisions are not possible within a thread.
    """
    seed = f"{thread_id}:{tool_call_id}:{call_index}:{ref_ordinal}"
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
        if raw in seen:
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
        if raw in seen:
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


def _collect_structured_refs(value: Any, found: list[tuple[str, str]]) -> None:
    """Recursively collect ``(key, string_value)`` pairs under known ref keys."""
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str) and (key in _STRUCTURED_REF_KEYS or key in _STRUCTURED_TASK_KEYS):
                if isinstance(item, str):
                    found.append((key, item))
                elif isinstance(item, list):
                    for element in item:
                        if isinstance(element, str):
                            found.append((key, element))
                        else:
                            _collect_structured_refs(element, found)
            else:
                _collect_structured_refs(item, found)
    elif isinstance(value, list):
        for item in value:
            _collect_structured_refs(item, found)


def _display_name_for_ref(ref: str) -> str:
    return ref.split("/")[-1] or ref


class _EntrySink:
    """Allocates sequential per-result ordinals so every extracted reference
    within one tool result gets a distinct handle."""

    def __init__(self, *, thread_id: str, tool_call_id: str, call_index: int, created_at: str, tool_name: str):
        self._thread_id = thread_id
        self._tool_call_id = tool_call_id
        self._call_index = call_index
        self._created_at = created_at
        self._tool_name = tool_name
        self._next_ordinal = 0

    def add(self, *, artifact_type: str, display_name: str, real_ref: str, mime_type: str | None = None) -> ArtifactEntry:
        entry = _make_entry(
            handle=generate_handle(self._thread_id, self._tool_call_id, self._call_index, self._next_ordinal),
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
       whole payload becomes one untruncated JSON ``data`` entry.
    2. ``content`` blocks of type ``file`` / ``image`` with a URL source become
       ``file`` / ``image`` entries.
    3. ``content`` text blocks and plain-string results are scanned
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
    sink = _EntrySink(thread_id=thread_id, tool_call_id=tool_call_id, call_index=call_index, created_at=now, tool_name=tool_name)
    entries: list[ArtifactEntry] = []

    artifact = result.artifact
    if artifact is not None and isinstance(artifact, dict):
        structured = artifact.get("structured_content")
        if structured is not None:
            found: list[tuple[str, str]] = []
            _collect_structured_refs(structured, found)
            if found:
                for key, value in found:
                    if not _is_referenceable_url(value):
                        continue
                    entries.append(
                        sink.add(
                            artifact_type="task" if key in _STRUCTURED_TASK_KEYS else "file",
                            display_name=_display_name_for_ref(value),
                            real_ref=value,
                        )
                    )
            else:
                entries.append(
                    sink.add(
                        artifact_type="data",
                        display_name=f"{tool_name} structured result",
                        real_ref=json.dumps(structured, ensure_ascii=False),
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
                        display_name=url.split("/")[-1] or url,
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
        if len("\n".join([*lines, line])) > max_chars:
            break
        lines.append(line)
    return "\n".join(lines)
