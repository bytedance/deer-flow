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
import unicodedata
from bisect import bisect_left
from collections.abc import Iterator, Mapping
from typing import Any
from urllib.parse import unquote

from deerflow.config.agents_config import AGENT_NAME_PATTERN
from deerflow.utils.thread_id import THREAD_ID_PATTERN

logger = logging.getLogger(__name__)

_SNAPSHOT_SCAN_PAGE_SIZE = 200
_SNAPSHOT_MAX_MESSAGES = 2000
# Total renderable-text budget, measured in UTF-8 encoded bytes (round 11):
# the persisted snapshot duplicates the whole transcript and every anonymous
# resolution deserializes AND re-sanitizes it, so a "few huge messages"
# thread must fail 413 exactly like a many-messages one instead of turning
# each public read into unbounded work. Encoded bytes, not code points: an
# astral-plane character costs four bytes on disk (more once JSON-escaped),
# so a code-point budget would under-count emoji-heavy transcripts 4x+.
_SNAPSHOT_MAX_RENDERED_BYTES = 2 * 1024 * 1024
# Independent safety bound on RAW scanned rows: a tool-heavy thread can carry
# far more rows than public messages, and without this the backward scan
# would walk an unbounded history while the public-message count stays under
# the share cap.
_SNAPSHOT_MAX_SCANNED_ROWS = 50_000
_THINK_OPEN_PREFIX_RE = re.compile(r"<think\b", re.IGNORECASE)
_THINK_CLOSE_PREFIX_RE = re.compile(r"</think", re.IGNORECASE)
# --- Block-structure classification for code protection ------------------
# The think-strip may only preserve what the Markdown renderer will also
# render as code, so code regions are recognized per CommonMark block
# rules instead of one greedy fence regex: an opener's info string must
# not contain a backtick (backtick fences only), a closer needs at least
# the opener's length (not exactly it), fences inside raw-HTML blocks are
# not fences, and every block-interrupting line ends a paragraph (an
# inline span can never reach across one).
_FENCE_OPEN_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_HEADING_RE = re.compile(r"^ {0,3}#{1,6}(?:[ \t]|$)")
_BLOCKQUOTE_RE = re.compile(r"^ {0,3}>")
_QUOTE_DEPTH_MARKER_RE = re.compile(r" {0,3}>[ \t]?")
_LIST_ITEM_RE = re.compile(r"^ {0,3}(?:[-+*]|\d{1,9}[.)])[ \t]")
_CONTAINER_PADDING_RE = re.compile(r"[ \t]*")
_CONTAINER_QUOTE_MARKER_RE = re.compile(r">[ \t]?")
_CONTAINER_LIST_MARKER_RE = re.compile(r"(?:[-+*]|\d{1,9}[.)])[ \t]+")
_THEMATIC_RE = re.compile(r"^ {0,3}(?:(?:-[ \t]*){3,}|(?:\*[ \t]*){3,}|(?:_[ \t]*){3,})$")
_SETEXT_UNDERLINE_RE = re.compile(r"^ {0,3}(?:=+|-+)[ \t]*$")
# CommonMark type-1 start: the tag name must be followed by a space, a
# tab, `>`, or the end of the line — a word boundary lets `<script=foo`
# through and opens a phantom block that swallows the real code fence.
_HTML_TYPE1_OPEN_RE = re.compile(r"^ {0,3}<(script|pre|style|textarea)(?:[ \t]|>|$)", re.IGNORECASE)

_HTML_TYPE2_OPEN_RE = re.compile(r"^ {0,3}<!--")
_HTML_TYPE2_CLOSE = "-->"
_HTML_TYPE3_OPEN_RE = re.compile(r"^ {0,3}<\?")
_HTML_TYPE3_CLOSE = "?>"
# CommonMark type-4 declarations require an uppercase ASCII letter after
# `<!`; a lowercase `<!foo` is ordinary text, not a declaration block.
_HTML_TYPE4_OPEN_RE = re.compile(r"^ {0,3}<![A-Z]")
_HTML_TYPE4_CLOSE = ">"
# CommonMark type-6 block tags (spec'd list; the block ends at a blank line).
_HTML_TYPE6_TAGS = (
    "address",
    "article",
    "aside",
    "base",
    "basefont",
    "blockquote",
    "body",
    "caption",
    "center",
    "col",
    "colgroup",
    "dd",
    "details",
    "dialog",
    "dir",
    "div",
    "dl",
    "dt",
    "fieldset",
    "figcaption",
    "figure",
    "footer",
    "form",
    "frame",
    "frameset",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "head",
    "header",
    "hr",
    "html",
    "iframe",
    "legend",
    "li",
    "link",
    "main",
    "menu",
    "menuitem",
    "nav",
    "noframes",
    "ol",
    "optgroup",
    "option",
    "p",
    "param",
    "search",
    "section",
    "summary",
    "table",
    "tbody",
    "td",
    "tfoot",
    "th",
    "thead",
    "title",
    "tr",
    "track",
    "ul",
)
# CommonMark type-6 covers *closing* tags of the listed elements too:
# `</div>` alone on a line is a type-6 opener, and types 1-6 interrupt an
# open paragraph (type 7 cannot) — misreading a closing tag as type 7
# would let the fence behind it open real code and preserve reasoning.
_HTML_TYPE6_OPEN_RE = re.compile(
    r"^ {0,3}</?(" + "|".join(_HTML_TYPE6_TAGS) + r")(?:[ \t]|/?>|$)",
    re.IGNORECASE,
)
_HTML_TYPE1_CLOSE_RE = re.compile(r"</(script|pre|style|textarea)>", re.IGNORECASE)
_HTML_TYPE5_OPEN_RE = re.compile(r"^ {0,3}<!\[CDATA\[")
_HTML_TYPE5_CLOSE = "]]>"
# Type 7: a complete open or closing tag alone on a line (checked only when
# no other HTML kind matches — a `<script>`/`<div>` line is type 1/6, not 7).
# The complete HTML tag grammar decides: an opener is type 7 only if the
# line *is* a well-formed tag, so a syntactically invalid `<span =foo>` is
# an ordinary paragraph line and the fence behind it is a real code fence.
# Quoted attribute values may carry `>` (markdown-it accepts
# `<span title="a>b">` as a type-7 block), which the grammar tracks.
_HTML_TAG_NAME = r"[A-Za-z][A-Za-z0-9-]*"
_HTML_ATTR_NAME = r"[A-Za-z_:][A-Za-z0-9_.:-]*"
_HTML_UNQUOTED_ATTR_VALUE = r"[^ \t\n\"'=<>`]+"
_HTML_ATTR = (
    rf"{_HTML_ATTR_NAME}"
    rf"(?:[ \t]*=[ \t]*(?:{_HTML_UNQUOTED_ATTR_VALUE}|'[^']*'|\"[^\"]*\"))?"
)
_HTML_OPEN_TAG_RE = re.compile(rf"<{_HTML_TAG_NAME}(?:[ \t]+{_HTML_ATTR})*[ \t]*/?>")
_HTML_CLOSE_TAG_RE = re.compile(rf"</{_HTML_TAG_NAME}[ \t]*>")


def _is_complete_tag_line(content: str) -> bool:
    indent = 0
    while indent < len(content) and content[indent] == " " and indent < 3:
        indent += 1
    body = content[indent:].strip()
    if not body:
        return False
    return _HTML_OPEN_TAG_RE.fullmatch(body) is not None or _HTML_CLOSE_TAG_RE.fullmatch(body) is not None


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
_ENTITY_CODEPOINTS = {0x2F: "/", 0x5C: "/", 0x25: "%", 0x26: "&"}
# Named references: the full HTML5/CommonMark table has 2200+ entries, but
# only the entities decoding to a single ASCII character can manufacture a
# path shape — separators (``sol``/``bsol``), introducers (``percnt``/
# ``amp``), dots (``period``), boundary/terminator characters (``num``/
# ``quest``/``colon``/``comma``/...), and identifier characters
# (``lowbar``). Everything else decodes to non-ASCII, lands literally for
# classification (round-9 design), and can at most extend an id run — so
# this enumerable single-ASCII set is the complete attack surface
# (``&period;&period;`` → ``..`` is the round-12 shape that proved it).
# ``bsol`` keeps the existing separator mapping to ``/`` (Windows-style
# separators collapse), and ``Tab``/``NewLine`` decode to real whitespace:
# the renderer line-breaks there too, so the shadow splitting the token is
# display-truthful, and boundary admissibility still judges pre-decode
# bytes.
_ENTITY_NAMES = {
    "tab": "\t",
    "newline": "\n",
    "excl": "!",
    "quot": '"',
    "num": "#",
    "dollar": "$",
    "percnt": "%",
    "amp": "&",
    "apos": "'",
    "lpar": "(",
    "rpar": ")",
    "ast": "*",
    "plus": "+",
    "comma": ",",
    "period": ".",
    "sol": "/",
    "colon": ":",
    "semi": ";",
    "lt": "<",
    "equals": "=",
    "gt": ">",
    "quest": "?",
    "commat": "@",
    "bsol": "/",
    "Hat": "^",
    "lowbar": "_",
    "grave": "`",
    "verbar": "|",
}
_HTML_ENTITY_RE = re.compile(
    r"&(?:#0*\d+|#x0*[0-9a-f]+|" + "|".join(_ENTITY_NAMES) + r");",
    re.IGNORECASE,
)
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
        self.limit_kind = limit_kind


async def build_share_snapshot(
    thread_id: str,
    *,
    request: Any,
    user_id: str | None,
) -> tuple[dict[str, Any], int | None]:
    """Freeze the visible transcript of *thread_id* into a public DTO.

    Returns the snapshot and the highest source ``seq`` the bounded scan
    observed (including tool/hidden rows the DTO drops) — the
    source-history boundary the snapshot represents, persisted as the
    share's audit-only ``source_last_seq``."""
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
    # chronological. Three bounds: the public-message cap enforces the share
    # contract, the rendered-bytes cap keeps one share from persisting (and
    # re-deserializing + re-sanitizing on every anonymous read) an
    # unbounded transcript that stays under the message count, and the
    # raw-scan cap bounds work on row-heavy threads.
    pages: list[list[dict[str, Any]]] = []
    public_messages = 0
    rendered_bytes = 0
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
            rendered_bytes += sum(len(message["content"].encode("utf-8")) for message in page_messages)
        if rendered_bytes > _SNAPSHOT_MAX_RENDERED_BYTES:
            logger.warning(
                "Share snapshot for thread %s exceeded the %d rendered-bytes cap; refusing partial share",
                thread_id,
                _SNAPSHOT_MAX_RENDERED_BYTES,
            )
            raise ShareSnapshotTooLarge(thread_id, rendered_bytes, _SNAPSHOT_MAX_RENDERED_BYTES, limit_kind="rendered-bytes")
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
    # The audit boundary is the highest raw seq the bounded scan consumed —
    # observed inside the pager before visibility filtering, so hidden rows
    # advance it exactly like public ones.
    return (
        {
            "version": 1,
            "messages": messages,
        },
        raw_scan_budget.max_seq,
    )


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


def _commonmark_inline_code_spans(text: str) -> list[tuple[int, int]]:
    """Inline code span extents per CommonMark, not just backtick matching:
    only an unescaped backtick run of length N closed by the next
    exactly-length-N run within this paragraph opens a span. Escaped
    delimiters (``\\````), mismatched run lengths, and runs that never close
    are literal text — the renderer shows their content as prose, so
    ``<think>`` blocks hiding there are model reasoning and must not be
    protected from stripping into an anonymous snapshot. *text* must be a
    single paragraph (no block-interrupting lines) — `_code_regions`
    guarantees that."""
    spans: list[tuple[int, int]] = []
    n = len(text)
    # One escape-agnostic pass indexes every maximal backtick run by length;
    # closing a length-L opener is then a bisect lookup instead of rescanning
    # the tail. The old doomed-lengths memo only deduplicated repeated
    # lengths, so successively longer unmatched runs walked the paragraph
    # once per distinct length — quadratic on snapshot-sized text (80 KiB
    # ≈ 1s, and the sanitizer runs again on every anonymous resolution).
    runs_by_length: dict[int, list[int]] = {}
    i = 0
    while i < n:
        if text[i] == "`":
            run_end = i + 1
            while run_end < n and text[run_end] == "`":
                run_end += 1
            runs_by_length.setdefault(run_end - i, []).append(i)
            i = run_end
        else:
            i += 1
    i = 0
    while i < n:
        char = text[i]
        if char == "\\":
            i += 2
            continue
        if char != "`":
            i += 1
            continue
        run_end = i + 1
        while run_end < n and text[run_end] == "`":
            run_end += 1
        starts = runs_by_length.get(run_end - i, ())
        closer = bisect_left(starts, run_end)
        if closer < len(starts):
            close = starts[closer] + (run_end - i)
            spans.append((i, close))
            i = close
        else:
            i = run_end
    return spans


def _quote_depth(content: str) -> int:
    """Number of leading blockquote markers (a line starting "> > " nests two)."""
    depth = 0
    offset = 0
    while True:
        marker = _QUOTE_DEPTH_MARKER_RE.match(content, offset)
        if marker is None:
            return depth
        depth += 1
        offset = marker.end()


def _container_thematic_suffix_start(content: str) -> int | None:
    """Start of a homogeneous three-marker suffix, computed in one pass."""
    cursor = len(content)
    while cursor > 0 and content[cursor - 1] in " \t":
        cursor -= 1
    if cursor == 0 or content[cursor - 1] not in "-*_":
        return None
    marker = content[cursor - 1]
    count = 0
    start = cursor
    while cursor > 0:
        while cursor > 0 and content[cursor - 1] in " \t":
            cursor -= 1
        if cursor == 0 or content[cursor - 1] != marker:
            break
        cursor -= 1
        start = cursor
        count += 1
    return start if count >= 3 else None


def _container_body(content: str) -> tuple[str, bool]:
    """Peel quote/list markers and report whether a quote was present."""
    offset = 0
    saw_quote = False
    while True:
        padding = _CONTAINER_PADDING_RE.match(content, offset)
        assert padding is not None
        offset = padding.end()
        marker = _CONTAINER_QUOTE_MARKER_RE.match(content, offset)
        if marker is not None:
            saw_quote = True
        else:
            marker = _CONTAINER_LIST_MARKER_RE.match(content, offset)
        if marker is None:
            return content[offset:], saw_quote
        offset = marker.end()


def _container_leaf_content(content: str) -> tuple[str, int, bool] | None:
    """Return a leaf-block line nested in quote/list containers.

    This parser is deliberately conservative after any quote/list has been
    observed: arbitrary leading indentation may be item content indentation.
    Misclassifying an indented code line as a boundary can only remove extra
    text, while missing a real item heading lets an inline-code span bridge
    distinct paragraphs and publish reasoning.
    """
    offset = 0
    thematic_start = _container_thematic_suffix_start(content)
    while True:
        # Regex ``pos`` keeps one immutable source string.  Re-slicing the
        # remaining suffix at every nested marker makes a valid 2 MiB share
        # quadratic under an adversarial ``> > > ...`` line.
        padding = _CONTAINER_PADDING_RE.match(content, offset)
        assert padding is not None
        offset = padding.end()
        # Thematic syntax overlaps a bullet marker (``* * *``), so test it
        # at every container depth before consuming another list marker.
        if offset == thematic_start:
            return content[offset:], offset, False
        marker = _CONTAINER_QUOTE_MARKER_RE.match(content, offset)
        if marker is None:
            marker = _CONTAINER_LIST_MARKER_RE.match(content, offset)
        if marker is None:
            break
        offset = marker.end()

    body = content[offset:]
    if _HEADING_RE.match(body) is not None:
        return body, offset, True
    if _THEMATIC_RE.match(body) is not None or _SETEXT_UNDERLINE_RE.match(body) is not None:
        return body, offset, False
    fence = _FENCE_OPEN_RE.match(body)
    if fence is not None and not (fence.group(1)[0] == "`" and "`" in fence.group(2)):
        return body, offset, False
    html_kind, _tag, _blank_end, _closes_on_open = _html_open(body)
    if html_kind is not None:
        return body, offset, False
    return None


def _indent_columns(content: str) -> int:
    """Indent width in columns: a space is one column, a tab advances to
    the next multiple of four (CommonMark tab expansion)."""
    columns = 0
    for char in content:
        if char == " ":
            columns += 1
        elif char == "\t":
            columns += 4 - (columns % 4)
        else:
            return columns
    return columns


def _fence_closes(content: str, char: str, min_len: int) -> bool:
    """A closing fence: up to three spaces of indent, at least *min_len*
    copies of the opening fence character, nothing but whitespace after."""
    indent = 0
    while indent < len(content) and content[indent] == " " and indent < 3:
        indent += 1
    body = content[indent:]
    length = 0
    while length < len(body) and body[length] == char:
        length += 1
    return length >= min_len and body[length:].strip() == ""


def _html_block_close(content: str, kind: str, tag: str | None) -> bool:
    """Has *content* ended the open HTML block of *kind*?"""
    if kind == "type1":
        # CommonMark 0.31.2 §4.6: the end tag "need not match the start
        # tag" — any of the four raw-text closers ends the block (verified
        # against the shipped renderer, micromark). A cross-tag close is
        # therefore a real paragraph boundary: the `<think>` behind it is
        # prose and must be stripped.
        return tag is not None and _HTML_TYPE1_CLOSE_RE.search(content) is not None
    if kind == "type2":
        return _HTML_TYPE2_CLOSE in content
    if kind == "type3":
        return _HTML_TYPE3_CLOSE in content
    if kind == "type4":
        return _HTML_TYPE4_CLOSE in content
    if kind == "type5":
        return _HTML_TYPE5_CLOSE in content
    return False  # blank-line-ended kinds are handled by the caller


def _html_open(content: str) -> tuple[str | None, str | None, bool, bool]:
    """(kind, tag, ends-at-blank-line, closes-on-the-open-line) when
    *content* opens a CommonMark HTML block, else all-None/False. Types 1-4
    may close on their own opening line (``<script>x</script>``) — the
    caller must not stay in the block state in that case."""
    type1 = _HTML_TYPE1_OPEN_RE.match(content)
    if type1 is not None:
        return (
            "type1",
            type1.group(1),
            False,
            _HTML_TYPE1_CLOSE_RE.search(content) is not None,
        )
    if _HTML_TYPE2_OPEN_RE.match(content) is not None:
        return "type2", None, False, _HTML_TYPE2_CLOSE in content
    if _HTML_TYPE3_OPEN_RE.match(content) is not None:
        return "type3", None, False, _HTML_TYPE3_CLOSE in content
    if _HTML_TYPE4_OPEN_RE.match(content) is not None:
        return "type4", None, False, _HTML_TYPE4_CLOSE in content
    if _HTML_TYPE5_OPEN_RE.match(content) is not None:
        return "type5", None, False, _HTML_TYPE5_CLOSE in content
    if _HTML_TYPE6_OPEN_RE.match(content) is not None:
        return "type6", None, True, False
    if _is_complete_tag_line(content):
        return "type7", None, True, False
    return None, None, False, False


def _code_regions(text: str) -> list[tuple[int, int]]:
    """Byte extents the Markdown renderer will treat as code: fenced code
    blocks (CommonMark opener/closer rules — backtick fences reject info
    strings containing backticks, closers need at least the opener's
    length) and inline code spans. HTML blocks are deliberately NOT
    protected — their lines merely terminate paragraphs, so any
    ``<think>`` inside them is stripped rather than served.

    The walk is line-structured (linear in the text; the old DOTALL fence
    regex was quadratic per line start) and yields disjoint regions, which
    is what makes the single-layer marker restore in
    `_strip_think_blocks_outside_markdown_code` safe."""
    regions: list[tuple[int, int]] = []
    n = len(text)

    # Precompute line extents (content end, line end including the line
    # terminator). CommonMark line endings are LF, CRLF, and bare CR.
    line_spans: list[tuple[int, int, int]] = []
    for match in re.finditer(r"[^\r\n]*(?:\r\n|\r|\n|$)", text):
        line_start, line_end = match.span()
        if line_start == n:
            break
        content_end = line_end
        if content_end > line_start and text[content_end - 1] == "\n":
            content_end -= 1
            if content_end > line_start and text[content_end - 1] == "\r":
                content_end -= 1
        elif content_end > line_start and text[content_end - 1] == "\r":
            content_end -= 1
        line_spans.append((line_start, content_end, line_end))

    fence_char: str | None = None
    fence_len = 0
    fence_start = 0
    html_kind: str | None = None
    html_tag: str | None = None
    html_blank_end = False
    container_html_kind: str | None = None
    container_html_tag: str | None = None
    container_html_blank_end = False
    container_html_requires_quote = False
    indented_start: int | None = None
    indented_end = 0
    # An indented code block may open only where no paragraph is open —
    # after a blank line, the document start, or a leaf block (heading,
    # fence close, HTML block end, thematic break, setext underline) — and
    # never after an ordinary/quote/list line, whose paragraph a deeper
    # indent would lazily continue.
    indented_eligible = True
    segment_start: int | None = None
    segment_end = 0
    # Quote/list lines root a segment whose later plain lines are lazy
    # continuations of the same paragraph (an inline span may bridge them);
    # an ordinary line roots a segment a quote/list line would interrupt.
    # `saw_quotelike` latches for the whole message: item-scoped fences and
    # indents cannot be told from document-level ones by a flat walk, so
    # once a list or quote appears, both document-level protections are
    # suppressed (strip instead — the module's leak-vs-loss asymmetry).
    segment_kind: str | None = None
    segment_quote_depth = 0
    saw_quotelike = False

    def flush_segment() -> None:
        # Resets the segment on flush: a caller that keeps extending the
        # segment across a non-paragraph line (an HTML block, say) would let
        # inline spans bridge it — the leak/corruption vector the reset
        # closes.
        nonlocal segment_start
        if segment_start is None:
            return
        for begin, end in _commonmark_inline_code_spans(text[segment_start:segment_end]):
            regions.append((segment_start + begin, segment_start + end))
        segment_start = None

    def close_indented() -> None:
        nonlocal indented_start
        if indented_start is not None:
            regions.append((indented_start, indented_end))
            indented_start = None

    for start, content_end, line_end in line_spans:
        content = text[start:content_end]
        if fence_char is not None:
            if _fence_closes(content, fence_char, fence_len):
                regions.append((fence_start, line_end))
                fence_char = None
                indented_eligible = True
            continue
        if html_kind is not None:
            if html_blank_end:
                if content.strip() == "":
                    html_kind = None
                    # The blank that ends the block leaves no open paragraph.
                    indented_eligible = True
            elif _html_block_close(content, html_kind, html_tag):
                html_kind = None
                indented_eligible = True
            continue
        if container_html_kind is not None:
            container_body, has_quote = _container_body(content)
            if container_html_requires_quote and not has_quote:
                # A raw HTML block cannot lazily continue after its quote
                # container ends; reconsider this line at document scope.
                container_html_kind = None
                indented_eligible = True
            else:
                if container_html_blank_end:
                    if container_body.strip() == "":
                        container_html_kind = None
                        indented_eligible = True
                elif _html_block_close(container_body, container_html_kind, container_html_tag):
                    container_html_kind = None
                    indented_eligible = True
                continue
        if indented_start is not None:
            if content.strip() == "" or _indent_columns(content) >= 4:
                indented_end = line_end
                indented_eligible = content.strip() == ""
                continue
            close_indented()
        if content.strip() == "":
            flush_segment()
            indented_eligible = True
            continue
        fence_match = _FENCE_OPEN_RE.match(content)
        if fence_match is not None and not (fence_match.group(1)[0] == "`" and "`" in fence_match.group(2)):
            if saw_quotelike:
                # List/quote context: an item-scoped fence's extent depends
                # on the item's content indent, which this document-level
                # walk does not model — and both misreads leak (an item
                # fence kept open past its item, or a dedented fence line
                # eaten as document fence content). Conservative inversion:
                # no document-level fence protection once a list or quote
                # has been seen. The fence line only BREAKS the segment so
                # fake inline spans cannot pair across it; item-scoped
                # fences are stripped instead of protected.
                flush_segment()
                indented_eligible = False
                continue
            # A fence interrupts any open paragraph.
            close_indented()
            flush_segment()
            fence_char = fence_match.group(1)[0]
            fence_len = len(fence_match.group(1))
            fence_start = start
            indented_eligible = False
            continue
        kind, tag, ends_at_blank, closes_on_open = _html_open(content)
        if kind is not None and not (kind == "type7" and segment_start is not None):
            # HTML blocks interrupt paragraphs and are deliberately NOT
            # protected — their content is stripped like any other prose so
            # a `<think>` inside one is never served. Type 7 is the
            # exception that cannot interrupt a paragraph: mid-paragraph it
            # is lazy continuation text.
            close_indented()
            flush_segment()
            if not closes_on_open:
                html_kind, html_tag, html_blank_end = kind, tag, ends_at_blank
                indented_eligible = False
            else:
                # A self-closed HTML block is a leaf-block boundary.
                indented_eligible = True
            continue
        quote_match = _BLOCKQUOTE_RE.match(content) is not None
        list_match = (not quote_match) and _LIST_ITEM_RE.match(content) is not None
        if quote_match or list_match or saw_quotelike:
            container_leaf = _container_leaf_content(content)
            if container_leaf is not None:
                leaf_body, leaf_offset, preserve_inline = container_leaf
                # A leaf block inside any quote/list container interrupts the
                # item paragraph. Item indentation is intentionally parsed
                # fail-closed because this sanitizer's leak-vs-loss contract
                # already suppresses code-block protection in such messages.
                saw_quotelike = True
                flush_segment()
                if preserve_inline:
                    for begin, end in _commonmark_inline_code_spans(leaf_body):
                        regions.append((start + leaf_offset + begin, start + leaf_offset + end))
                kind, tag, ends_at_blank, closes_on_open = _html_open(leaf_body)
                if kind is not None and not closes_on_open:
                    container_html_kind = kind
                    container_html_tag = tag
                    container_html_blank_end = ends_at_blank
                    _body, container_html_requires_quote = _container_body(content)
                indented_eligible = True
                continue
        if quote_match or list_match:
            # An empty quote line at any nesting depth is a blank line
            # inside the quote: it splits the quoted paragraph.
            blank_quote = quote_match and re.fullmatch(r" {0,3}>[ \t]*(?:>[ \t]*)*", content) is not None
            if blank_quote:
                flush_segment()
                indented_eligible = True
                continue
            saw_quotelike = True
            kind_root = "quote" if quote_match else "list"
            # A list line always starts a fresh item (two items are two
            # paragraphs — a span can never bridge them). A quote line
            # continues a quote-rooted segment only when its marker depth
            # is not deeper — the `>` markers are lazy paragraph
            # continuation at the same nesting; a deeper-nested quote line
            # interrupts the outer quote's paragraph.
            depth = _quote_depth(content) if quote_match else 0
            if list_match or segment_kind != "quote" or depth > segment_quote_depth:
                flush_segment()
                segment_start = start
                segment_kind = kind_root
                segment_quote_depth = depth
            segment_end = line_end
            indented_eligible = False
            continue
        if _HEADING_RE.match(content) is not None or _THEMATIC_RE.match(content) is not None or _SETEXT_UNDERLINE_RE.match(content) is not None:
            # Leaf-block lines end the paragraph an inline span lives in;
            # the span can never reach across one. A heading's own inline
            # code is still code to the renderer, so it is protected too
            # (thematic/setext lines carry no backticks by shape).
            flush_segment()
            if _HEADING_RE.match(content) is not None:
                for begin, end in _commonmark_inline_code_spans(content):
                    regions.append((start + begin, start + end))
            indented_eligible = True
            continue
        if indented_eligible and not saw_quotelike and _indent_columns(content) >= 4:
            # An indented code block (it cannot interrupt a paragraph, so
            # entry requires a blank line, the document start, or a leaf
            # block boundary); its content is protected verbatim.
            flush_segment()
            indented_start = start
            indented_end = line_end
            continue
        if segment_start is None:
            segment_start = start
            segment_kind = None
        segment_end = line_end
        indented_eligible = False
    flush_segment()
    close_indented()
    if fence_char is not None:
        # CommonMark: an unclosed fence runs to the end of the document.
        regions.append((fence_start, n))
    return regions


def _find_think_open(text: str, start: int) -> tuple[int, int] | None:
    """Find an opening think tag without retrying its suffix per candidate."""
    prefix = _THINK_OPEN_PREFIX_RE.search(text, start)
    if prefix is None:
        return None
    stop = text.find(">", prefix.end())
    if stop < 0:
        return None
    return prefix.start(), stop + 1


def _find_think_close(text: str, start: int) -> tuple[int, int] | None:
    """Find a closing think tag while scanning intervening space once."""
    cursor = start
    while prefix := _THINK_CLOSE_PREFIX_RE.search(text, cursor):
        stop = prefix.end()
        while stop < len(text) and text[stop].isspace():
            stop += 1
        if stop < len(text) and text[stop] == ">":
            return prefix.start(), stop + 1
        cursor = stop
    return None


def _strip_think_blocks_outside_markdown_code(text: str) -> str:
    """Remove model reasoning while preserving literal tags in code examples."""
    # Build an equal-length classification shadow whose NULs cannot introduce
    # ``<think>`` syntax. Exact source offsets then remain valid without any
    # collision-prone sentinel selection or per-code-region restoration.
    shadow_parts: list[str] = []
    cursor = 0
    for begin, end in _code_regions(text):
        shadow_parts.append(text[cursor:begin])
        shadow_parts.append("\x00" * (end - begin))
        cursor = end
    shadow_parts.append(text[cursor:])
    shadow = "".join(shadow_parts)

    kept_ranges: list[tuple[int, int]] = []
    cursor = 0
    while opening := _find_think_open(shadow, cursor):
        kept_ranges.append((cursor, opening[0]))
        close = _find_think_close(shadow, opening[1])
        if close is None:
            cursor = len(text)
            break
        cursor = close[1]
    else:
        kept_ranges.append((cursor, len(text)))

    original_output = "".join(text[begin:end] for begin, end in kept_ranges)
    shadow_output = "".join(shadow[begin:end] for begin, end in kept_ranges)
    trim_begin = len(shadow_output) - len(shadow_output.lstrip())
    trim_end = len(shadow_output.rstrip())
    return original_output[trim_begin:trim_end]


def _collapse_separators_once(
    text: str,
    *,
    decode_percent: bool = False,
    decode_escapes: bool = True,
) -> tuple[str, list[tuple[int, int]]]:
    """One normalization pass: returns the pass's output plus, per output
    character, the ``(first, last)`` input index it was produced from."""
    normalized: list[str] = []
    spans: list[tuple[int, int]] = []
    i = 0
    n = len(text)
    while i < n:
        char = text[i]
        if decode_percent and char == "%" and i + 2 < n:
            try:
                byte = int(text[i + 1 : i + 3], 16)
            except ValueError:
                byte = 0x100
            # Workspace route syntax is ASCII.  Leaving non-ASCII bytes
            # encoded avoids inventing an imprecise character-to-byte map.
            if byte < 0x80:
                normalized.append(chr(byte))
                spans.append((i, i + 2))
                i += 3
                continue
        if decode_escapes and char == "&":
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
            unicode_escape = _UNICODE_ESCAPE_RE.match(text, run_end) if decode_escapes else None
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


def _remove_dot_segments_once(
    text: str,
    spans: list[tuple[int, int]],
    *,
    encoded_dots: bool = True,
) -> tuple[str, list[tuple[int, int]]]:
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
            single_dots = (".", "%2e") if encoded_dots else (".",)
            double_dots = ("..", "%2e%2e", ".%2e", "%2e.") if encoded_dots else ("..",)
            if segment in single_dots:
                i = j
                continue
            if segment in double_dots:
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


def _normalize_workspace_path_with_offsets(text: str, *, resolve_dots: bool) -> tuple[str, list[tuple[int, int]]]:
    """Decode a workspace path while retaining exact source coordinates.

    Unlike the generic reference shadow, workspace paths need percent
    decoding *in* the mapped view so a canonical route end can be projected
    back without swallowing adjacent public prose.  Percent, entity, and
    unicode escapes share the same bounded fixpoint, allowing their supported
    compositions while keeping work linear in the path length.
    """
    normalized = text
    spans = [(index, index) for index in range(len(text))]
    for _ in range(_COLLAPSE_MAX_PASSES):
        collapsed, collapsed_spans = _collapse_separators_once(normalized, decode_percent=True)
        if collapsed == normalized:
            break
        normalized = collapsed
        spans = [(spans[first][0], spans[last][1]) for first, last in collapsed_spans]
    # The last permitted decode can itself produce adjacent separators
    # (``/%25252F`` -> ``//``) or a backslash (``/%255C`` -> ``/\\``).
    # Canonicalize that structure to stability without decoding another
    # escape layer.  Two passes suffice: the first turns every backslash
    # into ``/`` and the second folds any newly adjacent slash run.
    for _ in range(2):
        collapsed, collapsed_spans = _collapse_separators_once(
            normalized,
            decode_escapes=False,
        )
        if collapsed == normalized:
            break
        normalized = collapsed
        spans = [(spans[first][0], spans[last][1]) for first, last in collapsed_spans]
    # URL resolution happens after decoding the path, not between encoding
    # layers: resolving early makes a still-encoded ``.`` segment look like
    # ordinary path data and lets a following ``..`` pop the wrong segment.
    # Remaining ``%2E`` bytes are beyond the decode budget and stay literal.
    if resolve_dots:
        normalized, spans = _remove_dot_segments_once(
            normalized,
            spans,
            encoded_dots=False,
        )
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

# Owner-scoped API surface (round 8): every ``/api/threads/{id}`` route is
# private, not just the artifacts/uploads pair — each carries the internal
# thread id and several are owner-only exports. The id ends at a path/query/
# fragment/whitespace boundary or at the end of the token: the bare
# ``/api/threads/SECRET`` shape (round 11) leaks the identifier exactly like
# the ``/<segment>`` form, and an id-shaped word cannot be told apart from a
# secret, so both classify. The leading separator is optional so a relative
# Markdown destination or a bare path in running text classifies identically
# instead of publishing a live-looking private link. The mount name requires
# the same kind of trailing boundary (round 11): ``mnt/user-data`` ends the
# private mount, while ``user-database``/``user-data-v2``/``user-data.backup``
# are different, public names an unbounded prefix would have swallowed.
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
# ``api/langgraph/`` is a live alias of the thread route: the bundled nginx
# rewrites ``/api/langgraph/*`` to ``/api/*`` (docker/nginx/nginx.conf), so
# the prefixed shape classifies like the native one. ``mnt`` phrases are
# prefix-free and already cover the alias.
_BOUNDARY_BLOCK_RE = re.compile(r"[\w.\-]\Z")
_CORE_API_THREAD_REFERENCE_RE = re.compile(r"api/(?:langgraph/)?threads/[^/?#\s]+(?=[/?#\s]|$)", re.IGNORECASE)
_CORE_MNT_USER_DATA_RE = re.compile(r"mnt/user-data(?![\w.\-])", re.IGNORECASE)
_AGENT_NAME_ROUTE_SEGMENT = AGENT_NAME_PATTERN.pattern.removeprefix("^").removesuffix("$")
_THREAD_ID_ROUTE_SEGMENT = THREAD_ID_PATTERN.removeprefix("^").removesuffix("$")
_WORKSPACE_THREAD_ID_CHAR = r"[A-Za-z0-9_-]"
_WORKSPACE_THREAD_PATTERN = (
    rf"/workspace/(?:agents/(?>{_AGENT_NAME_ROUTE_SEGMENT})/)?chats/"
    rf"(?!(?-i:new)(?!{_WORKSPACE_THREAD_ID_CHAR}))"
    rf"(?P<thread_id>(?>{_THREAD_ID_ROUTE_SEGMENT}))_*"
)
_CORE_WORKSPACE_THREAD_RE = re.compile(_WORKSPACE_THREAD_PATTERN, re.IGNORECASE)
_WORKSPACE_TEXT_TOKEN_RE = re.compile(r"[^\s<>\"]+")
_WORKSPACE_HTTP_RE = re.compile(r"https?://", re.IGNORECASE)
_WORKSPACE_LITERAL_HTTP_AUTHORITY_RE = re.compile(r"https?://[^/?#\s<>\"]+", re.IGNORECASE)
_WORKSPACE_REFERENCE_TRAILING_PUNCTUATION = _REFERENCE_TRAILING_PUNCTUATION.replace("_", "")
_API_THREAD_REFERENCE_RE = re.compile(r"(?<![\w.\-])api/(?:langgraph/)?threads/[^/?#\s]+(?=[/?#\s]|$)", re.IGNORECASE)
_MNT_USER_DATA_RE = re.compile(r"(?<![\w.\-])mnt/user-data(?![\w.\-])", re.IGNORECASE)


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


def _workspace_root_boundary_ok(value: str, start: int) -> bool:
    """Whether ``value[start:]`` may begin a literal rooted route.

    A rooted route can follow prose punctuation or an assignment (including
    fullwidth punctuation), but not another path/identifier byte.  A local
    drive prefix is the one colon form that is not a public root.
    """
    if start == 0:
        return True
    previous = value[start - 1]
    if previous.isalnum() or previous in ".%-/\\":
        return False
    if previous != ":" or start < 2 or value[start - 2] not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz":
        return True
    if start == 2:
        return False
    before_drive = value[start - 3]
    return before_drive.isalnum() or before_drive in ".%-"


def _workspace_route_boundary_ok(value: str, end: int) -> bool:
    """Validate the byte following a canonical thread id/Markdown closer."""
    if end == len(value):
        return True
    follower = value[end]
    if follower.isspace() or follower in "/?#<>" or follower in _REFERENCE_TRAILING_PUNCTUATION:
        return True
    # Percent may encode a path continuation, while hyphen/underscore may
    # continue an already-maximal id.  ``@`` is identifier-like in copied
    # text despite Unicode classifying it as punctuation.
    if follower in "%@-_":
        return False
    return unicodedata.category(follower).startswith("P")


def _workspace_route_end(value: str, core_end: int) -> int:
    """Include only a matched route's path/query/fragment tail."""
    end = core_end
    if end < len(value) and value[end] in "/?#":
        while end < len(value) and not value[end].isspace() and value[end] not in '<>"':
            end += 1
    return end


def _workspace_private_source_extent(path: str) -> tuple[int, bool] | None:
    """Return ``(source_end, opaque_tail_reached_end)`` for ``path``.

    Both resolved and as-written views are checked: dot cancellation may
    reveal a route at the path root, but it must never erase a route already
    present in the source.  The normalized match end is projected through
    the source map so delimiters and entity spellings stay whole.  The flag
    records that a matched path/query/fragment ran to the input boundary
    before sentence punctuation was trimmed; callers use it to distinguish
    an artificial candidate split from a real prose delimiter.
    """
    extents: list[tuple[int, bool]] = []
    for resolve_dots in (True, False):
        shadow, spans = _normalize_workspace_path_with_offsets(path, resolve_dots=resolve_dots)
        match = _CORE_WORKSPACE_THREAD_RE.match(shadow)
        if match is None or not _workspace_route_boundary_ok(shadow, match.end()):
            continue
        # Once the canonical id has consumed all 64 allowed characters, a
        # following underscore is ambiguous: it may be invalid route data or
        # a Markdown delimiter that is absent from the rendered route.  The
        # anonymous-share boundary is intentionally fail-closed here.  Do not
        # reconstruct the frontend's full Markdown parser just to distinguish
        # those cases; redact the complete route-like run either way.
        end = _workspace_route_end(shadow, match.end())
        opaque_tail_reached_end = match.end() < len(shadow) and shadow[match.end()] in "/?#" and end == len(shadow)
        while end > match.end() and shadow[end - 1] in _WORKSPACE_REFERENCE_TRAILING_PUNCTUATION:
            end -= 1
        if end:
            extents.append((spans[end - 1][1] + 1, opaque_tail_reached_end))
    if not extents:
        return None
    return max(end for end, _ in extents), any(reached for _, reached in extents)


def _workspace_private_source_end(path: str) -> int | None:
    """Return only the source end for callers without split boundaries."""
    extent = _workspace_private_source_extent(path)
    return extent[0] if extent is not None else None


def _workspace_url_path_source_start(value: str) -> int | None:
    """Locate a literal URL's path without confusing authority entities."""
    parsed = value
    source_spans: list[tuple[int, int]] | None = None
    if _HTML_ENTITY_RE.search(value) is not None or "\\" in value:
        parsed, source_spans = _collapse_separators_with_offsets(value, resolve_dots=False)
    authority = _WORKSPACE_LITERAL_HTTP_AUTHORITY_RE.match(parsed)
    if authority is None:
        return None
    if source_spans is None:
        return authority.end()
    if authority.end() >= len(source_spans):
        return None
    return source_spans[authority.end()][0]


def _has_private_workspace_reference(value: str) -> bool:
    """Classify one reference whose literal root or HTTP scheme is first."""
    if _WORKSPACE_HTTP_RE.match(value) is not None:
        path_start = _workspace_url_path_source_start(value)
        if path_start is None:
            return False
        value = value[path_start:]
    elif not value.startswith("/") or value.startswith("//"):
        return False
    return _workspace_private_source_end(value) is not None


def _is_private_reference(value: str, *, include_workspace: bool = True) -> bool:
    """Dual-view, mirroring the dual shadow: the dot-resolved decode catches
    references that only reach the surface through ``.``/``..`` cancellation,
    and the as-written decode guarantees resolution can never erase a
    phrase — browsers do not entity-decode URLs, so an entity dot-tail
    (``…/u/&#46;&#46;``) stays literal in the href and resolves to the
    owner-scoped route even though the resolved view popped the segment.
    Phrase hits use the lookbehind-free cores with the boundary judged in
    fed coordinates (see ``_boundary_ok``)."""
    if include_workspace and _has_private_workspace_reference(value):
        return True
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
        if begin < stop and _is_private_reference(value[begin:stop], include_workspace=False):
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


def _iter_workspace_source_tokens(text: str) -> Iterator[tuple[str, int]]:
    """Split source tokens where renderer normalization creates whitespace."""
    for match in _WORKSPACE_TEXT_TOKEN_RE.finditer(text):
        value = match.group(0)
        if "&" not in value and "\\" not in value:
            yield value, match.start()
            continue
        shadow, spans = _collapse_separators_with_offsets(value, resolve_dots=False)
        source_cursor = 0
        for index, char in enumerate(shadow):
            if not char.isspace():
                continue
            separator_begin, separator_end = spans[index]
            if source_cursor < separator_begin:
                yield value[source_cursor:separator_begin], match.start() + source_cursor
            source_cursor = max(source_cursor, separator_end + 1)
        if source_cursor < len(value):
            yield value[source_cursor:], match.start() + source_cursor


def _collect_workspace_edits(text: str, edits: list[tuple[int, int, str]]) -> None:
    """Collect workspace cuts only from literal anchors in original text.

    The generic sanitizer's resolved whole-message shadow is intentionally
    not a truth source here: resolving a relative path can manufacture a
    root, and resolving a complete URL can pop its authority. Literal routes
    are split into independent anchored candidates, normalized path-locally,
    and mapped back to exact source spans.  A later route in the same prose
    token therefore cannot hide behind an earlier public path, and public
    punctuation or text after a route is never swallowed by a fail-closed
    whole-token replacement.
    """

    def http_boundary_ok(
        value: str,
        start: int,
        boundary_shadow: str | None,
        shadow_index: int | None,
    ) -> bool:
        candidate = boundary_shadow if boundary_shadow is not None and shadow_index is not None else value
        index = shadow_index if boundary_shadow is not None and shadow_index is not None else start
        if index == 0:
            return True
        previous = candidate[index - 1]
        if previous == "_":
            # An underscore run can open Markdown emphasis at the start of
            # a token (or after punctuation), but inside a route id it is
            # ordinary id data: ``id_https://`` is one route followed by a
            # colon, not a second URL that may manufacture a split boundary.
            run_start = index - 1
            while run_start > 0 and candidate[run_start - 1] == "_":
                run_start -= 1
            if run_start == 0:
                return True
            previous = candidate[run_start - 1]
        return re.match(r"[A-Za-z0-9+.-]", previous) is None

    def standalone_separator(value: str, start: int) -> bool:
        if start <= 0:
            return True
        previous = value[start - 1]
        if previous in "@_":
            return False
        return previous.isspace() or previous in _WORKSPACE_REFERENCE_TRAILING_PUNCTUATION or unicodedata.category(previous).startswith("P")

    def collect_bare_candidates(
        value: str,
        token_start: int,
        stop: int,
        opaque_markers: list[int],
    ) -> int:
        anchors: list[int] = []
        opaque_tail = False
        scanned_through = 0
        marker_index = 0
        boundary_index = 0
        slash = value.find("/", 0, stop)
        while slash >= 0:
            while marker_index < len(opaque_markers) and opaque_markers[marker_index] < slash:
                if anchors and opaque_markers[marker_index] >= scanned_through:
                    opaque_tail = True
                marker_index += 1
            rendered_value = value
            rendered_slash = slash
            if boundary_shadow is not None and boundary_spans is not None:
                while boundary_index < len(boundary_spans) and boundary_spans[boundary_index][1] < slash:
                    boundary_index += 1
                if boundary_index < len(boundary_spans) and boundary_spans[boundary_index][0] <= slash <= boundary_spans[boundary_index][1] and boundary_shadow[boundary_index] == "/":
                    rendered_value = boundary_shadow
                    rendered_slash = boundary_index
            if not value.startswith("//", slash) and _workspace_root_boundary_ok(value, slash) and _workspace_root_boundary_ok(rendered_value, rendered_slash):
                # Once a rooted candidate is active, only a prose/Markdown
                # terminator in both the source and rendered views can begin
                # another one.  Entity/unicode syntax ending in punctuation
                # must not split route data (``chat&#115;/id``), while an
                # encoded comma remains a real prose boundary.
                if not anchors or (not opaque_tail and standalone_separator(value, slash) and standalone_separator(rendered_value, rendered_slash)):
                    anchors.append(slash)
                    opaque_tail = False
            scanned_through = slash + 1
            slash = value.find("/", slash + 1, stop)

        claimed_until = 0
        index = 0
        while index < len(anchors):
            anchor = anchors[index]
            candidate_stop = anchors[index + 1] if index + 1 < len(anchors) else stop
            extent = _workspace_private_source_extent(value[anchor:candidate_stop])
            if extent is None:
                index += 1
                continue
            source_end, opaque_tail_reached_end = extent
            edit_end = anchor + source_end
            if candidate_stop < len(value) and opaque_tail_reached_end:
                complete_extent = _workspace_private_source_extent(value[anchor:])
                if complete_extent is None:
                    index += 1
                    continue
                edit_end = anchor + complete_extent[0]
            elif candidate_stop < len(value) and edit_end == candidate_stop:
                # The next anchor, not source syntax, supplied the apparent
                # route boundary.  Reject it instead of rescanning every
                # suffix (which is quadratic on concatenated URL prefixes).
                index += 1
                continue
            edits.append(
                (
                    token_start + anchor,
                    token_start + edit_end,
                    _PRIVATE_REFERENCE_MARKER,
                )
            )
            claimed_until = max(claimed_until, edit_end)
            index += 1
            while index < len(anchors) and anchors[index] < edit_end:
                index += 1
        return claimed_until

    for value, token_start in _iter_workspace_source_tokens(text):
        boundary_shadow: str | None = None
        boundary_spans: list[tuple[int, int]] | None = None
        if "&" in value or "\\" in value:
            boundary_shadow, boundary_spans = _collapse_separators_with_offsets(value, resolve_dots=False)
        if boundary_shadow is None or boundary_spans is None:
            opaque_markers = [match.start() for match in re.finditer(r"[?#]", value)]
        else:
            opaque_markers = []
            shadow_cursor = 0
            while shadow_cursor < len(boundary_shadow):
                if boundary_shadow[shadow_cursor] == "&":
                    residual_entity = _HTML_ENTITY_RE.match(boundary_shadow, shadow_cursor)
                    if residual_entity is not None:
                        shadow_cursor = residual_entity.end()
                        continue
                if boundary_shadow[shadow_cursor] in "?#":
                    opaque_markers.append(boundary_spans[shadow_cursor][0])
                shadow_cursor += 1
        url_anchors: list[int] = []
        boundary_cursor = 0
        for url_match in _WORKSPACE_HTTP_RE.finditer(value):
            start = url_match.start()
            shadow_index: int | None = None
            if boundary_shadow is not None and boundary_spans is not None:
                while boundary_cursor < len(boundary_spans) and boundary_spans[boundary_cursor][0] < start:
                    boundary_cursor += 1
                if boundary_cursor < len(boundary_spans) and boundary_spans[boundary_cursor][0] == start and boundary_cursor > 0:
                    shadow_index = boundary_cursor
            if http_boundary_ok(value, start, boundary_shadow, shadow_index):
                url_anchors.append(start)

        # A valid literal URL owns everything after its scheme until the
        # next independently anchored scheme in this whitespace token.  Bare
        # slash candidates are considered only in the prose prefix, never in
        # a URL's nested path/query (``...?next=/workspace/...`` stays public).
        prefix_stop = url_anchors[0] if url_anchors else len(value)
        bare_claimed_until = collect_bare_candidates(value, token_start, prefix_stop, opaque_markers)

        index = 0
        while index < len(url_anchors) and url_anchors[index] < bare_claimed_until:
            index += 1
        while index < len(url_anchors):
            anchor = url_anchors[index]
            has_later_anchor = index + 1 < len(url_anchors)
            candidate_stop = url_anchors[index + 1] if has_later_anchor else len(value)
            candidate = value[anchor:candidate_stop]
            path_start = _workspace_url_path_source_start(candidate)
            if path_start is None:
                index += 1
                continue
            extent = _workspace_private_source_extent(candidate[path_start:])
            if extent is None:
                index += 1
                continue
            source_end, opaque_tail_reached_end = extent

            # A later literal scheme is an independent reference only when
            # public structure ended the private route before it.  If the
            # private path/query/fragment reaches this artificial split,
            # reclassify against the complete token: a nested URL is still
            # part of that opaque private tail and must not escape the cut.
            # Rechecking also prevents the split itself from manufacturing
            # a false route boundary (``.../idhttps://...``).
            edit_end = anchor + path_start + source_end
            if has_later_anchor and opaque_tail_reached_end:
                complete = value[anchor:]
                complete_path_start = _workspace_url_path_source_start(complete)
                complete_extent = _workspace_private_source_extent(complete[complete_path_start:]) if complete_path_start is not None else None
                if complete_extent is None:
                    index += 1
                    continue
                path_start = complete_path_start
                edit_end = anchor + path_start + complete_extent[0]
            elif has_later_anchor and edit_end == candidate_stop:
                index += 1
                continue

            edits.append(
                (
                    token_start + anchor + path_start,
                    token_start + edit_end,
                    _PRIVATE_REFERENCE_MARKER,
                )
            )
            index += 1
            while index < len(url_anchors) and url_anchors[index] < edit_end:
                index += 1


def _iter_markdown_link_spans(text: str) -> Iterator[tuple[int, int, int, int, int, int]]:
    """Yield the narrow inline-link shapes supported by the sanitizer.

    This intentionally matches the former regular expression rather than
    implementing the full CommonMark link grammar. The explicit cursor makes
    failed ``[`` candidates linear instead of retrying the rest of the input
    from every opener.
    """
    cursor = 0
    while True:
        label_begin = text.find("[", cursor)
        if label_begin < 0:
            return
        label_stop = text.find("]", label_begin + 1)
        if label_stop < 0:
            return
        if label_stop + 1 >= len(text) or text[label_stop + 1] != "(":
            cursor = label_stop + 1
            continue
        target_begin = label_stop + 2
        target_stop = text.find(")", target_begin)
        if target_stop < 0:
            return
        if target_stop == target_begin:
            cursor = target_stop + 1
            continue
        begin = label_begin - 1 if label_begin > 0 and text[label_begin - 1] == "!" else label_begin
        yield begin, target_stop + 1, label_begin + 1, label_stop, target_begin, target_stop
        cursor = target_stop + 1


def _collect_edits(text: str, normalized: str, spans: list[tuple[int, int]], edits: list[tuple[int, int, str]], *, conservative_gaps: bool = True) -> None:
    """Collect private-reference cuts for one shadow of ``text`` into
    ``edits`` (original-text coordinates). The conservative backstops
    (whole-gap and whole-token cuts for phrases the shadow cannot position)
    belong to the resolved shadow only — the as-written shadow is there for
    precise segments the resolution erased, and its wider cuts would
    swallow public heads the resolved view already cut precisely."""

    def original_span(start: int, end: int) -> tuple[int, int]:
        return spans[start][0], spans[end - 1][1] + 1

    overlap_starts: list[int] = []
    overlap_prefix_max_stops: list[int] = []

    def overlaps_existing_edit(begin: int, stop: int) -> bool:
        """Query edits that predate the raw-match walk in O(log n)."""
        index = bisect_left(overlap_starts, stop) - 1
        return index >= 0 and overlap_prefix_max_stops[index] > begin

    def replace_markdown(
        begin_index: int,
        stop_index: int,
        label_begin_index: int,
        label_stop_index: int,
        target_begin_index: int,
        target_stop_index: int,
    ) -> None:
        target = normalized[target_begin_index:target_stop_index].strip()
        # A Markdown destination may carry an optional quoted title. The path
        # is always the first whitespace-delimited token.
        destination = target.split(maxsplit=1)[0] if target else ""
        target_begin, target_stop = original_span(target_begin_index, target_stop_index)
        original_target = text[target_begin:target_stop].strip()
        original_destination = original_target.split(maxsplit=1)[0] if original_target else ""
        label_begin, label_stop = original_span(label_begin_index, label_stop_index)
        original_label = text[label_begin:label_stop]
        destination_is_private = _is_private_reference(destination, include_workspace=False) or _is_private_reference(original_destination)
        label_is_private = _is_private_reference(normalized[label_begin_index:label_stop_index], include_workspace=False) or _is_private_reference(original_label)
        if not destination_is_private and not label_is_private:
            return
        begin, stop = original_span(begin_index, stop_index)
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
        label = original_label.strip()
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
            if not _is_private_reference(value, include_workspace=False):
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
                overlaps_existing_edit(begin, stop) or not kept or not _is_private_reference(kept, include_workspace=False)
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

    for link_spans in _iter_markdown_link_spans(normalized):
        replace_markdown(*link_spans)
    if not conservative_gaps and edits:
        # The second shadow only needs to test overlap against resolved-pass
        # edits and Markdown edits already collected above. Raw regex matches
        # in this pass are disjoint and preserve order through ``spans``.
        max_stop = 0
        for begin, stop, _ in sorted(edits, key=lambda edit: edit[0]):
            overlap_starts.append(begin)
            max_stop = max(max_stop, stop)
            overlap_prefix_max_stops.append(max_stop)
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
    _collect_workspace_edits(text, edits)
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
    """Re-apply the public contract to a stored snapshot at read time.

    Snapshots are immutable once minted, so a message that still carries an
    owner-only path — written through a sanitizer defect or before the rules
    were tightened — would otherwise stay exposed on every public read until
    the share is revoked. The private-reference neutralizer runs here next
    to ``sanitize_share_title`` for the same reason.

    The DTO is also *rebuilt*, never spread: the public response is
    reconstructed as the strict ``{version, messages}`` /
    ``{id, role, content}`` allowlist the create path emits, so extra
    fields in an older, malformed, or sanitizer-defect record (tool_calls,
    reasoning, run ids, debug metadata) can never serialize to anonymous
    callers, and messages that do not conform to the contract are dropped.
    Message ids are regenerated (``m1``, ``m2``, …) rather than trusted:
    a stored id could be a source event, run, or thread identifier, and a
    string check does not make it snapshot-local.
    """
    messages_value = snapshot.get("messages")
    messages: list[dict[str, str]] = []
    if isinstance(messages_value, list):
        for message in messages_value:
            if not isinstance(message, dict):
                continue
            role = message.get("role")
            content = message.get("content")
            if role not in ("user", "assistant"):
                continue
            if not isinstance(content, str):
                continue
            # Assistant reasoning owes the same guarantee at read time as at
            # create: an older or sanitizer-defect snapshot carrying a
            # <think> block must not serve it to anonymous readers forever.
            # Same order as the create path — strip reasoning, then
            # neutralize private paths in what remains. User messages are
            # never treated as assistant reasoning (create-path parity).
            sanitized = content
            if role == "assistant":
                sanitized = _strip_think_blocks_outside_markdown_code(sanitized)
            sanitized = _neutralize_private_references(sanitized)
            if not sanitized.strip():
                # Create-path parity: `_public_message` drops a message whose
                # public text is empty; a stored record that re-strips to
                # empty must not publish an empty shell either.
                continue
            messages.append(
                {
                    "id": f"m{len(messages) + 1}",
                    "role": role,
                    "content": sanitized,
                }
            )
    version = snapshot.get("version")
    return {
        "version": version if isinstance(version, int) else 1,
        "messages": messages,
    }


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
