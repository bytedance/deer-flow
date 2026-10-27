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
import re
from datetime import UTC, datetime
from typing import TypedDict

from langchain_core.messages import AIMessage, ToolMessage

from deerflow.agents.middlewares.tool_result_meta import TOOL_META_KEY

TOOL_RECEIPT_KEY = "deerflow_tool_receipt"
TOOL_RECEIPT_LEDGER_KEY = "deerflow_tool_receipt_ledger"

_HASH_LEN = 16
_RENDER_CHAR_BUDGET = 2000

#: Single source of truth for the citation wire format. Id assignment, ledger
#: validation, the model-facing prompt example, and the parent-side verifier
#: all derive from these — the format changes in exactly one place.
RECEIPT_ID_PREFIX = "r"
_MAX_RECEIPT_ID_DIGITS = 10


def receipt_id(position: int) -> str:
    """Display id for the ``position``-th receipt (1-based): ``r1``..``rN``."""
    return f"{RECEIPT_ID_PREFIX}{position}"


#: ``[r2]`` bare or ``[r2 write_file]`` anchored. The optional label lets the
#: verifier sanity-check claim-evidence coherence.
CITATION_RE = re.compile(rf"\[{RECEIPT_ID_PREFIX}(\d+)(?:\s+([A-Za-z_][\w.-]*))?\]")


def format_citation(rid: str, tool_name: str | None = None) -> str:
    """Canonical model-facing citation (``[r2]`` bare, ``[r2 write_file]`` anchored)."""
    return f"[{rid} {tool_name}]" if tool_name else f"[{rid}]"


def parse_citations(text: str) -> list[tuple[str, str | None]]:
    """Pull ``(id, anchor)`` pairs out of report prose, deduped first-seen."""
    seen: set[tuple[str, str | None]] = set()
    citations: list[tuple[str, str | None]] = []
    for match in CITATION_RE.finditer(text):
        digits = match.group(1)
        # Model output is untrusted.  Bound the decimal string before int()
        # so an enormous citation id cannot trip Python's conversion limit and
        # turn an otherwise successful task into a verification exception.
        if len(digits) > _MAX_RECEIPT_ID_DIGITS:
            continue
        rid = receipt_id(int(digits))
        citation = (rid, match.group(2))
        if citation in seen:
            continue
        seen.add(citation)
        citations.append(citation)
    return citations


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
        if not is_valid_receipt(receipt):
            continue
        receipts.append(
            ToolReceipt(
                id=receipt_id(len(receipts) + 1),
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


def extract_citing_turn_receipts(messages: list) -> list[ToolReceipt] | None:
    """Return the ledger snapshot shown to the last citing assistant turn.

    ``ToolReceiptMiddleware`` stamps this runtime-owned snapshot on each model
    response that received a receipt ledger. Unlike a terminal re-scan of tool
    messages, these positional display ids remain the ids the response could
    actually cite even if summarization later compacts and renumbers history.
    """
    for message in reversed(messages):
        if not isinstance(message, AIMessage):
            continue
        raw_ledger = (message.additional_kwargs or {}).get(TOOL_RECEIPT_LEDGER_KEY)
        if raw_ledger is None:
            continue
        if not isinstance(raw_ledger, list):
            return None
        receipts: list[ToolReceipt] = []
        first_position: int | None = None
        for index, receipt in enumerate(raw_ledger):
            if not is_valid_receipt(receipt):
                return None
            rid = receipt.get("id")
            match = re.fullmatch(rf"{re.escape(RECEIPT_ID_PREFIX)}([1-9]\d*)", rid) if isinstance(rid, str) else None
            if match is None:
                return None
            if first_position is None:
                first_position = int(match.group(1))
            if rid != receipt_id(first_position + index):
                return None
            receipts.append(
                ToolReceipt(
                    id=receipt["id"],
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
    return None


_RECEIPT_STR_FIELDS = ("tool_call_id", "tool_name", "status", "args_sha256", "output_sha256", "created_at")


def is_valid_receipt(receipt: object) -> bool:
    """Structural check for a persisted receipt (types only, not provenance)."""
    if not isinstance(receipt, dict):
        return False
    if any(not isinstance(receipt.get(field), str) for field in _RECEIPT_STR_FIELDS):
        return False
    output_bytes = receipt.get("output_bytes")
    return isinstance(output_bytes, int) and not isinstance(output_bytes, bool)


def render_tool_receipts_with_snapshot(
    receipts: list[ToolReceipt],
    *,
    max_chars: int = _RENDER_CHAR_BUDGET,
) -> tuple[str, list[ToolReceipt]]:
    """Render a ledger and return the exact receipt subset visible in it.

    The retained receipts keep their original display ids.  Callers that
    persist a citing-turn ledger must use this snapshot rather than the full
    input list, otherwise a citation could resolve against an entry omitted by
    the model context budget.
    """
    if not receipts:
        return "", []
    lines = [
        "## Tool receipts (execution record)",
        # The example is generated from format_citation/parse_citations' shared
        # format so the instruction can never drift from the verifier.
        f"Cite receipt ids (e.g. {format_citation(receipt_id(1), 'write_file')}) in your final report for every claim about an action you took.",
        # Anti-automation-bias (design rule 4): the ledger always states its
        # evidence boundary so the model never reads provenance as endorsement.
        "Execution evidence only — receipts record that a call happened and its status; they do not validate claim correctness or task acceptance.",
    ]
    receipt_lines = [f"- [{receipt['id']}] {receipt['tool_name']} status={receipt['status']} args_sha256={receipt['args_sha256']} output_sha256={receipt['output_sha256']} bytes={receipt['output_bytes']}" for receipt in receipts]
    if len("\n".join([*lines, *receipt_lines])) <= max_chars:
        lines.extend(receipt_lines)
        retained_receipts = receipts
    else:
        omission = "- ... older receipts omitted (context budget)"
        retained: list[str] = []
        retained_count = 0
        for line in reversed(receipt_lines):
            candidate = [*lines, omission, line, *retained]
            if len("\n".join(candidate)) > max_chars:
                break
            retained.insert(0, line)
            retained_count += 1
        lines.extend([omission, *retained])
        retained_receipts = receipts[-retained_count:] if retained_count else []
    rendered = "\n".join(lines)
    if len(rendered) > max_chars:
        rendered = rendered[: max(0, max_chars - 4)] + "\n..."
        retained_receipts = []
    return rendered, retained_receipts


def render_tool_receipts(receipts: list[ToolReceipt], *, max_chars: int = _RENDER_CHAR_BUDGET) -> str:
    """Render the receipt ledger as model-visible context (empty -> "")."""
    rendered, _ = render_tool_receipts_with_snapshot(receipts, max_chars=max_chars)
    return rendered
