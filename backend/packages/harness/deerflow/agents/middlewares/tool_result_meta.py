"""Unified tool result semantics for structured signal production.

Every tool result that passes through ToolErrorHandlingMiddleware gets a
``deerflow_tool_meta`` entry in additional_kwargs. Downstream consumers
(ToolProgressMiddleware, etc.) read this key instead of parsing text.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal

from langchain_core.messages import ToolMessage
from langgraph.types import Command

TOOL_META_KEY = "deerflow_tool_meta"

_ERROR_PREFIX = "Error:"
_PARTIAL_MARKERS = (
    "partial results",
    "limited results",
    "truncated",
    "results may be incomplete",
    # Tools that return status="success" with a no-results body (instead of status="error")
    # must still be caught by stagnation detection so the model is prompted to try a different query.
    "no results found",
    "no content found",
    "no images found",
)


@dataclass(frozen=True, slots=True)
class ToolResultMeta:
    status: Literal["success", "error", "partial_success"]
    error_type: str | None
    recoverable_by_model: bool
    recommended_next_action: Literal["continue", "rewrite_query", "try_alternative", "summarize", "stop"]
    source: Literal["exception", "tool_return", "content_analysis", "progress_middleware"]


_ERROR_RULES: list[tuple[list[str], dict[str, object]]] = [
    (
        ["401", "403", "unauthorized", "authentication", "invalid api key"],
        {"error_type": "auth", "recoverable_by_model": False, "recommended_next_action": "stop"},
    ),
    (
        ["rate limit", "rate limited", "rate_limit"],
        {"error_type": "rate_limited", "recoverable_by_model": False, "recommended_next_action": "summarize"},
    ),
    (
        ["timeout", "timed out", "connection", "network error", "temporarily unavailable"],
        {"error_type": "transient", "recoverable_by_model": False, "recommended_next_action": "try_alternative"},
    ),
    (
        ["not configured", "not installed", "missing required", "disabled", "no api key"],
        {"error_type": "config", "recoverable_by_model": False, "recommended_next_action": "stop"},
    ),
    (
        ["permission denied", "access denied", "path traversal", "forbidden"],
        {"error_type": "permission", "recoverable_by_model": True, "recommended_next_action": "try_alternative"},
    ),
    (
        ["no results found", "no content found", "no images found", "no results"],
        {"error_type": "no_results", "recoverable_by_model": True, "recommended_next_action": "rewrite_query"},
    ),
    (
        ["not found", "no such file", "does not exist", "404"],
        {"error_type": "not_found", "recoverable_by_model": True, "recommended_next_action": "rewrite_query"},
    ),
    (
        ["unexpected error", "internal error", "500"],
        {"error_type": "internal", "recoverable_by_model": False, "recommended_next_action": "stop"},
    ),
]

_UNKNOWN_ERROR: dict[str, object] = {
    "error_type": "unknown",
    "recoverable_by_model": True,
    "recommended_next_action": "try_alternative",
}

# Tool names whose result content is a *rendered remote page* rather than a tool's
# own message. Name-based, mirroring ToolResultSanitizationMiddleware's
# _REMOTE_CONTENT_TOOL_NAMES: the first-party fetch providers all normalize to
# ``web_fetch`` (see community/*/tools.py), so the gate stays provider-agnostic.
# The gate is required because normalize_tool_message() runs for *every* tool —
# a short "not found" line is legitimate output from many of them.
# ``web_capture`` is deliberately absent: its result is a tool message about an
# artifact ("Captured screenshot: <path> (warning: ...)"), not a rendered page, so
# a title rule cannot apply. A dead-target capture still yields the artifact plus a
# model-visible warning; stamping it belongs to the provider boundary (#4239).
_PAGE_CONTENT_TOOL_NAMES: frozenset[str] = frozenset({"web_fetch"})

# Category attributes reused by the error-shell path, indexed by the error_type
# _ERROR_RULES already declares. Derived rather than duplicated so a shell can
# never drift from the recoverable/next-action contract of its own category.
_ATTRS_BY_ERROR_TYPE: dict[str, dict[str, object]] = {str(attrs["error_type"]): attrs for _keywords, attrs in _ERROR_RULES}

# Reason phrases (RFC 9110 §15 plus the wording real servers ship) mapped onto the
# error_type they already have in _ERROR_RULES. Restricted to the statuses a fetch
# actually lands on as a rendered page. The 5xx split mirrors _ERROR_RULES' own:
# 500/501 sit with its "500"/"internal error" keywords (internal → stop), while
# 502/503/504 sit with its "timeout"/"temporarily unavailable" keywords (transient
# → try_alternative) — a gateway error is the try-a-different-source case, and the
# same words must not classify differently here than through _classify_error_text.
_ERROR_SHELL_PHRASES: dict[str, str] = {
    "unauthorized": "auth",
    "proxy authentication required": "auth",
    "forbidden": "permission",
    "access denied": "permission",
    "permission denied": "permission",
    "not found": "not_found",
    "too many requests": "rate_limited",
    "internal server error": "internal",
    "not implemented": "internal",
    "bad gateway": "transient",
    "service unavailable": "transient",
    "service temporarily unavailable": "transient",
    "gateway timeout": "transient",
}

# Generic subject nouns a server may prefix onto the reason phrase ("Page not found",
# IIS's "404 - File or directory not found."). Stripped from the *front* only, so any
# word left over after the phrase still rejects the title.
_STATUS_TITLE_FILLER: frozenset[str] = frozenset({"http", "error", "page", "the", "file", "or", "directory", "url", "resource"})


# Pre-compiled at module load from _ERROR_RULES. Anchoring bare numeric codes (401, 403, 404,
# 500) to word boundaries prevents substring hits on unrelated numbers like "took 500ms".
# Computed here (after _ERROR_RULES) so the set is authoritative and thread-safe — no lazy
# writes on the hot classification path.
_NUMERIC_KW_RE: dict[str, re.Pattern[str]] = {kw: re.compile(rf"\b{kw}\b") for rule_keywords, _ in _ERROR_RULES for kw in rule_keywords if kw.isdigit()}

_SEMANTIC_ZERO_ERROR_STRINGS: frozenset[str] = frozenset({"none", "null", "false", "no", "ok", "success", "n/a", ""})


def _extract_json_error_text(content: str) -> str | None:
    """Return the error string from a JSON-wrapped error like {"error": "...", "query": "..."}.

    Returns None when the ``error`` field is falsy (JSON null / 0 / false / empty
    string) or is a sentinel string that conventionally means "no error" (e.g.
    ``"none"``, ``"null"``, ``"false"``).  This prevents tools that return
    ``{"error": "none", "results": [...]}`` on success from being misclassified
    as errors.
    """
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return None
    error = data.get("error") if isinstance(data, dict) else None
    if not error:
        return None
    if isinstance(error, str) and error.lower().strip() in _SEMANTIC_ZERO_ERROR_STRINGS:
        return None
    # Serialize non-string values to JSON so _classify_error_text sees a predictable
    # format (e.g. {"error": 404} → "404", {"error": [...]} → "[...]") instead of
    # Python repr which can spuriously match keyword rules like "missing required".
    return error if isinstance(error, str) else json.dumps(error)


def _match_keyword(kw: str, lower: str) -> bool:
    """Match a keyword against lowercased text, using word boundaries for numeric codes."""
    if kw.isdigit():
        return bool(_NUMERIC_KW_RE[kw].search(lower))
    return kw in lower


def _classify_error_text(text: str) -> dict[str, object]:
    lower = text.lower()
    for keywords, attrs in _ERROR_RULES:
        if any(_match_keyword(kw, lower) for kw in keywords):
            return {**attrs}
    return {**_UNKNOWN_ERROR}


def _classify_error_shell(msg: ToolMessage, content: str) -> dict[str, object] | None:
    """Return category attributes when a fetched page is an HTTP error page.

    A fetch of a missing URL succeeds at the transport layer, so none of the branches
    above apply and the server's error page reaches the model stamped
    ``status="success"`` — counted as evidence it never contained (issue #4273).

    The signal is the *extracted title*: error pages from nginx / Apache / IIS /
    Cloudflare all render with the status line as their heading and only server
    boilerplate as the body ("# 404 Not Found" over "nginx/1.24.0"). Matching is by
    equality after normalization, never substring, so a document merely *about* a
    status keeps its title's other words and is rejected: "404 Ways to Cook Rice" and
    "Not Found: a short history of the 404" both survive as successes.

    Content length deliberately plays no part — measured against real error pages it
    does not separate (an IIS 404 renders to 193 chars, a genuine article to 202).

    This is the provider-agnostic fallback only. The authoritative signal is the
    provider's own status code, which stays at the web_fetch boundary (Browserless
    surfaces ``X-Response-Code`` per #4239); a page whose title is not a status line
    remains that layer's job.
    """
    if msg.name not in _PAGE_CONTENT_TOOL_NAMES:
        return None
    title = next((line for line in content.splitlines() if line.strip()), "")
    phrase = _as_status_line(title.lstrip("#").strip())
    error_type = _ERROR_SHELL_PHRASES.get(phrase) if phrase else None
    return {**_ATTRS_BY_ERROR_TYPE[error_type]} if error_type else None


def _as_status_line(title: str) -> str | None:
    """Reduce a page title to its bare reason phrase, or None if it carries content.

    "404 Not Found" -> "not found"; "404 - File or directory not found." -> "not found";
    "404 Ways to Cook Rice" -> "ways to cook rice" (words survive, so it is a document).
    """
    words = re.sub(r"[^0-9a-z]+", " ", title.lower()).split()
    # Strip leading status codes and generic nouns in either order — servers write both
    # "404 - File or directory not found" and "HTTP Error 404 - Not Found".
    while words and (words[0] in _STATUS_TITLE_FILLER or (len(words[0]) == 3 and words[0].isdigit() and 400 <= int(words[0]) <= 599)):
        words = words[1:]
    return " ".join(words) or None


def _make_meta(*, status: str, source: str, error_type: str | None = None, recoverable_by_model: bool = True, recommended_next_action: str = "continue") -> dict[str, object]:
    return {
        "status": status,
        "error_type": error_type,
        "recoverable_by_model": recoverable_by_model,
        "recommended_next_action": recommended_next_action,
        "source": source,
    }


def stamp_exception_meta(msg: ToolMessage, exc_info: str) -> ToolMessage:
    """Stamp deerflow_tool_meta with source='exception' onto an exception-derived ToolMessage.

    Unlike normalize_tool_message (which preserves existing stamps), this function always
    overwrites any pre-existing TOOL_META_KEY entry.  Exception-derived classification is
    more authoritative than a tool's own return-time stamp.
    """
    attrs = _classify_error_text(exc_info)
    updated_kwargs = dict(msg.additional_kwargs or {})
    updated_kwargs[TOOL_META_KEY] = _make_meta(status="error", source="exception", **attrs)
    msg.additional_kwargs = updated_kwargs
    return msg


def normalize_tool_message(msg: ToolMessage) -> ToolMessage:
    """Attach deerflow_tool_meta to a ToolMessage if not already present."""
    existing = (msg.additional_kwargs or {}).get(TOOL_META_KEY)
    if existing is not None:
        return msg

    content = msg.content if isinstance(msg.content, str) else ""
    # Pre-compute once; reused by the partial-success marker check below to avoid calling
    # content.lower() once per _PARTIAL_MARKERS entry inside the generator.
    content_lower = content.lower()

    # Non-standard error: tool returned status="error" without the "Error:" prefix convention.
    # (Actual exceptions from ToolErrorHandlingMiddleware are pre-stamped by stamp_exception_meta
    # and exit early above — they never reach this branch.)
    # Try JSON extraction first so classification uses only the "error" field value, not
    # keywords that appear incidentally in other JSON fields (e.g. "query").
    if msg.status == "error" and not content.startswith(_ERROR_PREFIX):
        json_error = _extract_json_error_text(content)
        if json_error is not None:
            attrs = _classify_error_text(json_error)
        else:
            # Determine whether content is a JSON object that simply has no 'error' key.
            # If so, do NOT classify from the raw JSON string — incidental field values
            # (e.g. {"user_id": 401}) would spuriously match keyword rules and hard-block
            # the tool.  Classify raw text only when the content is not valid JSON.
            try:
                is_json_dict = isinstance(json.loads(content), dict)
            except (json.JSONDecodeError, ValueError):
                is_json_dict = False
            attrs = {**_UNKNOWN_ERROR} if is_json_dict else _classify_error_text(content)
        meta = _make_meta(status="error", source="tool_return", **attrs)
    elif content.startswith(_ERROR_PREFIX):
        attrs = _classify_error_text(content[len(_ERROR_PREFIX) :])
        meta = _make_meta(status="error", source="tool_return", **attrs)
    elif (json_error := _extract_json_error_text(content)) is not None:
        attrs = _classify_error_text(json_error)
        meta = _make_meta(status="error", source="tool_return", **attrs)
    elif (shell_attrs := _classify_error_shell(msg, content)) is not None:
        meta = _make_meta(status="error", source="content_analysis", **shell_attrs)
    elif any(m in content_lower for m in _PARTIAL_MARKERS):
        meta = _make_meta(
            status="partial_success",
            source="content_analysis",
            recommended_next_action="rewrite_query",
        )
    else:
        meta = _make_meta(status="success", source="content_analysis")

    updated_kwargs = dict(msg.additional_kwargs or {})
    updated_kwargs[TOOL_META_KEY] = meta
    msg.additional_kwargs = updated_kwargs
    return msg


def normalize_tool_result(result: ToolMessage | Command) -> ToolMessage | Command:
    """Normalize a tool result, handling Command wrappers transparently."""
    if isinstance(result, ToolMessage):
        return normalize_tool_message(result)
    return result
