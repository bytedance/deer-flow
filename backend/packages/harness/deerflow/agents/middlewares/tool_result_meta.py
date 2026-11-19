"""Unified tool result semantics for structured signal production.

Every tool result that passes through ToolErrorHandlingMiddleware gets a
``deerflow_tool_meta`` entry in additional_kwargs. Downstream consumers
(ToolProgressMiddleware, etc.) read this key instead of parsing text.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal, get_args

from langchain_core.messages import ToolMessage
from langgraph.types import Command

from deerflow.agents.middlewares.tool_transform_meta import append_tool_transform, read_tool_transforms
from deerflow.utils.bash_exit import BASH_TOOL_NAMES, bash_exit_status

TOOL_META_KEY = "deerflow_tool_meta"
PROGRESS_GUARD_ERROR_TYPE = "blocked_by_progress_guard"

ToolResultStatus = Literal["success", "error", "partial_success"]
RecommendedNextAction = Literal["continue", "rewrite_query", "try_alternative", "summarize", "stop"]
TOOL_RESULT_STATUSES = frozenset(get_args(ToolResultStatus)) | {"unknown"}
TOOL_RESULT_NEXT_ACTIONS = frozenset(get_args(RecommendedNextAction)) | {"unknown"}

_ERROR_PREFIX = "Error:"


@dataclass(frozen=True, slots=True)
class ToolResultMeta:
    status: ToolResultStatus
    error_type: str | None
    recoverable_by_model: bool
    recommended_next_action: RecommendedNextAction
    source: Literal["exception", "tool_return", "content_analysis", "progress_middleware"]


_UNKNOWN_ERROR: dict[str, object] = {
    "error_type": "unknown",
    "recoverable_by_model": True,
    "recommended_next_action": "try_alternative",
}
TOOL_RESULT_ERROR_TYPES = frozenset({"auth", "rate_limited", "transient", "config", "permission", "no_results", "not_found", "internal", "unknown", PROGRESS_GUARD_ERROR_TYPE})


class _ModelToolResultText(str):
    """Request-local encoding marker; copied or persisted text is never trusted."""


def tool_result_for_model(message: ToolMessage) -> ToolMessage:
    """Expose reported execution status separately from textual result data.

    Provider serializers drop additional_kwargs (and often ToolMessage.status).
    Project only validated status/source fields, never arbitrary metadata or
    artifacts. Keep the original message for checkpoints, UI and receipt hashes.
    Legacy content-analysis stamps and native multimodal blocks pass through.
    """
    if not isinstance(message.content, str) or isinstance(message.content, _ModelToolResultText):
        return message
    meta = (message.additional_kwargs or {}).get(TOOL_META_KEY)
    if not isinstance(meta, dict):
        return message
    status, source = meta.get("status"), meta.get("source")
    if not isinstance(status, str) or status not in get_args(ToolResultStatus):
        return message
    if not isinstance(source, str) or source not in {"tool_return", "exception", "progress_middleware"}:
        return message
    envelope = {TOOL_META_KEY: {"status": status, "source": source}, "content": message.content}
    # A successful invocation can subsequently have its visible text shortened
    # by a budget wrapper. Expose that fact separately from execution status.
    transforms = [entry["kind"] for entry in read_tool_transforms(message) if entry["kind"] in {"truncated", "externalized"}]
    if transforms:
        envelope["content_transforms"] = list(dict.fromkeys(transforms))
    content = _ModelToolResultText(json.dumps(envelope, ensure_ascii=False))
    kwargs = dict(message.additional_kwargs or {})
    append_tool_transform(kwargs, "structured_tool_result", by="ToolErrorHandlingMiddleware")
    return message.model_copy(update={"content": content, "additional_kwargs": kwargs})


def _http_error_category(status: object) -> str | None:
    if not isinstance(status, int) or isinstance(status, bool) or not 400 <= status <= 599:
        return None
    if status in (401, 403):
        return "auth"
    if status == 429:
        return "rate_limited"
    if status in (408, 502, 503, 504):
        return "transient"
    if status == 404:
        return "not_found"
    if status >= 500:
        return "internal"
    return "unknown"


def classify_exception(exc: BaseException | str) -> dict[str, object]:
    """Classify actual exception types and HTTP status attributes, never prose."""
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    category = _http_error_category(status)
    if category is None:
        if isinstance(exc, (TimeoutError, ConnectionError)):
            category = "transient"
        elif isinstance(exc, PermissionError):
            category = "permission"
        elif isinstance(exc, FileNotFoundError):
            category = "not_found"
    # A failed request does not establish permanent tool unavailability.
    return {**_UNKNOWN_ERROR, "error_type": category or "unknown"}


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
    except (json.JSONDecodeError, ValueError, RecursionError):
        return None
    error = data.get("error") if isinstance(data, dict) else None
    if not error:
        return None
    if isinstance(error, str) and error.lower().strip() in _SEMANTIC_ZERO_ERROR_STRINGS:
        return None
    # Preserve the error payload in a predictable JSON representation. Its prose
    # is diagnostic context, not evidence for a category or recovery decision.
    return error if isinstance(error, str) else json.dumps(error)


def _make_meta(*, status: str, source: str, error_type: str | None = None, recoverable_by_model: bool = True, recommended_next_action: str = "continue") -> dict[str, object]:
    return {
        "status": status,
        "error_type": error_type,
        "recoverable_by_model": recoverable_by_model,
        "recommended_next_action": recommended_next_action,
        "source": source,
    }


def stamp_exception_meta(msg: ToolMessage, exc_info: BaseException | str) -> ToolMessage:
    """Stamp deerflow_tool_meta with source='exception' onto an exception-derived ToolMessage.

    Unlike normalize_tool_message (which preserves existing stamps), this function always
    overwrites any pre-existing TOOL_META_KEY entry.  Exception-derived classification is
    more authoritative than a tool's own return-time stamp.
    """
    attrs = classify_exception(exc_info)
    updated_kwargs = dict(msg.additional_kwargs or {})
    updated_kwargs[TOOL_META_KEY] = _make_meta(status="error", source="exception", **attrs)
    msg.additional_kwargs = updated_kwargs
    return msg


# Structured task/subagent failures (see subagents/status_contract.py). These
# producers put authoritative status in additional_kwargs["subagent_status"] while
# leaving ToolMessage.status at LangChain's default "success" and using display
# text that does not start with "Error:" — so content heuristics alone mis-label
# them as success. Honor the structured field before any content analysis.
_SUBAGENT_FAILURE_STATUSES = frozenset({"failed", "cancelled", "timed_out", "polling_timed_out"})


def normalize_tool_message(msg: ToolMessage) -> ToolMessage:
    """Attach tool status, correcting legacy bash analysis that missed an exit."""
    content = msg.content if isinstance(msg.content, str) else ""
    bash_status = bash_exit_status(content) if msg.name in BASH_TOOL_NAMES else None
    failed_bash = bash_status is not None and bash_status[0] == "error"
    existing = (msg.additional_kwargs or {}).get(TOOL_META_KEY)
    if existing is not None:
        # Explicit producer stamps remain authoritative. Older checkpoints can
        # contain generic analysis success for a provider-reported failed exit.
        if not (failed_bash and isinstance(existing, dict) and existing.get("source") == "content_analysis" and existing.get("status") == "success"):
            return msg

    kwargs = msg.additional_kwargs or {}
    subagent_status = kwargs.get("subagent_status")
    artifact = msg.artifact if isinstance(msg.artifact, dict) else {}
    response = artifact.get("deerflow_http_response")
    category = _http_error_category(response.get("status_code")) if isinstance(response, dict) else None
    # Producer status and native exit markers describe execution. Documents do not.
    if isinstance(subagent_status, str) and subagent_status in _SUBAGENT_FAILURE_STATUSES:
        attrs = {**_UNKNOWN_ERROR}
        if subagent_status in {"timed_out", "polling_timed_out"}:
            attrs["error_type"] = "transient"
        meta = _make_meta(status="error", source="tool_return", **attrs)
    elif category is not None:
        meta = _make_meta(status="error", source="tool_return", **{**_UNKNOWN_ERROR, "error_type": category})
    elif msg.status == "error":
        meta = _make_meta(status="error", source="tool_return", **_UNKNOWN_ERROR)
    elif content.startswith(_ERROR_PREFIX):
        # Legacy tool envelopes, including unstamped read_file checkpoints, use
        # this prefix. Producer-stamped successful file contents return above.
        meta = _make_meta(status="error", source="tool_return", **_UNKNOWN_ERROR)
    elif msg.name != "read_file" and _extract_json_error_text(content) is not None:
        meta = _make_meta(status="error", source="tool_return", **_UNKNOWN_ERROR)
    elif failed_bash:
        meta = _make_meta(status="error", source="content_analysis", **_UNKNOWN_ERROR)
    else:
        meta = _make_meta(status="success", source="tool_return")

    updated_kwargs = dict(msg.additional_kwargs or {})
    updated_kwargs[TOOL_META_KEY] = meta
    msg.additional_kwargs = updated_kwargs
    return msg


def _command_messages(result: Command) -> list | tuple | None:
    update = result.update
    if not isinstance(update, dict):
        return None
    messages = update.get("messages")
    if isinstance(messages, ToolMessage):
        return [messages]
    if isinstance(messages, (list, tuple)):
        return messages
    return None


def normalize_tool_result(result: ToolMessage | Command, *, tool_call_id: str = "") -> ToolMessage | Command:
    """Normalize a tool result, handling Command wrappers transparently.

    When ``tool_call_id`` is provided, only the matching ``ToolMessage`` inside a
    Command is stamped. Other Command fields and unrelated messages are left intact.
    Producer-supplied ``deerflow_tool_meta`` is preserved by ``normalize_tool_message``.
    """
    if isinstance(result, ToolMessage):
        return normalize_tool_message(result)
    messages = _command_messages(result)
    if messages is None:
        return result
    for message in messages:
        if not isinstance(message, ToolMessage):
            continue
        if tool_call_id and str(message.tool_call_id) != tool_call_id:
            continue
        normalize_tool_message(message)
    return result
