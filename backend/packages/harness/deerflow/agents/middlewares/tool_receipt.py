"""Deterministic tool-call receipts: the zero-LLM verification layer.

Every tool result gets a receipt stamped into ``additional_kwargs`` by
``ToolReceiptMiddleware``. Receipts are *derived* from the message stream
(never stored separately), so rendering for the model and harvesting for the
parent agent always agree. Display ids (``r1..rN``) are positional over the
append-only message list, which keeps them stable across turns — but only
while history stays append-only (see the renumbering caveat below).

Layering contract: a tool receipt is an immutable *fact* record per tool call,
message-carried. It is distinct from the runtime-layer run delivery receipt
(``run.delivery`` event, one per run, event-store-carried) — the two layers
share only the verdict *structure* convention (``source``/``requirement`` +
details); the ``satisfied`` boolean stays exclusive to the runtime hard gate,
and advisory layers use neutral vocabulary (``citation_resolved``,
``supported``) so the model never conflates evidence with acceptance.

Freshness caveat: receipts capture execution truth (the raw tool return,
stamped before sanitization/truncation rewrites content further out the
chain). After compaction, only the sanitized ``content`` survives — so
``output_sha256`` is a *freshness stamp*, not a re-checkable fingerprint
against the persisted message.

Renumbering caveat: compaction/summarization (which long subagent runs use)
drops older ``ToolMessage``s, and since display ids are assigned positionally
in ``extract_tool_receipts``, the surviving receipts renumber — an ``[r3]``
cited before compaction can point at a different tool call (or nothing)
after. Layer 2 citation verification must therefore resolve ``[rN]``
references against the ledger as of the citing turn, not the post-compaction
ledger.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import TypedDict

from langchain_core.messages import ToolMessage

from deerflow.agents.middlewares.tool_result_meta import TOOL_META_KEY

TOOL_RECEIPT_KEY = "deerflow_tool_receipt"
# Carried only on the parent ``task`` result.  The value is produced from the
# child graph's stamped ToolMessages; external input is stripped at the Gateway
# boundary before it can enter a run.
SUBAGENT_TOOL_RECEIPTS_KEY = "deerflow_subagent_tool_receipts"

_HASH_LEN = 16
_RENDER_CHAR_BUDGET = 2000
_MAX_RECEIPT_FIELD_CHARS = 256
_MAX_SUBAGENT_RECEIPTS = 256


class ToolReceipt(TypedDict):
    id: str  # display id, assigned by extract_tool_receipts ("r1"..)
    tool_call_id: str
    tool_name: str
    status: str  # success | error | partial_success (from deerflow_tool_meta)
    args_sha256: str
    output_sha256: str
    output_bytes: int
    created_at: str


def _short_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:_HASH_LEN]


def make_tool_receipt(tool_call: dict, message: ToolMessage) -> dict:
    """Build a receipt for one tool call/result pair (no display id yet)."""
    args = tool_call.get("args")
    args_bytes = json.dumps(args if isinstance(args, dict) else {}, sort_keys=True, default=str).encode("utf-8")
    content = message.content if isinstance(message.content, str) else json.dumps(message.content, sort_keys=True, default=str)
    meta = (message.additional_kwargs or {}).get(TOOL_META_KEY) or {}
    status = str(meta.get("status") or getattr(message, "status", "success") or "success")
    return {
        "tool_call_id": str(tool_call.get("id") or ""),
        "tool_name": str(tool_call.get("name") or ""),
        "status": status,
        "args_sha256": _short_hash(args_bytes),
        "output_sha256": _short_hash(content.encode("utf-8")),
        "output_bytes": len(content.encode("utf-8")),
        "created_at": datetime.now(UTC).isoformat(),
    }


def extract_tool_receipts(messages: list) -> list[ToolReceipt]:
    """Collect stamped receipts in message order, assigning display ids r1..rN.

    Receipt dicts come back out of persisted checkpoints, so their shape is
    validated before use: a malformed entry (missing/wrongly-typed fields, or
    extra keys) is skipped rather than crashing the render path or being
    treated as runtime-stamped evidence.
    """
    receipts: list[ToolReceipt] = []
    for message in messages:
        if not isinstance(message, ToolMessage):
            continue
        receipt = (message.additional_kwargs or {}).get(TOOL_RECEIPT_KEY)
        if not _is_valid_receipt(receipt):
            continue
        receipts.append(
            ToolReceipt(
                id=f"r{len(receipts) + 1}",
                tool_call_id=receipt["tool_call_id"],
                tool_name=receipt["tool_name"],
                status=receipt["status"],
                args_sha256=receipt["args_sha256"],
                output_sha256=receipt["output_sha256"],
                output_bytes=receipt["output_bytes"],
                created_at=receipt["created_at"],
            )
        )
    return receipts


def extract_serialized_tool_receipts(messages: list[dict]) -> list[ToolReceipt]:
    """Extract child receipts from serialized subagent step messages.

    ``SubagentResult.ai_messages`` stores ``BaseMessage.model_dump()`` values,
    not live ``ToolMessage`` instances.  Keep this parser deliberately strict
    and bounded because its output crosses the subagent boundary in a parent
    ``ToolMessage``.
    """
    receipts: list[ToolReceipt] = []
    for message in messages:
        if not isinstance(message, dict) or message.get("type") != "tool":
            continue
        additional_kwargs = message.get("additional_kwargs")
        if not isinstance(additional_kwargs, dict):
            continue
        receipt = additional_kwargs.get(TOOL_RECEIPT_KEY)
        if not _is_valid_receipt(receipt):
            continue
        receipts.append(
            ToolReceipt(
                id=f"r{len(receipts) + 1}",
                tool_call_id=receipt["tool_call_id"],
                tool_name=receipt["tool_name"],
                status=receipt["status"],
                args_sha256=receipt["args_sha256"],
                output_sha256=receipt["output_sha256"],
                output_bytes=receipt["output_bytes"],
                created_at=receipt["created_at"],
            )
        )
        if len(receipts) >= _MAX_SUBAGENT_RECEIPTS:
            break
    return receipts


def child_receipts_for_result(messages: list[dict] | None) -> list[dict[str, object]]:
    """Return a bounded, JSON-safe receipt bundle for a parent task result."""
    return [dict(receipt) for receipt in extract_serialized_tool_receipts(messages or [])]


def _validated_child_receipts(value: object) -> list[ToolReceipt]:
    """Read a task result's server-generated child receipt bundle."""
    if not isinstance(value, list):
        return []
    receipts: list[ToolReceipt] = []
    for entry in value[:_MAX_SUBAGENT_RECEIPTS]:
        if not isinstance(entry, dict) or not _is_valid_receipt(entry):
            continue
        raw_id = entry.get("id")
        receipt_id = raw_id if isinstance(raw_id, str) and len(raw_id) <= 32 else f"r{len(receipts) + 1}"
        receipts.append(
            ToolReceipt(
                id=receipt_id,
                tool_call_id=entry["tool_call_id"],
                tool_name=entry["tool_name"],
                status=entry["status"],
                args_sha256=entry["args_sha256"],
                output_sha256=entry["output_sha256"],
                output_bytes=entry["output_bytes"],
                created_at=entry["created_at"],
            )
        )
    return receipts


def render_receipt_ledger(messages: list, *, max_chars: int = _RENDER_CHAR_BUDGET) -> str:
    """Render direct and cross-subagent receipts into one bounded ledger."""
    if max_chars <= 0:
        return ""
    direct = extract_tool_receipts(messages)
    child_lines: list[str] = []
    for message in messages:
        if not isinstance(message, ToolMessage):
            continue
        child = _validated_child_receipts((message.additional_kwargs or {}).get(SUBAGENT_TOOL_RECEIPTS_KEY))
        if not child:
            continue
        scope = str(message.tool_call_id or "unknown")
        child_lines.extend(
            f"- [task:{scope}/{receipt['id']}] (child citation [{receipt['id']}]) "
            f"{receipt['tool_name']} status={receipt['status']} "
            f"args_sha256={receipt['args_sha256']} output_sha256={receipt['output_sha256']} "
            f"bytes={receipt['output_bytes']}"
            for receipt in child
        )

    if not child_lines:
        return render_tool_receipts(direct, max_chars=max_chars)

    # Child evidence is the reason this ledger crosses the graph boundary, so
    # reserve it first.  Retain the newest child actions when the budget is
    # tight; unlike a final string slice this cannot drop the entire child
    # section after a long direct-tool history.
    child_header = [
        "## Subagent tool receipts (execution record)",
        "Child ids are task-scoped: [task:<task-call-id>/rN]; child [rN] maps to that id.",
        "Execution evidence only; not proof of correctness or acceptance.",
    ]
    omission = "- ... older child receipts omitted (context budget)"
    retained: list[str] = []
    for line in reversed(child_lines):
        candidate = [*child_header, omission, line, *retained]
        if len("\n".join(candidate)) > max_chars:
            break
        retained.insert(0, line)
    omitted = len(retained) < len(child_lines)
    child_parts = [*child_header]
    if omitted:
        child_parts.append(omission)
    child_parts.extend(retained)
    child_rendered = "\n".join(child_parts)

    # A very small caller budget can be shorter than the explanatory header.
    # Keep a compact, qualified receipt id rather than returning a header-only
    # truncation that makes the delegated evidence unreachable.
    if not retained:
        latest_line = child_lines[-1]
        minimal = ["## Subagent receipts", latest_line]
        child_rendered = "\n".join(minimal)
        child_rendered = _bound_rendered_text(child_rendered, max_chars)

    # Direct receipts are useful context, but must not displace the child
    # records.  Render only what fits before the reserved child section.
    direct_budget = max_chars - len(child_rendered) - 2
    # ``render_tool_receipts`` has its own explanatory header.  If the
    # remaining budget cannot fit that header, omit direct records entirely so
    # they cannot displace or truncate the child evidence.
    direct_header_min = len(
        "\n".join(
            [
                "## Tool receipts (execution record)",
                "Cite receipt ids (e.g. [r1]) in your final report for every claim about an action you took.",
                "Execution evidence only — receipts record that a call happened and its status; they do not validate claim correctness or task acceptance.",
            ]
        )
    )
    direct_rendered = render_tool_receipts(direct, max_chars=direct_budget) if direct_budget >= direct_header_min else ""
    rendered = "\n\n".join(part for part in (direct_rendered, child_rendered) if part)
    return _bound_rendered_text(rendered, max_chars)


_RECEIPT_STR_FIELDS = ("tool_call_id", "tool_name", "status", "args_sha256", "output_sha256", "created_at")


def _is_valid_receipt(receipt: object) -> bool:
    """Structural check for a persisted receipt (types only, not provenance)."""
    if not isinstance(receipt, dict):
        return False
    if any(not isinstance(receipt.get(field), str) or len(receipt[field]) > _MAX_RECEIPT_FIELD_CHARS for field in _RECEIPT_STR_FIELDS):
        return False
    output_bytes = receipt.get("output_bytes")
    return isinstance(output_bytes, int) and not isinstance(output_bytes, bool) and output_bytes >= 0


def render_tool_receipts(receipts: list[ToolReceipt], *, max_chars: int = _RENDER_CHAR_BUDGET) -> str:
    """Render the receipt ledger as model-visible context (empty -> "")."""
    if not receipts or max_chars <= 0:
        return ""
    lines = [
        "## Tool receipts (execution record)",
        "Cite receipt ids (e.g. [r1]) in your final report for every claim about an action you took.",
        # Anti-automation-bias (design rule 4): the ledger always states its
        # evidence boundary so the model never reads provenance as endorsement.
        "Execution evidence only — receipts record that a call happened and its status; they do not validate claim correctness or task acceptance.",
    ]
    receipt_lines = [f"- [{receipt['id']}] {receipt['tool_name']} status={receipt['status']} args_sha256={receipt['args_sha256']} output_sha256={receipt['output_sha256']} bytes={receipt['output_bytes']}" for receipt in receipts]
    if len("\n".join([*lines, *receipt_lines])) <= max_chars:
        lines.extend(receipt_lines)
    else:
        omission = "- ... older receipts omitted (context budget)"
        retained: list[str] = []
        for line in reversed(receipt_lines):
            candidate = [*lines, omission, line, *retained]
            if len("\n".join(candidate)) > max_chars:
                break
            retained.insert(0, line)
        lines.extend([omission, *retained])
    rendered = "\n".join(lines)
    return _bound_rendered_text(rendered, max_chars)


def _bound_rendered_text(text: str, max_chars: int) -> str:
    """Truncate rendered context without exceeding the caller's hard budget."""
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    if max_chars <= 4:
        return text[:max_chars]
    return text[: max_chars - 4] + "\n..."
