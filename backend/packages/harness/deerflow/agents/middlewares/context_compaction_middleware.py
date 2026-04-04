"""Low-cost message cleanup before expensive summarization kicks in."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from copy import copy

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from deerflow.config.context_management_config import get_context_management_config

_UPLOAD_BLOCK_RE = re.compile(r"<uploaded_files>[\s\S]*?</uploaded_files>\n*", re.IGNORECASE)
_STRIPPED_UPLOAD_PLACEHOLDER = "[Earlier uploaded file listing omitted to reduce context.]"
_COMPACTED_TOOL_RESULT_TEMPLATE = (
    "[Older {tool_name} result omitted to reduce context. Re-run the tool with a narrower command or line range if needed.]"
)
_SESSION_COLLAPSE_TAG = "<session_history_summary>"


def _replace_message_content(msg, content: str):
    updated = copy(msg)
    updated.content = content
    return updated


def _truncate_text(value: str, *, limit: int) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return f"{text[: max(limit - 3, 0)].rstrip()}..."


def _strip_historical_upload_blocks(messages: list) -> list | None:
    human_indices = [idx for idx, msg in enumerate(messages) if isinstance(msg, HumanMessage)]
    if len(human_indices) <= 1:
        return None

    patched = list(messages)
    changed = False

    for idx in human_indices[:-1]:
        msg = patched[idx]
        if not isinstance(msg.content, str) or "<uploaded_files>" not in msg.content:
            continue
        stripped = _UPLOAD_BLOCK_RE.sub("", msg.content).strip()
        replacement = stripped if stripped else _STRIPPED_UPLOAD_PLACEHOLDER
        if replacement != msg.content:
            patched[idx] = _replace_message_content(msg, replacement)
            changed = True

    return patched if changed else None


def _compact_old_tool_results(messages: list) -> list | None:
    config = get_context_management_config().microcompact
    if not config.enabled:
        return None

    compactable = set(config.compactable_tools)
    candidate_indices: list[int] = []
    for idx, msg in enumerate(messages):
        if not isinstance(msg, ToolMessage):
            continue
        if msg.name not in compactable:
            continue
        if msg.status == "error":
            continue
        if not isinstance(msg.content, str):
            continue
        if len(msg.content) < config.min_content_chars:
            continue
        if msg.content.startswith("[Older ") and "result omitted to reduce context" in msg.content:
            continue
        candidate_indices.append(idx)

    if len(candidate_indices) <= config.keep_recent_tool_results:
        return None

    keep = set(candidate_indices[-config.keep_recent_tool_results :])
    patched = list(messages)
    changed = False
    for idx in candidate_indices:
        if idx in keep:
            continue
        msg = patched[idx]
        placeholder = _COMPACTED_TOOL_RESULT_TEMPLATE.format(tool_name=msg.name or "tool")
        if msg.content != placeholder:
            patched[idx] = _replace_message_content(msg, placeholder)
            changed = True

    return patched if changed else None


def _find_safe_collapse_start(messages: list, keep_recent_messages: int) -> int:
    start = max(len(messages) - keep_recent_messages, 0)
    changed = True
    while changed and start > 0:
        changed = False
        for idx in range(start, len(messages)):
            msg = messages[idx]
            if not isinstance(msg, ToolMessage) or not msg.tool_call_id:
                continue
            for search_idx in range(idx - 1, -1, -1):
                prior = messages[search_idx]
                if not isinstance(prior, AIMessage) or not prior.tool_calls:
                    continue
                if any(tc.get("id") == msg.tool_call_id for tc in prior.tool_calls):
                    if search_idx < start:
                        start = search_idx
                        changed = True
                    break
    return start


def _build_session_history_summary(prefix: list) -> str | None:
    session_config = get_context_management_config().session_state
    if not prefix:
        return None

    latest_goal = None
    recent_ai_updates: list[str] = []
    recent_tool_observations: list[str] = []

    for msg in reversed(prefix):
        if latest_goal is None and isinstance(msg, HumanMessage):
            content = msg.content if isinstance(msg.content, str) else ""
            if "<uploaded_files>" in content:
                content = _UPLOAD_BLOCK_RE.sub("", content).strip()
            if (
                not content
                or "<system_reminder>" in content
                or "<session_state>" in content
                or "<session_history_summary>" in content
            ):
                continue
            if content:
                latest_goal = _truncate_text(content, limit=session_config.max_goal_chars)
        if isinstance(msg, AIMessage) and not getattr(msg, "tool_calls", None) and isinstance(msg.content, str) and msg.content.strip():
            recent_ai_updates.append(_truncate_text(msg.content, limit=session_config.max_response_chars))
            if len(recent_ai_updates) >= 2:
                break

    for msg in reversed(prefix):
        if not isinstance(msg, ToolMessage):
            continue
        if msg.status == "error" or not isinstance(msg.content, str):
            continue
        content = msg.content.strip()
        if not content:
            continue
        recent_tool_observations.append(
            f"- {msg.name or 'tool'}: {_truncate_text(content, limit=session_config.max_tool_observation_chars)}"
        )
        if len(recent_tool_observations) >= session_config.max_tool_observations:
            break

    lines = [_SESSION_COLLAPSE_TAG, "Older thread history has been collapsed. Treat this as authoritative session context."]
    if latest_goal:
        lines.extend(["", f"Current goal before the recent working set: {latest_goal}"])
    if recent_ai_updates:
        lines.extend(["", "Important prior conclusions:"])
        lines.extend(f"- {item}" for item in reversed(recent_ai_updates))
    if recent_tool_observations:
        lines.extend(["", "Older tool observations worth preserving:"])
        lines.extend(reversed(recent_tool_observations))
    lines.append("\n</session_history_summary>")
    return "\n".join(lines)


def _collapse_old_session_history(messages: list) -> list | None:
    session_config = get_context_management_config().session_state
    if not session_config.enabled or not session_config.collapse_enabled:
        return None
    if len(messages) < session_config.collapse_when_message_count_at_least:
        return None

    start = _find_safe_collapse_start(messages, session_config.keep_recent_messages)
    if start <= 0:
        return None

    prefix = messages[:start]
    suffix = messages[start:]
    summary = _build_session_history_summary(prefix)
    if not summary:
        return None

    collapsed_message = HumanMessage(content=summary)
    return [collapsed_message, *suffix]


def build_compacted_messages(messages: list) -> list | None:
    config = get_context_management_config()
    patched = messages
    changed = False

    if config.snip.enabled and config.snip.strip_historical_upload_blocks:
        stripped = _strip_historical_upload_blocks(patched)
        if stripped is not None:
            patched = stripped
            changed = True

    compacted = _compact_old_tool_results(patched)
    if compacted is not None:
        patched = compacted
        changed = True

    collapsed = _collapse_old_session_history(patched)
    if collapsed is not None:
        patched = collapsed
        changed = True

    return patched if changed else None


class ContextCompactionMiddleware(AgentMiddleware[AgentState]):
    """Trim obviously low-value message content before model invocation."""

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        patched = build_compacted_messages(list(request.messages))
        if patched is not None:
            request = request.override(messages=patched)
        return handler(request)

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        patched = build_compacted_messages(list(request.messages))
        if patched is not None:
            request = request.override(messages=patched)
        return await handler(request)
