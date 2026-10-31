"""Deterministic evidence for lead-agent final-answer action claims."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, TypedDict

from langchain_core.messages import AIMessage, ToolMessage

from deerflow.agents.middlewares.tool_receipt import TOOL_RECEIPT_KEY, is_valid_receipt
from deerflow.runtime.context_keys import CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY

SCHEMA = "deerflow.final_answer_evidence.v1"
_KNOWN_RECEIPT_STATUSES = frozenset({"success", "error", "partial_success"})

ACTION_CATEGORY_TOOLS: dict[str, frozenset[str]] = {
    "artifact_delivery": frozenset({"present_files"}),
    "command_execution": frozenset({"bash"}),
    "delegation": frozenset({"task", "batch_task"}),
    "file_write": frozenset({"write_file", "str_replace"}),
    "retrieval": frozenset({"web_search", "web_fetch", "knowledge_search", "knowledge_entries_search", "entity_relations_search"}),
}

# Deliberately narrow: these patterns identify explicit completion claims, not
# general prose. The output is advisory execution evidence, never a truth verdict.
_ACTION_PATTERNS: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = (
    (
        "file_write",
        (
            re.compile(r"\b(?:wrote|written|created|saved|modified|updated|patched|fixed|added|removed|renamed|moved)\b", re.IGNORECASE),
            re.compile(r"已(?:写入|创建|保存|修改|更新|修复|添加|删除|重命名|移动)|写入了|创建了|保存了|修复了"),
        ),
    ),
    (
        "command_execution",
        (
            re.compile(r"\b(?:ran|executed|tested|built|compiled|installed|deployed|verified)\b", re.IGNORECASE),
            re.compile(r"运行了|执行了|测试了|构建了|编译了|安装了|部署了|验证了"),
        ),
    ),
    (
        "retrieval",
        (
            re.compile(r"\b(?:searched|fetched|retrieved|crawled)\b", re.IGNORECASE),
            re.compile(r"搜索了|检索了|抓取了|获取了"),
        ),
    ),
    (
        "artifact_delivery",
        (
            re.compile(r"\b(?:generated|exported|presented|delivered)\b", re.IGNORECASE),
            re.compile(r"生成了|导出了|交付了|展示了"),
        ),
    ),
    (
        "delegation",
        (
            re.compile(r"\b(?:delegated|dispatched)\b", re.IGNORECASE),
            re.compile(r"委派了|派发了"),
        ),
    ),
)


class FinalAnswerEvidence(TypedDict):
    """Content-free execution evidence for one final answer."""

    schema: str
    status: str
    final_message_id: str | None
    final_content_sha256: str
    claimed_action_categories: list[str]
    unmatched_action_categories: list[str]
    lead_receipts: dict[str, Any]
    coverage: str


def _content_text(message: AIMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, Mapping) and block.get("type") in ("text", "output_text") and isinstance(block.get("text"), str):
            parts.append(block["text"])
    return "\n".join(parts)


def claimed_action_categories(message: AIMessage) -> list[str]:
    """Return only explicit, supported action-claim categories."""
    text = _content_text(message)
    return [category for category, patterns in _ACTION_PATTERNS if any(pattern.search(text) for pattern in patterns)]


def _current_run_messages(messages: Sequence[Any], context: Mapping[str, Any]) -> tuple[list[Any], bool]:
    """Apply the worker-owned run boundary, not a guess based on user turns."""
    if CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY not in context:
        return list(messages), False
    previous = context[CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY]
    if not isinstance(previous, (set, frozenset)) or any(not isinstance(value, str) for value in previous):
        return list(messages), False
    if not previous:
        return list(messages), True
    for index in range(len(messages) - 1, -1, -1):
        if getattr(messages[index], "id", None) in previous:
            return list(messages[index + 1 :]), True
    return list(messages), False


def _lead_receipts(messages: Iterable[Any]) -> dict[str, Any]:
    by_category: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    count = 0
    for message in messages:
        # A subagent result is itself a delegated call. Its nested receipts are
        # intentionally excluded: they are child evidence, not lead evidence.
        if not isinstance(message, ToolMessage):
            continue
        receipt = (message.additional_kwargs or {}).get(TOOL_RECEIPT_KEY)
        if not is_valid_receipt(receipt):
            continue
        count += 1
        tool_name = receipt["tool_name"]
        category = next((name for name, tools in ACTION_CATEGORY_TOOLS.items() if tool_name in tools), "other")
        by_category[category] = by_category.get(category, 0) + 1
        status = receipt["status"]
        safe_status = status if status in _KNOWN_RECEIPT_STATUSES else "unknown"
        status_counts[safe_status] = status_counts.get(safe_status, 0) + 1
    return {
        "count": count,
        "by_category": dict(sorted(by_category.items())),
        "status_counts": dict(sorted(status_counts.items())),
    }


def build_final_answer_evidence(final_message: AIMessage, messages: Sequence[Any], *, context: Mapping[str, Any] | None = None) -> FinalAnswerEvidence:
    """Build bounded evidence; never copy answer, arguments, paths, or outputs."""
    current, boundary_known = _current_run_messages(messages, context or {})
    claims = claimed_action_categories(final_message)
    receipts = _lead_receipts(current)
    successful_tools = {
        (message.additional_kwargs or {}).get(TOOL_RECEIPT_KEY, {}).get("tool_name")
        for message in current
        if isinstance(message, ToolMessage) and is_valid_receipt((message.additional_kwargs or {}).get(TOOL_RECEIPT_KEY)) and (message.additional_kwargs or {}).get(TOOL_RECEIPT_KEY, {}).get("status") == "success"
    }
    unmatched = [category for category in claims if not (ACTION_CATEGORY_TOOLS[category] & successful_tools)]
    if not boundary_known:
        status = "insufficient_coverage"
    elif not claims:
        status = "no_action_claims"
    elif unmatched:
        status = "claims_without_matching_receipts"
    else:
        status = "matching_receipts_observed"
    # A missing user boundary means the receipt scan may include prior turns.
    # No receipt is still conclusive only when a boundary is known and the
    # final answer makes no action claim.
    coverage = "current_run_visible" if boundary_known else "unknown"
    return {
        "schema": SCHEMA,
        "status": status,
        "final_message_id": final_message.id if isinstance(final_message.id, str) else None,
        "final_content_sha256": hashlib.sha256(_content_text(final_message).encode("utf-8")).hexdigest(),
        "claimed_action_categories": claims,
        "unmatched_action_categories": unmatched,
        "lead_receipts": receipts,
        "coverage": coverage,
    }


def event_changes(evidence: FinalAnswerEvidence) -> dict[str, Any]:
    """Return a plain dict for the run-event store boundary."""
    return dict(evidence)
