"""Parent-side verification of subagent report citations against tool receipts.

Layer 1 consumption (RFC #4651 PR2): a subagent's final report cites receipt
ids (``[rN]``, optionally anchored ``[rN tool_name]``); this module
cross-checks those citations against the execution record harvested from the
child's own message stream. Pure functions only — no IO, no LLM calls.

Vocabulary layering: the summary boolean is ``citation_resolved``, never
``satisfied``/``verified``/``passed`` — strong-positive words are reserved
for the runtime hard gate so the model never conflates advisory execution
evidence with task acceptance.

Display ids are positional over the ledger shown for one model call. The
receipt middleware stamps that exact ledger on the resulting assistant
message, and terminal harvest uses the snapshot rather than renumbering the
post-compaction tool-message tail. The verdict remains advisory, not a gate.
"""

from __future__ import annotations

from typing import TypedDict

from deerflow.agents.middlewares.tool_receipt import ToolReceipt, parse_citations

VERDICT_SOURCE = "receipt_citations"
VERDICT_REQUIREMENT = "cited_ids_in_execution_record"

#: Anti-automation-bias: model-visible verdict text always states its boundary.
_LIMITATION = "execution evidence only, does not validate claim correctness"


class CitationFailure(TypedDict):
    id: str
    reason: str


class ReceiptVerdict(TypedDict):
    source: str
    requirement: str
    citation_resolved: bool
    cited: list[str]
    resolved: list[str]
    failed: list[CitationFailure]
    unknown: list[str]
    no_citation_claims: bool


def verify_receipt_citations(report_text: str, receipts: list[ToolReceipt]) -> ReceiptVerdict:
    """Cross-check every citation in the report against the harvested ledger."""
    by_id = {receipt["id"]: receipt for receipt in receipts}
    cited: list[str] = []
    resolved: list[str] = []
    failed: list[CitationFailure] = []
    unknown: list[str] = []
    for rid, anchor in parse_citations(report_text):
        cited.append(rid)
        receipt = by_id.get(rid)
        if receipt is None:
            unknown.append(rid)
            continue
        if receipt["status"] != "success":
            failed.append({"id": rid, "reason": f"receipt status={receipt['status']}"})
            continue
        if anchor is not None and anchor != receipt["tool_name"]:
            failed.append({"id": rid, "reason": f"anchor mismatch: cited as {anchor}, receipt {rid} is {receipt['tool_name']}"})
            continue
        resolved.append(rid)
    # Legacy field retained for persisted-contract compatibility; prose is not
    # parsed as a claim. Absence of citations is explicitly unresolved.
    no_citation_claims = False
    citation_resolved = bool(cited) and not failed and not unknown
    return ReceiptVerdict(
        source=VERDICT_SOURCE,
        requirement=VERDICT_REQUIREMENT,
        citation_resolved=citation_resolved,
        cited=cited,
        resolved=resolved,
        failed=failed,
        unknown=unknown,
        no_citation_claims=no_citation_claims,
    )


def validate_receipt_verdict(value: object) -> ReceiptVerdict | None:
    """Structural check for a persisted verdict (read side trusts nothing)."""
    if not isinstance(value, dict):
        return None
    source = value.get("source")
    requirement = value.get("requirement")
    citation_resolved = value.get("citation_resolved")
    no_citation_claims = value.get("no_citation_claims")
    if not isinstance(source, str) or not isinstance(requirement, str):
        return None
    if not isinstance(citation_resolved, bool) or not isinstance(no_citation_claims, bool):
        return None

    def _str_list(key: str) -> list[str] | None:
        items = value.get(key)
        if not isinstance(items, list) or any(not isinstance(item, str) for item in items):
            return None
        return list(items)

    cited = _str_list("cited")
    resolved = _str_list("resolved")
    unknown = _str_list("unknown")
    if cited is None or resolved is None or unknown is None:
        return None
    raw_failed = value.get("failed")
    if not isinstance(raw_failed, list):
        return None
    failed: list[CitationFailure] = []
    for entry in raw_failed:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str) or not isinstance(entry.get("reason"), str):
            return None
        failed.append({"id": entry["id"], "reason": entry["reason"]})
    return ReceiptVerdict(
        source=source,
        requirement=requirement,
        citation_resolved=citation_resolved,
        cited=cited,
        resolved=resolved,
        failed=failed,
        unknown=unknown,
        no_citation_claims=no_citation_claims,
    )


def render_citation_verdict(verdict: ReceiptVerdict) -> str:
    """Render the verdict as the delegation-ledger citation segment."""
    if verdict["no_citation_claims"] or not verdict["cited"]:
        return "citations: UNVERIFIED — no receipt citations"
    parts = [f"{len(verdict['resolved'])} resolved"]
    if verdict["failed"]:
        parts.append(f"{len(verdict['failed'])} failed")
    if verdict["unknown"]:
        parts.append(f"{len(verdict['unknown'])} unknown")
    return f"citations: {', '.join(parts)} — {_LIMITATION}"
