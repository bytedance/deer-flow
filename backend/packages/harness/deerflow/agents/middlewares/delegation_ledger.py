"""Deterministic capture and rendering for task delegations."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from html import escape
from typing import Any

from langchain_core.messages import AIMessage, AnyMessage, ToolMessage

from deerflow.agents.thread_state import DelegationEntry
from deerflow.subagents.status_contract import SUBAGENT_STATUS_KEY, extract_subagent_status

_RESULT_BRIEF_CAP = 2000
_DESCRIPTION_CAP = 200
_LEDGER_RENDER_CHAR_BUDGET = 6000
_LEDGER_ENTRY_RESULT_RENDER_CAP = 120
_TASK_SUCCESS_PREFIX = "Task Succeeded. Result:"
_TASK_FAILED_PREFIX = "Task failed. Error:"
_TASK_TIMED_OUT_PREFIX = "Task timed out. Error:"


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _bound_text(text: str, cap: int = _RESULT_BRIEF_CAP) -> str:
    """Deterministic head/tail truncation. This is not an LLM summary."""
    if len(text) <= cap:
        return text
    if cap <= 0:
        return ""
    head = cap * 2 // 3
    omitted_marker = "\n...\n"
    if cap <= len(omitted_marker):
        return text[:cap]
    tail = cap - head - len(omitted_marker)
    if tail <= 0:
        return text[:cap]
    return f"{text[:head]}{omitted_marker}{text[-tail:]}"


def _parse_task_result(content: str, status: str | None = None) -> tuple[str, str] | None:
    text = (content if isinstance(content, str) else str(content)).strip()
    status = status or extract_subagent_status(text)
    if status is None:
        return None
    if status == "completed" and text.startswith(_TASK_SUCCESS_PREFIX):
        return status, text[len(_TASK_SUCCESS_PREFIX) :].strip()
    if status == "failed" and text.startswith(_TASK_FAILED_PREFIX):
        return status, text[len(_TASK_FAILED_PREFIX) :].strip()
    if status == "timed_out" and text.startswith(_TASK_TIMED_OUT_PREFIX):
        return status, text[len(_TASK_TIMED_OUT_PREFIX) :].strip()
    return status, text


def _escape_context_text(value: object) -> str:
    return escape(" ".join(str(value).split()), quote=False)


def _status_guidance(status: str) -> str:
    if status == "in_progress":
        return "already delegated; do NOT delegate again; wait for or build on the result"
    if status == "completed":
        return "completed result; do NOT delegate again; reuse this result"
    if status == "failed":
        return "failed attempt; may retry with a changed plan"
    if status == "cancelled":
        return "cancelled attempt; may retry with a changed plan"
    if status == "timed_out":
        return "timed-out attempt; may retry with a changed plan"
    if status == "polling_timed_out":
        return "polling timed-out attempt; may retry with a changed plan"
    return "prior attempt; inspect status before retrying"


def _tool_call_name(tool_call: dict[str, Any]) -> str:
    name = tool_call.get("name")
    if isinstance(name, str):
        return name
    function = tool_call.get("function")
    if isinstance(function, dict) and isinstance(function.get("name"), str):
        return function["name"]
    return ""


def _tool_call_id(tool_call: dict[str, Any]) -> str | None:
    tool_call_id = tool_call.get("id")
    return str(tool_call_id) if tool_call_id else None


def _tool_call_args(tool_call: dict[str, Any]) -> dict[str, Any]:
    args = tool_call.get("args")
    return args if isinstance(args, dict) else {}


def extract_delegations(messages: list[AnyMessage]) -> list[DelegationEntry]:
    """Enumerate `task` delegations from AI tool calls and paired results."""
    entries_by_id: dict[str, DelegationEntry] = {}
    order: list[str] = []
    now = _utc_now_iso()
    for message in messages:
        if not isinstance(message, AIMessage):
            continue
        for tool_call in message.tool_calls or []:
            if _tool_call_name(tool_call) != "task":
                continue
            tool_call_id = _tool_call_id(tool_call)
            if tool_call_id is None:
                continue
            args = _tool_call_args(tool_call)
            description = str(args.get("description") or args.get("prompt") or "")[:_DESCRIPTION_CAP]
            if tool_call_id not in entries_by_id:
                order.append(tool_call_id)
            entries_by_id[tool_call_id] = {
                "id": tool_call_id,
                "description": description,
                "subagent_type": str(args.get("subagent_type") or ""),
                "status": "in_progress",
                "created_at": now,
            }

    for message in messages:
        if not isinstance(message, ToolMessage):
            continue
        tool_call_id = str(message.tool_call_id) if message.tool_call_id else ""
        entry = entries_by_id.get(tool_call_id)
        if entry is None:
            continue
        content = message.content if isinstance(message.content, str) else str(message.content)
        status = message.additional_kwargs.get(SUBAGENT_STATUS_KEY)
        parsed = _parse_task_result(content, status if isinstance(status, str) else None)
        if parsed is None:
            continue
        status, result_text = parsed
        result_ref = str(message.id or tool_call_id)
        entry.update(
            {
                "status": status,
                "result_brief": _bound_text(result_text),
                "result_sha256": hashlib.sha256(result_text.encode("utf-8")).hexdigest(),
                "result_ref": result_ref,
            }
        )
    return [entries_by_id[tool_call_id] for tool_call_id in order]


def _fits_budget(lines: list[str], candidate: str, max_chars: int) -> bool:
    return len("\n".join([*lines, candidate])) <= max_chars


def _render_entry_line(entry: DelegationEntry) -> str:
    status = _escape_context_text(entry["status"])
    description = _escape_context_text(entry["description"])
    subagent_type = _escape_context_text(entry["subagent_type"])
    guidance = _status_guidance(entry["status"])
    line = f"- [{status}] {description} (via {subagent_type}; {guidance})"
    result_brief = entry.get("result_brief")
    if result_brief:
        line += f" -> {_escape_context_text(_bound_text(result_brief, _LEDGER_ENTRY_RESULT_RENDER_CAP))}"
    return line


def render_delegation_ledger(entries: list[DelegationEntry], *, max_chars: int = _LEDGER_RENDER_CHAR_BUDGET) -> str:
    """Render the delegation ledger as model-visible system context."""
    if not entries:
        return ""

    lines = [
        "## Work already delegated",
        "Newest entries are shown first. In-progress entries are already delegated. Completed entries are reusable results. Failed, cancelled, or timed-out entries are prior attempts.",
    ]
    omitted = 0
    for index, entry in enumerate(reversed(entries)):
        line = _render_entry_line(entry)
        if _fits_budget(lines, line, max_chars):
            lines.append(line)
            continue
        omitted = len(entries) - index
        break

    if omitted:
        omitted_line = f"- ... {omitted} older delegation entries omitted from this model view because of context budget"
        while len(lines) > 1 and not _fits_budget(lines, omitted_line, max_chars):
            lines.pop()
            omitted += 1
            omitted_line = f"- ... {omitted} older delegation entries omitted from this model view because of context budget"
        if _fits_budget(lines, omitted_line, max_chars):
            lines.append(omitted_line)

    rendered = "\n".join(lines)
    if len(rendered) <= max_chars:
        return rendered
    return rendered[: max(0, max_chars - 4)] + "\n..."
