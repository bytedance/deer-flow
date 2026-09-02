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
# Word-initial branches (``api/…``, ``mnt/…``) anchor a token on any
# separator-ish follower — raw, backslash, or percent; layers mix freely
# (literal ``api`` ahead of a percent-encoded ``threads``). No lookbehind
# here: admissibility is judged downstream in fed coordinates, where an
# encoded glue character (``&#46;api/…``) cannot masquerade as the pinned
# ``foo.api`` identifier shape. The separator-led branches need no guard —
# a private path starting mid-token still classifies on its own shape.
_REFERENCE_RE = re.compile(
    r"(?:https?://|/|%[0-9A-Fa-f]{2}|(?:api|mnt)(?=[/\\%]))[^\s<>\"]+",
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
# Any character reference decodes in the shadow, not only separators: the
# frontend's CommonMark renderer (micromark via streamdown) decodes ``&#45;``
# back into a path exactly as readily as ``&#47;``, so one entity-encoded
# letter would otherwise shield a whole private phrase. The separator
# codepoints keep their special mappings (a decoded backslash is a
# separator, ``%``/``&`` feed the percent/entity paths); everything else
# lands literally for classification. Public text keeps its original bytes
# either way — decoding only feeds classification.
_HTML_ENTITY_RE = re.compile(
    r"&(?:#0*\d+|#x0*[0-9a-f]+|sol|bsol|percnt|amp);",
    re.IGNORECASE,
)
_ENTITY_CODEPOINTS = {0x2F: "/", 0x5C: "/", 0x25: "%", 0x26: "&"}
_ENTITY_NAMES = {"sol": "/", "bsol": "/", "percnt": "%", "amp": "&"}
# ``uXXXX`` / ``u{X...}`` escapes decode the same way (JSON consumers decode
# letters as readily as separators); the 2-digit form keeps round-8 parity.
_UNICODE_ESCAPE_RE = re.compile(r"u(?:\{0*[0-9a-f]{1,6}\}|[0-9a-f]{4}|[0-9a-f]{2})", re.IGNORECASE)
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
        codepoint = int(digits.lstrip("0") or "0", base)
        char = _ENTITY_CODEPOINTS.get(codepoint)
        if char is None:
            if codepoint <= 0 or codepoint > 0x10FFFF or 0xD800 <= codepoint <= 0xDFFF:
                return None
            char = chr(codepoint)
    else:
        char = _ENTITY_NAMES.get(body)
    if char is None:
        return None
    return char, match.end()


def _decode_unicode_escape(token: str) -> str | None:
    """Decode one matched ``uXXXX`` / ``u{X...}`` escape to its character."""
    body = token[1:]
    if body.startswith("{"):
        body = body[1:-1]
    codepoint = int(body.lstrip("0") or "0", 16)
    if codepoint == 0x5C:
        return "\\"
    if codepoint <= 0 or codepoint > 0x10FFFF or 0xD800 <= codepoint <= 0xDFFF:
        return None
    return chr(codepoint)


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
            unicode_escape = _UNICODE_ESCAPE_RE.match(text, run_end)
            decoded_escape = _decode_unicode_escape(unicode_escape.group(0)) if unicode_escape is not None else None
            if decoded_escape is not None:
                # A decoded ``\u005c`` yields the backslash itself: a
                # ``u002f`` escape it introduces collapses on the next pass.
                # Every other codepoint lands literally in the shadow.
                normalized.append(decoded_escape)
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
            if run_end - i > 1 and (i == 0 or text[i - 1] != ":"):
                # A run of separators is one separator: raw ``//`` (and,
                # composed across passes, entity- or percent-decoded doubles)
                # must classify like the single ``/`` whose escaped forms
                # already collapse — the shipped nginx leaves ``merge_slashes``
                # on, so ``/api//threads//…`` reaches the real owner-scoped
                # route when followed. The run directly after ``:`` is a URL
                # scheme separator, not a path one: keeping it lets the
                # ``https?://`` match cover the full URL (and a public host
                # keep its bytes while only a private-shaped subpath is cut).
                normalized.append("/")
                spans.append((i, run_end - 1))
                i = run_end
                continue
        normalized.append(char)
        spans.append((i, i))
        i += 1
    return "".join(normalized), spans


def _remove_dot_segments_once(text: str, spans: list[tuple[int, int]]) -> tuple[str, list[tuple[int, int]]]:
    """Resolve ``.``/``..``/``%2E`` segments away (RFC 3986 dot-segment
    removal — browser URL shortening and the nginx URI normalizer both do
    this, so ``/api/a/b/../../threads/…`` reaches the owner-scoped route).
    Stack-shaped, matching real resolution: N ``..`` cancel N preceding
    segments, so ``ab/cd/..`` stays ``ab`` (public) while ``a/b/../..``
    cancels to nothing. A cancelled segment's original bytes leave the
    shadow exactly like the dot that cancelled them; ``%2E`` variants are
    recognized because the shadow does not percent-decode.

    Resolution never crosses a query or fragment: a ``?`` or ``#`` starts
    an opaque tail (reset at whitespace, where a new path may follow in
    prose). Cancellation itself is segment-bounded and character-blind —
    a cancelled segment may contain any legal path character, spaces
    included — because classification runs against both the resolved and
    the as-written shadow: aggressive popping can never erase a phrase the
    unresolved view still carries."""
    out: list[str] = []
    out_spans: list[tuple[int, int]] = []
    opaque = False
    i = 0
    n = len(text)
    while i < n:
        char = text[i]
        if char.isspace():
            opaque = False
        elif char in "?#":
            opaque = True
        if not opaque and char == "/":
            j = i + 1
            while j < n and text[j] not in "/?#" and not text[j].isspace():
                j += 1
            segment = text[i + 1 : j].lower()
            if segment in (".", "%2e"):
                i = j
                continue
            if segment in ("..", "%2e%2e", ".%2e", "%2e."):
                while out and out[-1] != "/":
                    out.pop()
                    out_spans.pop()
                if out:
                    out.pop()
                    out_spans.pop()
                i = j
                continue
        out.append(char)
        out_spans.append(spans[i])
        i += 1
    return "".join(out), out_spans


def _collapse_separators_with_offsets(text: str, *, resolve_dots: bool = True) -> tuple[str, list[tuple[int, int]]]:
    """Normalize escape and backslash separators for classification.

    Returns the normalized text plus, for every normalized character, the
    ``(first, last)`` original index it was produced from, so a match found in
    the normalized text can be cut out of the original — escaped bytes must
    never survive the public output. A run of backslashes before a ``/``
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
    original bytes. Each round also resolves dot segments away, so decodes
    that reveal ``.``/``..`` compositions (``&#46;&#46;``, ``%2E``) are
    normalized like their resolved forms; ``resolve_dots=False`` yields the
    as-written view for the dual-shadow classification.
    """
    if resolve_dots:
        normalized, spans = _remove_dot_segments_once(text, [(index, index) for index in range(len(text))])
    else:
        normalized, spans = text, [(index, index) for index in range(len(text))]
    for _ in range(_COLLAPSE_MAX_PASSES):
        collapsed, collapsed_spans = _collapse_separators_once(normalized)
        if resolve_dots:
            collapsed, collapsed_spans = _remove_dot_segments_once(collapsed, collapsed_spans)
        if collapsed == normalized:
            break
        normalized = collapsed
        # The dot pass appends the collapsed spans it read, so one
        # indirection through ``spans`` reaches original bytes either way.
        spans = [(spans[first][0], spans[last][1]) for first, last in collapsed_spans]
    return normalized, spans


def _decoded_reference(value: str, *, resolve_dots: bool = True) -> str:
    """Decode a bounded number of URL-encoding layers for classification."""
    decoded = value
    for _ in range(3):
        candidate = unquote(decoded)
        if candidate == decoded:
            break
        decoded = candidate
    normalized, _ = _collapse_separators_with_offsets(decoded, resolve_dots=resolve_dots)
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
#
# The phrase boundary is judged in the coordinates of the bytes actually
# fed to classification — the phrase starts wherever any non-word,
# non-dot, non-hyphen character (or nothing) precedes it there. Any join
# character can head a whitespace-free token (``/docs&api/…``, fullwidth
# commas), while ``foo_api``/``foo.api``/``foo-mnt`` stay public
# identifiers. Judging pre-decode matters: an encoded glue character
# (``&#46;api/…`` — the original ends in ``;``, a boundary) must not decode
# into a ``.``/word char and shield the phrase behind the lookbehind. The
# span-checked sites use the lookbehind-free cores plus ``_boundary_ok``;
# the anchored probe keeps the lookbehind form (its window starts at a
# boundary by construction).
_BOUNDARY_BLOCK_RE = re.compile(r"[\w.\-]\Z")
_CORE_API_THREAD_REFERENCE_RE = re.compile(r"api/threads/[^/?#\s]+/", re.IGNORECASE)
_CORE_MNT_USER_DATA_RE = re.compile(r"mnt/user-data", re.IGNORECASE)
_API_THREAD_REFERENCE_RE = re.compile(r"(?<![\w.\-])api/threads/[^/?#\s]+/", re.IGNORECASE)
_MNT_USER_DATA_RE = re.compile(r"(?<![\w.\-])mnt/user-data", re.IGNORECASE)


def _boundary_ok(fed_text: str, fed_spans: list[tuple[int, int]], shadow_index: int) -> bool:
    """Is the phrase starting at ``shadow_index`` boundary-admissible?

    ``fed_spans`` map shadow positions back into ``fed_text`` — the bytes
    classification was fed (original text for the shadow pipeline,
    percent-decoded text inside the classifier). The byte just before the
    phrase's first character decides, so decoding can never manufacture a
    ``foo.api``-shaped shield that the original bytes do not carry."""
    origin = fed_spans[shadow_index][0]
    if origin <= 0:
        return True
    return _BOUNDARY_BLOCK_RE.match(fed_text[origin - 1]) is None


def _trim_reference_punctuation(value: str) -> str:
    return value.rstrip(_REFERENCE_TRAILING_PUNCTUATION)


def _is_private_reference(value: str) -> bool:
    """Dual-view, mirroring the dual shadow: the dot-resolved decode catches
    references that only reach the surface through ``.``/``..`` cancellation,
    and the as-written decode guarantees resolution can never erase a
    phrase — browsers do not entity-decode URLs, so an entity dot-tail
    (``…/u/&#46;&#46;``) stays literal in the href and resolves to the
    owner-scoped route even though the resolved view popped the segment.
    Phrase hits use the lookbehind-free cores with the boundary judged in
    fed coordinates (see ``_boundary_ok``)."""
    for resolve_dots in (True, False):
        fed = value
        for _ in range(3):
            candidate = unquote(fed)
            if candidate == fed:
                break
            fed = candidate
        shadow, fed_spans = _collapse_separators_with_offsets(fed, resolve_dots=resolve_dots)
        for core in (_CORE_API_THREAD_REFERENCE_RE, _CORE_MNT_USER_DATA_RE):
            for match in core.finditer(shadow):
                if _boundary_ok(fed, fed_spans, match.start()):
                    return True
    return False


def _phrase_end(value: str, end: int) -> int:
    """Extend a private phrase's cut through in-segment bytes: URL structure
    (``/``, ``?``, ``#``) continues the path, prose/markdown terminators and
    whitespace end it."""
    n = len(value)
    while end < n:
        char = value[end]
        if char in "/?#":
            end += 1
            continue
        if char in _REFERENCE_CUT_TERMINATORS or char.isspace():
            break
        end += 1
    return end


def _starts_with_private_reference(window: str) -> bool:
    """Anchored classification: does *window* begin with a private phrase?

    Used by the segment walker's percent probe. Percent-encoded phrases
    never decode in the shadow (their decoded positions cannot map back to
    original bytes), so after each terminator run the upcoming window is
    decoded for classification alone. The window is a slice of the
    separator-normalized shadow, so entities and unicode escapes are
    already decoded and only percent layers remain — a cheap bounded
    unquote plus slash-run collapse; no offsets are needed for a yes/no."""
    decoded = window
    for _ in range(3):
        candidate = unquote(decoded)
        if candidate == decoded:
            break
        decoded = candidate
    decoded = _PROBE_SLASH_RUN_RE.sub("/", decoded)
    if "/." in decoded:
        decoded, _ = _remove_dot_segments_once(decoded, [(index, index) for index in range(len(decoded))])
    # Leading separators are stripped before the anchored match: the phrase
    # regexes use a lookbehind boundary, so they match at the phrase itself
    # (a protocol-relative ``//mnt/…`` strips to the phrase and classifies
    # like the absolute form).
    decoded = _trim_reference_punctuation(decoded).lstrip("/").lower()
    return _MNT_USER_DATA_RE.match(decoded) is not None or _API_THREAD_REFERENCE_RE.match(decoded) is not None


# Probe windows may contain a URL scheme (``https://…`` tail); its ``//``
# is not a path separator.
_PROBE_SLASH_RUN_RE = re.compile(r"(?<!:)/{2,}")


# One bounded probe per terminator join keeps the walk linear — re-decoding
# the whole tail at every terminator was quadratic on joined lists. The
# window must still admit a fully-encoded phrase (three percent layers ≈ 8
# bytes per decoded char, so a ``uuid`` + segment needs several hundred).
_SEGMENT_PROBE_WINDOW = 1024


def _private_reference_segments(
    value: str,
    *,
    conservative_gaps: bool = True,
    fed_text: str,
    fed_spans: list[tuple[int, int]],
    offset: int,
) -> list[tuple[int, int]]:
    """Shadow-coordinate ``[start, end)`` spans of every private phrase in
    one matched token. Public head/middle/tail bytes between the segments
    are part of no span and survive the cut; the joining terminators stay
    public too. ``fed_text``/``fed_spans``/``offset`` anchor the token in
    the coordinates classification was fed, so every candidate's phrase
    boundary is judged on pre-decode bytes (``_boundary_ok``) — an encoded
    glue character cannot decode into a ``foo.api``-shaped shield.

    Percent-encoded phrases never decode in the shadow (their decoded
    positions cannot map back to original bytes), so they are caught two
    ways: an anchored probe at the terminator run that directly follows a
    cut, and — because junk items can shield a later encoded tail from the
    anchored probe — classification of every unconsumed gap, cut
    conservatively when its decoded form carries a private phrase. The
    gap backstop belongs to the resolved shadow; ``conservative_gaps=False``
    (the as-written shadow) limits itself to precisely positioned segments
    so its cuts cannot swallow public heads the resolved view already cut
    precisely."""
    segments: list[tuple[int, int]] = []
    # Both match streams are computed once: re-searching per iteration
    # rescans the token tail every time and is quadratic on joined lists.
    api_matches = [m for m in _CORE_API_THREAD_REFERENCE_RE.finditer(value) if _boundary_ok(fed_text, fed_spans, offset + m.start())]
    mnt_matches = [m for m in _CORE_MNT_USER_DATA_RE.finditer(value) if _boundary_ok(fed_text, fed_spans, offset + m.start())]
    api_index = 0
    mnt_index = 0
    pos = 0
    n = len(value)

    def next_match(start: int) -> tuple[int, int] | None:
        nonlocal api_index, mnt_index
        while api_index < len(api_matches) and api_matches[api_index].start() < start:
            api_index += 1
        while mnt_index < len(mnt_matches) and mnt_matches[mnt_index].start() < start:
            mnt_index += 1
        options: list[tuple[int, int]] = []
        if api_index < len(api_matches):
            options.append((api_matches[api_index].start(), api_matches[api_index].end()))
        if mnt_index < len(mnt_matches):
            options.append((mnt_matches[mnt_index].start(), mnt_matches[mnt_index].end()))
        return min(options) if options else None

    def cut_gap(start: int, stop: int) -> None:
        begin = start
        while begin < stop and value[begin] in _REFERENCE_CUT_TERMINATORS:
            begin += 1
        if begin < stop and _is_private_reference(value[begin:stop]):
            segments.append((begin, stop))

    while pos < n:
        candidate = next_match(pos)
        probe = pos
        while probe < n and value[probe] in _REFERENCE_CUT_TERMINATORS:
            probe += 1
        # A regex phrase sitting exactly at the probe position — bare, or
        # behind its own single separator — proves itself without any
        # window decode. This is the common joined-list shape; decoding per
        # item here was the quadratic hotspot.
        if candidate is not None and (candidate[0] == probe or (candidate[0] == probe + 1 and value[probe] == "/")):
            probed = True
        else:
            probed = probe > pos and probe < n and not value[probe].isspace() and _boundary_ok(fed_text, fed_spans, offset + probe) and _starts_with_private_reference(value[probe : probe + _SEGMENT_PROBE_WINDOW])
        if candidate is None and not probed:
            break
        # A regex phrase starting strictly before the probe wins (public
        # head keeps its comma); a tie — the phrase directly follows the
        # terminator run behind its own separator — goes to the probe, which
        # cuts the separator with the phrase (`,/mnt/…` → `,` + marker).
        if candidate is not None and (not probed or candidate[0] < probe):
            start, walk_from = candidate
            if conservative_gaps:
                cut_gap(pos, start)
            if start == 1 and value[0] == "/":
                # A standalone reference's own leading separator belongs to
                # the cut; a separator deeper in the token is public
                # structure introducing the phrase (a public host keeps the
                # slash before a private-shaped subpath).
                start = 0
            end = _phrase_end(value, walk_from)
            if end <= start:
                pos = start + 1
                continue
            segments.append((start, end))
            pos = end
        else:
            end = _phrase_end(value, probe)
            segments.append((probe, end))
            pos = end
    if conservative_gaps:
        cut_gap(pos, n)
    return segments


def _neutralize_private_references(text: str) -> str:
    """Remove owner-only artifact paths from an otherwise public transcript.

    Classification runs on the separator-normalized shadow of the text (JSON
    ``\\/`` escapes, percent-encoding, HTML character references, and
    ``\\uXXXX`` unicode escapes — raw or in any combination, decoding every
    character they encode, not just separators), while replacements are
    applied to the original text: normalized matching is what catches
    escaped private references, but public content must keep its exact
    original bytes. Each private phrase is cut on its own segment, so public
    head/middle/tail bytes inside one whitespace-free token survive.

    One application may still leave work — a markdown edit that shadows an
    overlapping raw match drops it for that pass — so the pass re-applies on
    its own output until it stabilizes, bounded by ``_COLLAPSE_MAX_PASSES``.
    """
    for _ in range(_COLLAPSE_MAX_PASSES):
        result = _neutralize_private_references_once(text)
        if result == text:
            return result
        text = result
    return text


def _collect_edits(text: str, normalized: str, spans: list[tuple[int, int]], edits: list[tuple[int, int, str]], *, conservative_gaps: bool = True) -> None:
    """Collect private-reference cuts for one shadow of ``text`` into
    ``edits`` (original-text coordinates). The conservative backstops
    (whole-gap and whole-token cuts for phrases the shadow cannot position)
    belong to the resolved shadow only — the as-written shadow is there for
    precise segments the resolution erased, and its wider cuts would
    swallow public heads the resolved view already cut precisely."""

    def original_span(start: int, end: int) -> tuple[int, int]:
        return spans[start][0], spans[end - 1][1] + 1

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
        # A word-branch token starting mid-word (``fooapi/threads/…``) is a
        # public fragment: the classifier sees its slice starting at
        # ``api`` and would misread slice-start as a boundary, so the fed-
        # coordinate check gates the whole token, fallback included.
        if value[:3].lower() in ("api", "mnt") and not _boundary_ok(text, spans, match.start()):
            return
        # Every private phrase in the token is cut on its own segment, so a
        # public head/middle/tail (and the joining terminators) survive. The
        # whole-token fallback still covers phrases the shadow cannot
        # position at all — percent-encoding decodes for classification, not
        # in the shadow, and a probe window may have missed the shape.
        segments = _private_reference_segments(
            value,
            conservative_gaps=conservative_gaps,
            fed_text=text,
            fed_spans=spans,
            offset=match.start(),
        )
        if not segments:
            if not _is_private_reference(value):
                return
            end = _phrase_end(value, 0)
            kept = _trim_reference_punctuation(value[:end])
            begin, stop = original_span(match.start(), match.start() + len(kept))
            if not conservative_gaps and (
                # As-written fallback: only cover tokens the resolved pass
                # left untouched — wherever resolution positioned a precise
                # cut, this wider cut must not swallow its public head — and
                # only cut a prefix that is itself private, never a public
                # first item of a mixed token whose private content lives
                # behind a terminator.
                any(e_begin < stop and begin < e_stop for e_begin, e_stop, _ in edits) or not kept or not _is_private_reference(kept)
            ):
                return
            if kept:
                edits.append((begin, stop, _PRIVATE_REFERENCE_MARKER))
            return
        for start, end in segments:
            # Trailing sentence punctuation is kept out of the cut so the
            # public text keeps its own ``.``/``,``/``)`` after the marker.
            kept = _trim_reference_punctuation(value[start:end])
            if not kept:
                continue
            stop_index = match.start() + start + len(kept)
            begin, stop = original_span(match.start() + start, stop_index)
            edits.append((begin, stop, _PRIVATE_REFERENCE_MARKER))

    for match in _MARKDOWN_LINK_RE.finditer(normalized):
        replace_markdown(match)
    for match in _REFERENCE_RE.finditer(normalized):
        replace_raw(match)


def _neutralize_private_references_once(text: str) -> str:
    """One classification-and-cut pass over ``text`` (see the wrapper).

    Dual shadow: cuts are collected against both the dot-resolved view
    (catching references that only reach the owner-scoped surface through
    ``.``/``..`` cancellation) and the as-written view (guaranteeing that
    aggressive resolution can never erase a phrase — a ``..`` cancelling
    the phrase's own final segment, or popping through prose). A phrase in
    either shadow is cut; the as-written pass carries no conservative
    backstops, so its segments can never swallow public heads the resolved
    view already cut precisely."""
    edits: list[tuple[int, int, str]] = []
    for normalized, spans, conservative_gaps in (
        (*_collapse_separators_with_offsets(text), True),
        (*_collapse_separators_with_offsets(text, resolve_dots=False), False),
    ):
        _collect_edits(text, normalized, spans, edits, conservative_gaps=conservative_gaps)

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
