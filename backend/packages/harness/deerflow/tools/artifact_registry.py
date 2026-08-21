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
_REMOTE_FILE_URL_PATTERN = re.compile(
    r"https?://\S+\.(?:png|jpg|jpeg|gif|html|pdf|csv|json|txt|log|md|xlsx?|docx?|zip)"
)

_STRUCTURED_REF_CAP = 500
_ARTIFACT_RENDER_CHAR_BUDGET = 3000


def generate_handle(thread_id: str, tool_call_id: str, call_index: int) -> str:
    """Return a deterministic short handle for an artifact.

    The same ``(thread_id, tool_call_id, call_index)`` always produces the same
    handle. ``tool_call_id`` is unique within an ``AIMessage`` and ``call_index``
    distinguishes multiple outputs from one tool call, so collisions are not
    possible within a thread.
    """
    seed = f"{thread_id}:{tool_call_id}:{call_index}"
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
        raw = match.group(0).rstrip(".,;:)")
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
        raw = match.group(0).rstrip(".,;:)")
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


def _extract_content_block_entries(
    content: list[Any],
    *,
    tool_name: str,
    tool_call_id: str,
    thread_id: str,
    call_index: int,
    created_at: str,
) -> list[ArtifactEntry]:
    entries: list[ArtifactEntry] = []
    for i, block in enumerate(content):
        if not isinstance(block, dict):
            continue
        block_type = block.get("type", "")
        block_index = call_index + i

        if block_type in {"file", "image"}:
            source = block.get("source") or {}
            if not isinstance(source, dict):
                continue
            url = source.get("url")
            if isinstance(url, str) and url:
                entries.append(
                    _make_entry(
                        handle=generate_handle(thread_id, tool_call_id, block_index),
                        tool_name=tool_name,
                        tool_call_id=tool_call_id,
                        call_index=block_index,
                        artifact_type="file" if block_type == "file" else "image",
                        display_name=url.split("/")[-1] or url,
                        real_ref=url,
                        created_at=created_at,
                        mime_type=source.get("mime_type") if isinstance(source.get("mime_type"), str) else None,
                    )
                )
            continue

        if block_type == "text":
            text = block.get("text")
            if not isinstance(text, str):
                continue
            for ref in _detect_refs_in_text(text):
                entries.append(
                    _make_entry(
                        handle=generate_handle(thread_id, tool_call_id, block_index),
                        tool_name=tool_name,
                        tool_call_id=tool_call_id,
                        call_index=block_index,
                        artifact_type=ref["type"],
                        display_name=ref["display"],
                        real_ref=ref["ref"],
                        created_at=created_at,
                    )
                )
    return entries


def extract_artifacts_from_result(
    result: ToolMessage,
    *,
    thread_id: str,
    call_index: int = 0,
) -> list[ArtifactEntry]:
    """Extract artifact references from a ``ToolMessage``.

    Precedence:
    1. ``ToolMessage.artifact["structured_content"]`` (MCP ``structuredContent``)
       becomes a single ``data`` entry carrying a compact JSON preview.
    2. ``content`` blocks of type ``file`` / ``image`` with a URL source become
       ``file`` / ``image`` entries.
    3. ``content`` text blocks are scanned conservatively for sandbox paths and
       remote file URLs.

    Error results and plain-string content (no refs) produce no entries.
    """
    if result.status == "error":
        return []

    now = _utc_now_iso()
    tool_name = result.name or "unknown"
    tool_call_id = result.tool_call_id or ""
    entries: list[ArtifactEntry] = []

    artifact = result.artifact
    if artifact is not None and isinstance(artifact, dict):
        structured = artifact.get("structured_content")
        if structured is not None:
            preview = json.dumps(structured, ensure_ascii=False)[:_STRUCTURED_REF_CAP]
            entries.append(
                _make_entry(
                    handle=generate_handle(thread_id, tool_call_id, call_index),
                    tool_name=tool_name,
                    tool_call_id=tool_call_id,
                    call_index=call_index,
                    artifact_type="data",
                    display_name=f"{tool_name} structured result",
                    real_ref=preview,
                    created_at=now,
                )
            )
            return entries

    content = result.content
    if isinstance(content, str):
        return entries
    if not isinstance(content, list):
        return entries

    return _extract_content_block_entries(
        content,
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        thread_id=thread_id,
        call_index=call_index,
        created_at=now,
    )


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