"""Deterministic facts over one saved branch, without interpreting response text."""

from collections import defaultdict
from copy import deepcopy

from .findings import annotate_findings

PROCESS_KEY = "deerflow_trajectory_process"


def process_evidence(value):
    """Accept only the collector's bounded, typed process observations."""
    if not isinstance(value, list):
        return []
    result = []
    for item in value[:128]:
        if not isinstance(item, dict) or not isinstance(item.get("source"), str):
            continue
        status = item.get("status")
        if status not in {"completed", "timeout", "interrupted", "unknown"}:
            continue
        code = item.get("exit_code")
        result.append(
            {
                "source": item["source"][:80],
                "status": status,
                "exit_code": code
                if status == "completed" and type(code) is int
                else None,
            }
        )
    return result


def analyze_rows(rows, *, thread_id=None, execution_id=None):
    """Analyze the loaded range only; ordering comes from the checkpoint parent chain.

    Stable row IDs remove paging overlaps, never content-equal executions. A call
    ID reused while still outstanding is ambiguous; no result is guessed to belong
    to one of those invocations. Updated messages are revisions, not extra calls.
    """
    output, seen = [], set()
    for row in rows:
        key = row.get("row_id")
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        output.append(deepcopy(row))
    turns = defaultdict(int)
    order = defaultdict(int)
    pending = defaultdict(list)
    invocations = {}
    repeats = defaultdict(list)
    results = {}
    for row in output:
        scope = (
            row.get("checkpoint_ns", ""),
            execution_id or (row.get("subagent_source") or {}).get("execution_id"),
        )
        independent = row.get("source") == "runtime_timing"
        if not independent:
            order[scope] += 1
        if row["kind"] == "user" and not row.get("updated"):
            turns[scope] += 1
        turn = turns[scope]
        evidence = {
            "thread_id": thread_id or row.get("thread_id"),
            "checkpoint_ns": scope[0],
            "execution_id": scope[1],
            "checkpoint_id": row.get("checkpoint_id"),
            "message_id": row.get("id"),
            "tool_call_id": row.get("tool_call_id"),
            "row_id": row.get("row_id"),
        }
        row["analysis"] = {
            "evidence": evidence,
            "saved_order": None if independent else order[scope],
            "order_basis": "operation_anchor"
            if independent
            else "checkpoint_parent_chain",
            "timestamp_basis": "checkpoint_saved_at"
            if row.get("source") != "runtime_timing"
            else "operation_ended_at",
            "result_links": [],
        }
        for call_index, call in enumerate(row.get("tool_calls", [])):
            call_id = call.get("id")
            key = (scope, turn, row.get("id"), call_id, call_index)
            fact = {
                "call_id": call_id,
                "call_row_id": row.get("row_id"),
                "tool_name": call.get("name"),
                "issuing_message_id": row.get("id"),
                "call_index": call_index,
                "result_row_ids": [],
                "association": "missing_result",
                "repeat_index": None,
                "repeat_count": None,
            }
            call["analysis"] = fact
            if not call_id or not row.get("id") or row.get("unidentified"):
                fact["association"] = "missing_identity"
                continue
            if key in invocations:
                call["analysis"] = invocations[key]
                continue
            invocations[key] = fact
            pending[(scope, turn, call_id)].append(fact)
            if call.get("args_fingerprint"):
                repeats[
                    (scope, turn, call.get("name"), call["args_fingerprint"])
                ].append(fact)
        if row["kind"] == "tool":
            result_key = (scope, turn, row.get("id"))
            if row.get("updated") and row.get("id") and result_key in results:
                original = results[result_key]
                row["analysis"].update(
                    {
                        key: original.get(key)
                        for key in ("association", "result_links", "tool_name")
                    }
                )
                continue
            candidates = pending[(scope, turn, row.get("tool_call_id"))]
            if len(candidates) == 1:
                call = candidates[0]
                call["result_row_ids"].append(row["row_id"])
                call["association"] = "matched"
                row["analysis"]["result_links"] = [call["call_row_id"]]
                row["analysis"]["association"] = "matched"
                row["analysis"]["tool_name"] = call["tool_name"]
                row["analysis"]["evidence"]["issuing_message_id"] = call[
                    "issuing_message_id"
                ]
                pending[(scope, turn, row.get("tool_call_id"))] = []
            else:
                row["analysis"]["association"] = (
                    "ambiguous" if candidates else "missing_call"
                )
                for call in candidates:
                    call["association"] = "ambiguous"
            if row.get("id"):
                results[result_key] = row["analysis"]
    for group in repeats.values():
        for index, fact in enumerate(group, 1):
            fact.update(repeat_index=index, repeat_count=len(group))
    return annotate_findings(output)
