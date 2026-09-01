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
# Word-initial branches (``api/…``, ``mnt/…``) only fire at a token boundary:
# ``fooapi/threads/…`` is public text, not a relative reference. The
# separator-led branches need no guard — a private path starting mid-token
# still classifies on its own shape.
_REFERENCE_RE = re.compile(
    r"(?:https?://|/|%[0-9A-Fa-f]{2}|(?<!\w)(?:api(?=/threads/)|mnt(?=[\\/]|%[0-9A-Fa-f]{2})))[^\s<>\"]+",
    re.IGNORECASE,
)
_PRIVATE_REFERENCE_MARKER = "[private artifact omitted]"

# Separator entities (round 8): ``/`` and ``\`` as HTML numeric/hex/named
# character references, and as JSON/JS ``\uXXXX`` escapes. CommonMark decodes
# character references and JSON consumers decode ``\uXXXX`` before display,
# so the classification shadow must collapse them like any other separator
# encoding while the original bytes stay cut out of the public output.
# Round-8 adversarial pass: encodings compose, so the entity decoder also
# yields the *introducers* — ``&#37;``/``&percnt;`` decode to ``%`` (feeding
# the percent-decoding path: ``&#37;2F`` → ``%2F`` → ``/``) and
# ``&#38;``/``&amp;`` decode to ``&`` so a following collapse pass unwraps
# ``&amp;#47;``; ``\u005c`` yields ``\`` so an adjacent ``u002f`` collapses
# on the next pass. That is why the collapse runs to a bounded fixpoint.
_HTML_ENTITY_RE = re.compile(
    r"&(?:#0*(?:47|92|37|38)|#x0*(?:2f|5c|25|26)|sol|bsol|percnt|amp);",
    re.IGNORECASE,
)
_ENTITY_CODEPOINTS = {0x2F: "/", 0x5C: "/", 0x25: "%", 0x26: "&"}
_ENTITY_NAMES = {"sol": "/", "bsol": "/", "percnt": "%", "amp": "&"}
_UNICODE_SEPARATOR_ESCAPE_RE = re.compile(r"u(?:002f|2f|\{0*2f\})", re.IGNORECASE)
_UNICODE_BACKSLASH_ESCAPE_RE = re.compile(r"u(?:005c|5c|\{0*5c\})", re.IGNORECASE)
# Depth bound for nested encodings, matching ``_decoded_reference``'s
# three-layer percent-decoding loop: ``&amp;amp;#47;`` needs all three.
_COLLAPSE_MAX_PASSES = 3


def _decode_entity(text: str, index: int) -> tuple[str, int] | None:
    """Decode one character reference at *index* into (char, end_index)."""
    match = _HTML_ENTITY_RE.match(text, index)
    if match is None:
        return None
    body = match.group(0)[1:-1].lower()
    if body.startswith("#"):
        digits = body[1:]
        base = 10
        if digits.startswith("x"):
            digits = digits[1:]
            base = 16
        char = _ENTITY_CODEPOINTS.get(int(digits.lstrip("0") or "0", base))
    else:
        char = _ENTITY_NAMES.get(body)
    if char is None:
        return None
    return char, match.end()


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


def _collapse_separators_once(text: str) -> tuple[str, list[tuple[int, int]]]:
    """One normalization pass: returns the pass's output plus, per output
    character, the ``(first, last)`` input index it was produced from."""
    normalized: list[str] = []
    spans: list[tuple[int, int]] = []
    i = 0
    n = len(text)
    while i < n:
        char = text[i]
        if char == "&":
            entity = _decode_entity(text, i)
            if entity is not None:
                decoded, end = entity
                normalized.append(decoded)
                spans.append((i, end - 1))
                i = end
                continue
        if char == "\\":
            run_end = i
            while run_end < n and text[run_end] == "\\":
                run_end += 1
            backslash_escape = _UNICODE_BACKSLASH_ESCAPE_RE.match(text, run_end)
            if backslash_escape is not None:
                # Yield the backslash itself: a u002f escape it introduces
                # collapses on the next pass.
                normalized.append("\\")
                spans.append((i, backslash_escape.end() - 1))
                i = backslash_escape.end()
                continue
            unicode_escape = _UNICODE_SEPARATOR_ESCAPE_RE.match(text, run_end)
            if unicode_escape is not None:
                normalized.append("/")
                spans.append((i, unicode_escape.end() - 1))
                i = unicode_escape.end()
                continue
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
        if char == "/":
            run_end = i
            while run_end < n and text[run_end] == "/":
                run_end += 1
            if run_end - i > 1:
                # A run of separators is one separator: raw ``//`` (and,
                # composed across passes, entity- or percent-decoded doubles)
                # must classify like the single ``/`` whose escaped forms
                # already collapse — the shipped nginx leaves ``merge_slashes``
                # on, so ``/api//threads//…`` reaches the real owner-scoped
                # route when followed.
                normalized.append("/")
                spans.append((i, run_end - 1))
                i = run_end
                continue
        normalized.append(char)
        spans.append((i, i))
        i += 1
    return "".join(normalized), spans


def _collapse_separators_with_offsets(text: str) -> tuple[str, list[tuple[int, int]]]:
    """Normalize escape and backslash separators for classification.

    Returns the normalized text plus, for every normalized character, the
    ``(first, last)`` original index it was produced from, so a match found in
    the normalized text can be cut out of the original — escaped bytes must
    never survive into the public output. A run of backslashes before a ``/``
    collapses into that single ``/`` (JSON ``\\/`` escapes at any depth);
    remaining backslashes are treated as Windows-style separators. Separator
    characters arriving as HTML character references (``&#47;``, ``&sol;``,
    …) or JSON/JS unicode escapes (``\\u002f``, any casing, any backslash
    depth) collapse the same way: both decode to a real separator before
    display, so neither may survive classification in encoded form.

    Because encodings compose (``&amp;#47;``, ``&#37;2F``, ``\\u005cu002f``),
    the pass runs repeatedly until it stabilizes (bounded by
    ``_COLLAPSE_MAX_PASSES``, the same depth the percent-decoding loop
    allows); spans are composed across passes so every cut still lands on
    original bytes.
    """
    normalized, spans = _collapse_separators_once(text)
    for _ in range(_COLLAPSE_MAX_PASSES - 1):
        collapsed, collapsed_spans = _collapse_separators_once(normalized)
        if collapsed == normalized:
            break
        normalized = collapsed
        spans = [(spans[first][0], spans[last][1]) for first, last in collapsed_spans]
    return normalized, spans


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


# Sentence punctuation that regex extraction greedily consumes but that is
# syntax, not part of the reference: the private-reference terminator must
# not be defeated by it, and it must survive into the public output.
# Markdown-structural characters count too: a closing backtick, emphasis
# marker, or bracket adjacency after ``artifacts``/``uploads`` must not
# defeat the terminator (round 7) — those bytes stay in the public output
# because only the classification/cut bound is trimmed.
_REFERENCE_TRAILING_PUNCTUATION = ".,;:!?)]}\"'`*_~(|[<"

# Where the cut stops while a matched reference runs past its structural
# end (round 8): prose and markdown delimiters terminate the private path
# (``/uploads`'s`` and ``/uploads,then`` must keep their suffix bytes), while
# URL structure (``/``, ``?``, ``#``, consumed by the scan before this set
# is consulted) continues it so a query string or nested path can never
# survive the cut. Dots continue (filenames) and are handled by the
# trailing-punctuation trim instead. A terminator run only ends the cut
# when what follows it is not itself private: tool-style output joins
# several paths with commas/semicolons/parens inside one whitespace-free
# token, and the first cut must not publish the tail items.
_REFERENCE_CUT_TERMINATORS = ",;:!?)\\]}\"'`*_~(|[<"

# Owner-scoped API surface (round 8): every ``/api/threads/{id}/<segment>``
# route is private, not just the artifacts/uploads pair — each carries the
# internal thread id and several are owner-only exports. The leading
# separator is optional so a relative Markdown destination or a bare path
# in running text classifies identically instead of publishing a
# live-looking private link.
_API_THREAD_REFERENCE_RE = re.compile(r"(?:^|/)api/threads/[^/?#\s]+/", re.IGNORECASE)
_MNT_USER_DATA_RE = re.compile(r"(?:^|/)mnt/user-data", re.IGNORECASE)


def _trim_reference_punctuation(value: str) -> str:
    return value.rstrip(_REFERENCE_TRAILING_PUNCTUATION)


def _is_private_reference(value: str) -> bool:
    decoded = _trim_reference_punctuation(_decoded_reference(value)).lower()
    return _MNT_USER_DATA_RE.search(decoded) is not None or _API_THREAD_REFERENCE_RE.search(decoded) is not None


def _private_reference_cut_end(value: str) -> int | None:
    """Index just past the private path inside *value* (a normalized-shadow
    slice): the path continues through URL structure and in-segment bytes,
    and stops at the first prose/markdown terminator or whitespace — unless
    the terminator only joins this private path to another one, in which
    case the cut continues through the joined items."""
    prefix = _API_THREAD_REFERENCE_RE.search(value) or _MNT_USER_DATA_RE.search(value)
    if prefix is None:
        return None
    end = prefix.end()
    n = len(value)
    while end < n:
        char = value[end]
        if char in "/?#":
            end += 1
            continue
        if char in _REFERENCE_CUT_TERMINATORS or char.isspace():
            probe = end
            while probe < n and value[probe] in _REFERENCE_CUT_TERMINATORS:
                probe += 1
            if probe < n and not value[probe].isspace() and _is_private_reference(value[probe:]):
                end = probe
                continue
            break
        end += 1
    return end


def _neutralize_private_references(text: str) -> str:
    """Remove owner-only artifact paths from an otherwise public transcript.

    Classification runs on the separator-normalized shadow of the text (JSON
    ``\\/`` escapes, percent-encoding, HTML character references, and
    ``\\uXXXX`` unicode escapes — raw or in any combination), while
    replacements are applied to the original text: normalized matching is
    what catches escaped private references, but public content must keep
    its exact original bytes. The cut spans exactly the private path and
    stops at the first structural terminator, so public prose after the
    reference survives.
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
        destination_is_private = _is_private_reference(destination)
        label_is_private = _is_private_reference(match.group("label"))
        if not destination_is_private and not label_is_private:
            return
        begin, stop = original_span(match.start(), match.end())
        if label_is_private:
            # The leak is the LABEL itself (round 7): publishing it next to
            # the marker would defeat the point — collapse the whole link.
            # That holds even when the destination is private too (round 9):
            # falling through to the destination branch would republish the
            # private label verbatim beside the marker.
            edits.append((begin, stop, _PRIVATE_REFERENCE_MARKER))
            return
        # The label must come from the original bytes, not the normalized
        # shadow: a label containing backslashes would otherwise publish
        # its separator-normalized form (``C:/Users/bob`` for ``C:\Users\bob``).
        label_begin, label_stop = original_span(match.start("label"), match.end("label"))
        label = text[label_begin:label_stop].strip()
        edits.append((begin, stop, f"{label} {_PRIVATE_REFERENCE_MARKER}".strip()))

    def replace_raw(match: re.Match[str]) -> None:
        value = match.group(0)
        if not _is_private_reference(value):
            return
        # The cut spans exactly the private path: it ends at the first
        # structural terminator (URL structure continues the path, prose
        # delimiters stay in the public output), and trailing sentence
        # punctuation is kept out of the cut so the public text keeps its
        # own ``.``/``,``/``)`` after the marker.
        cut_end = _private_reference_cut_end(value)
        if cut_end is None:
            cut_end = len(value)
        kept = _trim_reference_punctuation(value[:cut_end])
        stop_index = match.start() + len(kept)
        begin, stop = original_span(match.start(), stop_index)
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


def resanitize_share_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Re-apply the private-reference neutralizer to a stored snapshot.

    Snapshots are immutable once minted, so a message that still carries an
    owner-only path — written through a sanitizer defect or before the rules
    were tightened — would otherwise stay exposed on every public read until
    the share is revoked. The public read boundary runs this pass next to
    ``sanitize_share_title`` for the same reason.
    """
    messages = snapshot.get("messages")
    if not isinstance(messages, list):
        return snapshot
    sanitized_messages: list[Any] = []
    changed = False
    for message in messages:
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            sanitized = _neutralize_private_references(message["content"])
            if sanitized != message["content"]:
                changed = True
                message = {**message, "content": sanitized}
        sanitized_messages.append(message)
    return {**snapshot, "messages": sanitized_messages} if changed else snapshot


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
