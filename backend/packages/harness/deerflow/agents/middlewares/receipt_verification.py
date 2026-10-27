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

import re
from typing import TypedDict

from deerflow.agents.middlewares.tool_receipt import ToolReceipt, parse_citations

VERDICT_SOURCE = "receipt_citations"
VERDICT_REQUIREMENT = "cited_ids_in_execution_record"

#: Zero-citation heuristic: a completed report making action claims with no
#: receipt citations is a weak-negative signal, not a clean bill. Verb list
#: plus path-with-extension patterns; false positives cost one UNVERIFIED
#: line, false negatives let false success through — biased toward sensitive.
_ACTION_VERB_RE = re.compile(
    r"\b(wrote|written|created|saved|generated|ran|executed|uploaded|downloaded"
    r"|deleted|modified|updated|installed|deployed|fetched|built|compiled"
    r"|produced|exported|fixed|added|changed|removed|implemented|patched"
    r"|refactored|renamed|moved|merged|committed|edited|replaced|tested"
    r"|verified|cleaned|configured)\b",
    re.IGNORECASE,
)
#: CJK reports have no word boundaries, so the English list never fires on
#: them; match common action verbs directly instead.
_CJK_ACTION_VERB_RE = re.compile(
    r"创建|生成|写入|保存|修改|更新|删除|运行|执行|安装|部署|上传|下载"
    r"|修复|添加|新增|编写|编译|构建|导出|测试|提交|移动|重命名|配置|替换|清理"
)
_FILE_PATH_RE = re.compile(r"(?:/[\w.\-]+){2,}|\b[\w.\-]+\.(?:py|md|txt|json|ya?ml|csv|html|js|ts|sh|log|pdf|png|jpe?g)\b")

#: Safety net beyond any verb list: a harvested non-empty receipt ledger means
#: the subagent demonstrably executed tools, so a paragraph-length report that
#: cites none of them is UNVERIFIED regardless of language or phrasing. Short
#: status confirmations stay a vacuous pass.
_NONTRIVIAL_REPORT_MIN_CHARS = 240

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


def _has_action_claims(report_text: str) -> bool:
    return bool(_ACTION_VERB_RE.search(report_text) or _CJK_ACTION_VERB_RE.search(report_text) or _FILE_PATH_RE.search(report_text))


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
    no_citation_claims = not cited and (_has_action_claims(report_text) or bool(receipts) and len(report_text.strip()) >= _NONTRIVIAL_REPORT_MIN_CHARS)
    if cited:
        citation_resolved = not failed and not unknown
    else:
        # Claim-free report with nothing to check: vacuous pass, renders nothing.
        citation_resolved = not no_citation_claims
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
    if verdict["no_citation_claims"]:
        return "citations: UNVERIFIED — action claims without receipt citations"
    if not verdict["cited"]:
        return ""
    parts = [f"{len(verdict['resolved'])} resolved"]
    if verdict["failed"]:
        parts.append(f"{len(verdict['failed'])} failed")
    if verdict["unknown"]:
        parts.append(f"{len(verdict['unknown'])} unknown")
    return f"citations: {', '.join(parts)} — {_LIMITATION}"
