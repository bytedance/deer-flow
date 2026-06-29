"""Lead-agent middleware: a system-maintained ledger of delegated subtasks.

Issue: the lead repeatedly re-delegated the same research because the context
held no durable record of what it had already dispatched (the record was lost
to summarization). This middleware keeps that record in ThreadState (which
summarization does not touch) and re-injects it into every model call, so the
model always sees "already delegated: ..." and stops re-delegating.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, ToolMessage

from deerflow.agents.thread_state import DelegationEntry
from deerflow.subagents.status_contract import SUBAGENT_STATUS_KEY, extract_subagent_status


def extract_delegations(messages: list) -> list[DelegationEntry]:
    """Derive delegation entries from the visible message list, in dispatch order.

    A ``task`` tool-call is a dispatch (status "in_progress"); its matching
    ToolMessage upgrades the status from the structured ``subagent_status`` kwarg,
    or by parsing the result text as a fallback (same contract the frontend uses).
    """
    by_id: dict[str, DelegationEntry] = {}

    for message in messages:
        if isinstance(message, AIMessage):
            for call in message.tool_calls or []:
                if call.get("name") != "task":
                    continue
                task_id = call.get("id")
                if not task_id or task_id in by_id:
                    continue
                args = call.get("args") or {}
                by_id[task_id] = {
                    "task_id": task_id,
                    "description": args.get("description") or "",
                    "subagent_type": args.get("subagent_type") or "",
                    "status": "in_progress",
                }
        elif isinstance(message, ToolMessage):
            entry = by_id.get(message.tool_call_id or "")
            if entry is None:
                continue
            status = message.additional_kwargs.get(SUBAGENT_STATUS_KEY)
            if not status:
                content = message.content if isinstance(message.content, str) else str(message.content)
                status = extract_subagent_status(content)
            if status:
                entry["status"] = status

    return list(by_id.values())


def format_delegation_block(entries: list[DelegationEntry]) -> str | None:
    """Render the ledger as a hidden <system-reminder>, or None when empty."""
    if not entries:
        return None

    lines = [
        "<system-reminder>",
        "<delegated_subtasks>",
        "You have ALREADY delegated these subtasks in this run. Do NOT re-delegate the same work; reuse or build on their results instead.",
    ]
    for entry in entries:
        lines.append(f"- [{entry['status']}] ({entry['subagent_type']}) {entry['description']}")
    lines.append("</delegated_subtasks>")
    lines.append("</system-reminder>")
    return "\n".join(lines)
