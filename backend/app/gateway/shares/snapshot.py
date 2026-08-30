"""Immutable snapshot builder for read-only conversation sharing (#4548).

Reuses the canonical paged-message path (``_scan_thread_message_page``) and
its visibility helpers rather than adding a second interpretation of thread
history, then converts the result into the narrow public DTO. The design
requires the allowlist here: not every ``hide_from_ui`` message is filtered
by the scan (allowlisted ``ask_clarification`` replies can be persisted), so
the hidden/control filter is applied again on top.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import unquote

from deerflow.utils.llm_text import strip_think_blocks

logger = logging.getLogger(__name__)

_SNAPSHOT_SCAN_PAGE_SIZE = 200
_SNAPSHOT_MAX_MESSAGES = 2000
# Independent safety bound on RAW scanned rows: a tool-heavy thread can carry
# far more rows than public messages, and without this the backward scan
# would walk an unbounded history while the public-message count stays under
# the share cap.
_SNAPSHOT_MAX_SCANNED_ROWS = 50_000
_FENCED_CODE_RE = re.compile(
    r"^[ \t]{0,3}(?P<fence>`{3,}|~{3,})[^\n]*\n.*?^[ \t]{0,3}(?P=fence)[ \t]*(?:\n|$)",
    re.MULTILINE | re.DOTALL,
)
_INLINE_CODE_RE = re.compile(r"(?P<ticks>`+).*?(?P=ticks)", re.DOTALL)
_MARKDOWN_LINK_RE = re.compile(r"!?\[(?P<label>[^\]]*)\]\((?P<target>[^)]+)\)")
_REFERENCE_RE = re.compile(
    r"(?:https?://|/|%[0-9A-Fa-f]{2}|mnt(?=[\\/]|%[0-9A-Fa-f]{2}))[^\s<>\"]+",
    re.IGNORECASE,
)
_PRIVATE_REFERENCE_MARKER = "[private artifact omitted]"


class ShareSnapshotTooLarge(Exception):
    """The thread's visible transcript exceeds the share snapshot cap.

    A share promises the *complete* visible transcript (#4548); instead of
    silently dropping the oldest messages, creation must fail loudly.
    """

    def __init__(self, thread_id: str, hit: int, cap: int, *, limit_kind: str = "public-message") -> None:
        super().__init__(f"thread {thread_id} exceeds the {cap} {limit_kind} share snapshot cap")
        self.thread_id = thread_id
        self.hit = hit
        self.cap = cap


async def build_share_snapshot(
    thread_id: str,
    *,
    request: Any,
    user_id: str | None,
) -> dict[str, Any]:
    """Freeze the visible transcript of *thread_id* into a public DTO."""
    from app.gateway.routers.thread_runs import (
        _RawMessageScanBudget,
        _RawMessageScanLimitExceeded,
        _scan_thread_message_page,
    )

    # ``_scan_thread_message_page`` pages backward (newest page first) and
    # returns every page internally ascending by ``seq``. Rows are sanitized
    # to public messages PER PAGE so the share cap counts what would
    # actually be published (tool rows and hidden/control messages don't
    # consume budget); page order flips only at the end so each page stays
    # chronological. Two bounds: the public-message cap enforces the share
    # contract, the raw-scan cap bounds work on row-heavy threads.
    pages: list[list[dict[str, Any]]] = []
    public_messages = 0
    raw_scan_budget = _RawMessageScanBudget(_SNAPSHOT_MAX_SCANNED_ROWS)
    before_seq: int | None = None
    while True:
        try:
            rows, has_more = await _scan_thread_message_page(
                thread_id,
                limit=_SNAPSHOT_SCAN_PAGE_SIZE,
                before_seq=before_seq,
                request=request,
                user_id=user_id,
                raw_scan_budget=raw_scan_budget,
            )
        except _RawMessageScanLimitExceeded as exc:
            logger.warning(
                "Share snapshot for thread %s exceeded the %d raw-scan safety bound; refusing to walk further",
                thread_id,
                _SNAPSHOT_MAX_SCANNED_ROWS,
            )
            raise ShareSnapshotTooLarge(
                thread_id,
                exc.scanned_rows,
                _SNAPSHOT_MAX_SCANNED_ROWS,
                limit_kind="raw-scan",
            ) from exc
        if not rows:
            break
        page_messages = [_public_message(row) for row in rows]
        page_messages = [message for message in page_messages if message is not None]
        if page_messages:
            pages.append(page_messages)
            public_messages += len(page_messages)
        if public_messages > _SNAPSHOT_MAX_MESSAGES:
            # ``has_more`` describes canonical page-eligible rows, not public
            # messages. Reject only after observing the first public message
            # beyond the cap; at exactly the cap we must keep scanning in case
            # all remaining rows are tool/hidden content.
            logger.warning(
                "Share snapshot for thread %s exceeded the %d public-message cap; refusing partial share",
                thread_id,
                _SNAPSHOT_MAX_MESSAGES,
            )
            raise ShareSnapshotTooLarge(thread_id, public_messages, _SNAPSHOT_MAX_MESSAGES)
        if not has_more:
            break
        before_seq = rows[0]["seq"]  # pages are ascending: row 0 is the oldest
    pages.reverse()

    # Snapshot-local, monotonic ids: the public contract must not leak run-event
    # ids or any store identifiers.
    messages: list[dict[str, Any]] = []
    for page in pages:
        for message in page:
            message["id"] = f"m{len(messages) + 1}"
            messages.append(message)

    logger.debug("Share snapshot for thread %s: %d visible messages", thread_id, len(messages))
    return {
        "version": 1,
        "messages": messages,
    }


def _public_message(row: dict[str, Any]) -> dict[str, Any] | None:
    """Map one scanned row to the strict public DTO, or None if not public."""
    from app.gateway.routers.thread_runs import _is_hidden_or_control_message, _message_type

    content = row.get("content")
    message_type = _message_type(content)
    if message_type not in ("human", "ai"):
        return None
    if _is_hidden_or_control_message(content):
        return None
    text = _strict_public_text(content)
    if message_type == "ai":
        text = _strip_think_blocks_outside_markdown_code(text)
    text = _neutralize_private_references(text)
    if not text.strip():
        return None
    return {
        "id": "",  # assigned chronologically after the page-order flip
        "role": "user" if message_type == "human" else "assistant",
        "content": text,
    }


def _strict_public_text(message: Any) -> str:
    """Extract only explicit renderable text, never reasoning/tool blocks."""
    raw_content = message.get("content") if isinstance(message, Mapping) else getattr(message, "content", None)
    if isinstance(raw_content, str):
        return raw_content
    if isinstance(raw_content, list):
        parts: list[str] = []
        for block in raw_content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, Mapping) and block.get("type") in {"text", "output_text"}:
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(part for part in parts if part)
    if isinstance(raw_content, Mapping) and raw_content.get("type") in {"text", "output_text"}:
        text = raw_content.get("text")
        return text if isinstance(text, str) else ""
    return ""


def _strip_think_blocks_outside_markdown_code(text: str) -> str:
    """Remove model reasoning while preserving literal tags in code examples."""
    protected: list[str] = []
    marker_prefix = "\x00deerflow-share-code-"
    while marker_prefix in text:
        marker_prefix += "_"

    def protect(match: re.Match[str]) -> str:
        marker = f"{marker_prefix}{len(protected)}\x00"
        protected.append(match.group(0))
        return marker

    without_fences = _FENCED_CODE_RE.sub(protect, text)
    without_code = _INLINE_CODE_RE.sub(protect, without_fences)
    stripped = strip_think_blocks(without_code)
    for index, code in enumerate(protected):
        stripped = stripped.replace(f"{marker_prefix}{index}\x00", code)
    return stripped


def _collapse_separators_with_offsets(text: str) -> tuple[str, list[tuple[int, int]]]:
    """Normalize escape and backslash separators for classification.

    Returns the normalized text plus, for every normalized character, the
    ``(first, last)`` original index it was produced from, so a match found in
    the normalized text can be cut out of the original — escaped bytes must
    never survive into the public output. A run of backslashes before a ``/``
    collapses into that single ``/`` (JSON ``\\/`` escapes at any depth);
    remaining backslashes are treated as Windows-style separators.
    """
    normalized: list[str] = []
    spans: list[tuple[int, int]] = []
    i = 0
    n = len(text)
    while i < n:
        char = text[i]
        if char == "\\":
            run_end = i
            while run_end < n and text[run_end] == "\\":
                run_end += 1
            if run_end < n and text[run_end] == "/":
                normalized.append("/")
                spans.append((i, run_end))
                i = run_end + 1
                continue
            for backslash in range(i, run_end):
                normalized.append("/")
                spans.append((backslash, backslash))
            i = run_end
            continue
        normalized.append(char)
        spans.append((i, i))
        i += 1
    return "".join(normalized), spans


def _decoded_reference(value: str) -> str:
    """Decode a bounded number of URL-encoding layers for classification."""
    decoded = value
    for _ in range(3):
        candidate = unquote(decoded)
        if candidate == decoded:
            break
        decoded = candidate
    normalized, _ = _collapse_separators_with_offsets(decoded)
    return normalized


def _is_private_reference(value: str) -> bool:
    decoded = _decoded_reference(value).lower()
    return "/mnt/user-data" in decoded or decoded.startswith("mnt/user-data") or re.search(r"/api/threads/[^/\s?#]+/(?:artifacts|uploads)(?:[/\s?#]|$)", decoded) is not None


def _neutralize_private_references(text: str) -> str:
    """Remove owner-only artifact paths from an otherwise public transcript.

    Classification runs on the separator-normalized shadow of the text (JSON
    ``\\/`` escapes, encoded or raw), while replacements are applied to the
    original text: normalized matching is what catches escaped private
    references, but public content must keep its exact original bytes.
    """
    normalized, spans = _collapse_separators_with_offsets(text)

    def original_span(start: int, end: int) -> tuple[int, int]:
        return spans[start][0], spans[end - 1][1] + 1

    edits: list[tuple[int, int, str]] = []

    def replace_markdown(match: re.Match[str]) -> None:
        target = match.group("target").strip()
        # A Markdown destination may carry an optional quoted title. The path
        # is always the first whitespace-delimited token.
        destination = target.split(maxsplit=1)[0] if target else ""
        if not _is_private_reference(destination):
            return
        label = match.group("label").strip()
        begin, stop = original_span(match.start(), match.end())
        edits.append((begin, stop, f"{label} {_PRIVATE_REFERENCE_MARKER}".strip()))

    def replace_raw(match: re.Match[str]) -> None:
        if not _is_private_reference(match.group(0)):
            return
        begin, stop = original_span(match.start(), match.end())
        edits.append((begin, stop, _PRIVATE_REFERENCE_MARKER))

    for match in _MARKDOWN_LINK_RE.finditer(normalized):
        replace_markdown(match)
    for match in _REFERENCE_RE.finditer(normalized):
        replace_raw(match)

    # Markdown links take precedence over raw references overlapping them,
    # matching the sequential regex passes this replaced.
    edits.sort(key=lambda edit: edit[0])
    parts: list[str] = []
    cursor = 0
    for begin, stop, replacement in edits:
        if begin < cursor:
            continue
        parts.append(text[cursor:begin])
        parts.append(replacement)
        cursor = stop
    parts.append(text[cursor:])
    return "".join(parts)


def sanitize_share_title(
    value: object,
    *,
    fallback: str = "Shared conversation",
    max_length: int = 512,
) -> str:
    """Return a bounded public title with owner-only references removed."""
    raw_title = str(value).strip() if value is not None else ""
    title = _neutralize_private_references(raw_title).strip()
    if not title:
        title = _neutralize_private_references(str(fallback)).strip()
    return (title or "Shared conversation")[:max_length]


async def resolve_share_title(thread_id: str, *, request: Any, fallback: str = "Shared conversation") -> str:
    """Best-effort thread title for the share record and public page."""
    from app.gateway.deps import get_thread_store

    try:
        meta = await get_thread_store(request).get(thread_id)
    except Exception:
        logger.warning("Could not read thread meta for share title of %s", thread_id, exc_info=True)
        return sanitize_share_title(None, fallback=fallback)
    title = None
    if isinstance(meta, Mapping):
        title = meta.get("display_name") or meta.get("title")
    return sanitize_share_title(title, fallback=fallback)
