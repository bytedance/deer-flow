"""Observed tool failures and bounded retry clues, separate from model prose."""

import shlex
from pathlib import PurePosixPath


NATIVE_FILE_TOOLS = {"read_file", "write_file", "str_replace", "glob", "grep", "ls"}


def operation_targets(name, args):
    """Extract literal absolute paths only, without resolving files or shell code."""
    if not isinstance(args, dict):
        return []
    candidates = []
    if name in NATIVE_FILE_TOOLS:
        path = args.get("path")
        if (
            name == "glob"
            and isinstance(path, str)
            and isinstance(args.get("pattern"), str)
        ):
            candidates.append(str(PurePosixPath(path) / args["pattern"]))
        else:
            candidates.append(path)
    elif name == "bash":
        command = args.get("command")
        if not isinstance(command, str) or len(command) > 16000:
            return []
        try:
            lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>")
            lexer.whitespace_split = True
            candidates.extend(list(lexer)[:256])
        except ValueError:
            return []
    return list(
        dict.fromkeys(
            str(PurePosixPath(path))
            for path in candidates
            if isinstance(path, str)
            and path.startswith("/")
            and len(path) <= 2048
            and not any(char in path for char in "*?[$`\\\n\r")
            and ".." not in PurePosixPath(path).parts
        )
    )[:8]


def tool_meta_evidence(value):
    if not isinstance(value, dict) or value.get("status") not in {
        "success",
        "error",
        "partial_success",
    }:
        return None
    return {
        key: value[key][:80]
        for key in ("status", "source", "error_type")
        if isinstance(value.get(key), str)
    }


def tool_failure(row):
    if row.get("kind") not in {"tool", "timing"}:
        return None
    timing = row.get("timing") or {}
    if row["kind"] == "timing" and timing.get("operation") != "tool":
        return None
    meta = row.get("tool_meta") or {}
    if row.get("tool_status") == "error" or meta.get("status") == "error":
        return {
            "confidence": "observed",
            "basis": "tool_status",
            "reason": "工具报告失败",
        }
    for process in row.get("process", []):
        if process.get("status") == "timeout":
            return {
                "confidence": "observed",
                "basis": "process_status",
                "reason": "进程超时",
            }
        code = process.get("exit_code")
        if type(code) is int and code != 0:
            return {
                "confidence": "observed",
                "basis": "process_exit_code",
                "reason": f"进程返回码 {code}",
            }
    if timing.get("operation") == "tool" and timing.get("outcome") in {
        "failed",
        "timeout",
    }:
        return {
            "confidence": "observed",
            "basis": "tool_timing",
            "reason": "工具超时" if timing["outcome"] == "timeout" else "工具执行失败",
        }
    # A successful read may contain an error document. Preserve explicit status;
    # untyped legacy envelopes are a clue, never an authoritative failure.
    if (
        (row.get("text") or "").startswith("Error:")
        and meta.get("status") == "success"
        and meta.get("source") != "content_analysis"
    ):
        return {
            "confidence": "inferred",
            "basis": "status_text_conflict",
            "reason": "工具标记成功，但输出以错误提示开头，需核对",
        }
    if (row.get("text") or "").startswith("Error:"):
        return {
            "confidence": "inferred",
            "basis": "legacy_error_text",
            "reason": "工具返回错误文本，旧记录状态待确认",
        }
    return None


def annotate_findings(rows):
    turns, pending_failures, target_failures, calls_by_row, issued, scope_by_row = (
        {},
        {},
        {},
        {},
        set(),
        {},
    )
    for row in rows:
        analysis = row["analysis"]
        evidence = analysis["evidence"]
        scope = (evidence["checkpoint_ns"], evidence["execution_id"])
        if row["kind"] == "user" and not row.get("updated"):
            turns[scope] = turns.get(scope, 0) + 1
        scope = (*scope, turns.get(scope, 0))
        scope_by_row[row["row_id"]] = scope
        failure = tool_failure(row)
        analysis["tool_failure"] = failure
        for call in row.get("tool_calls", []):
            fact = call["analysis"]
            fact.setdefault("retry", None)
            if id(fact) in issued or fact["association"] in {
                "ambiguous",
                "missing_identity",
            }:
                continue
            issued.add(id(fact))
            signature = (
                (call.get("name"), call.get("args_fingerprint"))
                if call.get("args_fingerprint")
                else None
            )
            targets = call.get("operation_targets") or []
            previous = pending_failures.get((scope, signature)) if signature else None
            if previous:
                fact["retry"] = {
                    "kind": "same_call_after_failure",
                    "confidence": previous["failure"]["confidence"],
                    "previous_call_row_id": previous["fact"]["call_row_id"],
                    "previous_result_row_id": previous["row_id"],
                    "reason": "失败后重复相同调用",
                }
            else:
                previous = next(
                    (
                        target_failures[(scope, target)]
                        for target in targets
                        if (scope, target) in target_failures
                    ),
                    None,
                )
                if previous:
                    fact["retry"] = {
                        "kind": "same_target_after_failure",
                        "confidence": "inferred",
                        "previous_call_row_id": previous["fact"]["call_row_id"],
                        "previous_result_row_id": previous["row_id"],
                        "reason": "失败后再次访问同一路径，可能重试",
                    }
            calls_by_row.setdefault(row["row_id"], []).append(
                (call, signature, targets, fact)
            )
        if row["kind"] != "tool" or analysis.get("association") != "matched":
            continue
        for call_row in analysis["result_links"]:
            for call, signature, targets, fact in calls_by_row.get(call_row, []):
                if (
                    call.get("id") != row.get("tool_call_id")
                    or scope_by_row.get(call_row) != scope
                ):
                    continue
                record = {
                    "fact": fact,
                    "failure": failure,
                    "row_id": row["row_id"],
                    "signature": signature,
                }
                if failure:
                    if signature:
                        pending_failures[(scope, signature)] = record
                    for target in targets:
                        target_failures[(scope, target)] = record
                else:
                    if signature:
                        pending_failures.pop((scope, signature), None)
                    for target in targets:
                        if (
                            (old := target_failures.get((scope, target)))
                            and signature
                            and old["signature"] == signature
                        ):
                            target_failures.pop((scope, target))
    return rows
