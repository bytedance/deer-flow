"""Pre-import validator for raw accept/reject benchmark datasets."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

Severity = Literal["error", "warning"]

_FIELD_REPAIR_GUIDANCE: dict[str, list[str]] = {
    "decision": [
        "将 `decision` 统一映射到 accepted/rejected/revise（可接受别名：accept/reject/revision）。",
        "若原始字段名不同（如 `outcome`/`review_decision`），先在预处理阶段重命名为 `decision`。",
    ],
    "venue": [
        "补齐 `venue`（或使用 `journal`/`conference` 别名），确保每条记录都有投稿目标场景。",
    ],
    "claims": [
        "将 `claims` 统一为数组结构；单条对象改成 `[obj]`。",
        "每条 claim 建议至少包含 `type`、`has_evidence`、`has_citation`。",
    ],
    "generated_citations": [
        "统一为 `generated_citations: string[]`，不要混用非数组或嵌套对象。",
    ],
    "verified_citations": [
        "补齐 `verified_citations`（可从 `ground_truth_citations` 映射），用于 citation fidelity 评估。",
    ],
    "abstract_numbers": [
        "补齐 `abstract_numbers`，或提供 `abstract_text` 让系统自动抽取数字。",
    ],
    "body_numbers": [
        "补齐 `body_numbers`，或提供 `body_text` 让系统自动抽取数字。",
    ],
    "rebuttal_addressed_ids": [
        "补齐 `rebuttal_addressed_ids`，保证 reviewer comment 和 rebuttal 可对齐。",
        "把 `reviewer_comments` 统一映射到 `reviewer_comment_ids`（例如 `[{\"id\":\"R1\"}] -> [\"R1\"]`）。",
    ],
    "cross_modal_items_expected": [
        "确保 `cross_modal_items_expected` 是非负整数。",
    ],
    "cross_modal_items_used": [
        "确保 `cross_modal_items_used` 是非负整数，且通常不大于 expected。",
    ],
    "revision_terms": [
        "建议至少提供 2 轮 `revision_terms` 快照，增强 long-horizon consistency 信号。",
    ],
    "revision_numbers": [
        "建议至少提供 2 轮 `revision_numbers` 快照，增强 long-horizon consistency 信号。",
    ],
    "claims.text": [
        "文本中若包含邮箱/URL/DOI/ORCID，建议开启 anonymize 或先脱敏。",
    ],
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalize_decision(value: Any) -> str:
    if not isinstance(value, str):
        return "unknown"
    lowered = value.strip().lower()
    if lowered in {"accept", "accepted", "minor accept"}:
        return "accepted"
    if lowered in {"reject", "rejected", "desk reject", "major reject"}:
        return "rejected"
    if lowered in {"revise", "revision", "major revision", "minor revision", "r&r"}:
        return "revise"
    return "unknown"


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
    return out


def _as_float_list(value: Any) -> list[float]:
    if isinstance(value, list):
        out: list[float] = []
        for item in value:
            try:
                out.append(float(item))
            except Exception:
                continue
        return out
    if isinstance(value, str):
        found = re.findall(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", value)
        out: list[float] = []
        for token in found:
            try:
                out.append(float(token))
            except Exception:
                continue
        return out
    return []


def _normalize_reviewer_ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    ids: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            ids.append(item.strip())
        elif isinstance(item, dict):
            candidate = item.get("id") or item.get("comment_id") or item.get("reviewer_id")
            if isinstance(candidate, str) and candidate.strip():
                ids.append(candidate.strip())
    return ids


def _extract_raw_records(payload: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    metadata: dict[str, Any] = {}
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)], metadata
    if isinstance(payload, dict):
        if isinstance(payload.get("metadata"), dict):
            metadata = payload["metadata"]
        for key in ("records", "cases", "items", "submissions"):
            raw = payload.get(key)
            if isinstance(raw, list):
                return [item for item in raw if isinstance(item, dict)], metadata
    raise ValueError(
        "Raw dataset must be a JSON array or object containing "
        "`records`/`cases`/`items`/`submissions` list"
    )


def _record_id(record: dict[str, Any], index: int) -> str:
    for key in ("case_id", "manuscript_id", "submission_id"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return f"record-{index:04d}"


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _contains_sensitive_patterns(text: str) -> bool:
    patterns = (
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
        r"https?://\S+",
        r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\b",
        r"\b(?:orcid\.org/)?\d{4}-\d{4}-\d{4}-\d{3}[\dX]\b",
    )
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _add_issue(
    issues: list[dict[str, Any]],
    *,
    severity: Severity,
    record_index: int,
    record_id: str,
    field: str,
    message: str,
) -> None:
    issues.append(
        {
            "severity": severity,
            "record_index": record_index,
            "record_id": record_id,
            "field": field,
            "message": message,
        }
    )


def _build_repair_suggestions(
    field_issue_counts: dict[str, dict[str, int]],
) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    for field, counts in sorted(field_issue_counts.items(), key=lambda x: x[0]):
        actions = _FIELD_REPAIR_GUIDANCE.get(field, [])
        if not actions:
            actions = [
                "检查该字段的数据类型与取值范围，并在预处理阶段统一映射到标准 schema。",
            ]
        suggestions.append(
            {
                "field": field,
                "issue_count": int(counts.get("total", 0)),
                "error_count": int(counts.get("error", 0)),
                "warning_count": int(counts.get("warning", 0)),
                "actions": actions,
            }
        )
    return suggestions


def _validate_payload(
    payload: Any,
    *,
    source_path_label: str,
    source_fingerprint: str,
) -> dict[str, Any]:
    records, metadata = _extract_raw_records(payload)

    issues: list[dict[str, Any]] = []
    for idx, record in enumerate(records, start=1):
        rid = _record_id(record, idx)
        decision_raw = (
            record.get("decision")
            or record.get("outcome")
            or record.get("review_decision")
        )
        decision = _normalize_decision(decision_raw)
        if decision == "unknown":
            _add_issue(
                issues,
                severity="error",
                record_index=idx,
                record_id=rid,
                field="decision",
                message=f"Unsupported or missing decision: {decision_raw!r}",
            )

        venue = (
            record.get("venue")
            or record.get("journal")
            or record.get("conference")
            or metadata.get("venue")
        )
        if not isinstance(venue, str) or not venue.strip():
            _add_issue(
                issues,
                severity="error",
                record_index=idx,
                record_id=rid,
                field="venue",
                message="Missing venue/journal/conference field.",
            )

        claims = record.get("claims") or record.get("claim_annotations")
        if claims is None:
            _add_issue(
                issues,
                severity="warning",
                record_index=idx,
                record_id=rid,
                field="claims",
                message="No claims/claim_annotations provided.",
            )
        elif not isinstance(claims, list):
            _add_issue(
                issues,
                severity="error",
                record_index=idx,
                record_id=rid,
                field="claims",
                message="claims must be an array if provided.",
            )
        elif len(claims) == 0:
            _add_issue(
                issues,
                severity="warning",
                record_index=idx,
                record_id=rid,
                field="claims",
                message="claims is empty.",
            )

        generated_citations = _as_str_list(
            record.get("generated_citations") or record.get("output_citations")
        )
        verified_citations = _as_str_list(
            record.get("verified_citations") or record.get("ground_truth_citations")
        )
        if generated_citations and not verified_citations:
            _add_issue(
                issues,
                severity="warning",
                record_index=idx,
                record_id=rid,
                field="verified_citations",
                message="generated_citations present but verified_citations missing/empty.",
            )
        if not generated_citations and verified_citations:
            _add_issue(
                issues,
                severity="warning",
                record_index=idx,
                record_id=rid,
                field="generated_citations",
                message="verified_citations present but generated_citations missing/empty.",
            )

        abstract_numbers = _as_float_list(
            record.get("abstract_numbers") or record.get("abstract_text") or ""
        )
        body_numbers = _as_float_list(
            record.get("body_numbers") or record.get("body_text") or ""
        )
        if not abstract_numbers:
            _add_issue(
                issues,
                severity="warning",
                record_index=idx,
                record_id=rid,
                field="abstract_numbers",
                message="No numeric facts extracted from abstract_numbers/abstract_text.",
            )
        if not body_numbers:
            _add_issue(
                issues,
                severity="warning",
                record_index=idx,
                record_id=rid,
                field="body_numbers",
                message="No numeric facts extracted from body_numbers/body_text.",
            )

        reviewer_ids = _normalize_reviewer_ids(
            record.get("reviewer_comment_ids")
            or record.get("reviewer_comments")
            or record.get("review_comments")
            or []
        )
        addressed_ids = _normalize_reviewer_ids(
            record.get("rebuttal_addressed_ids")
            or record.get("addressed_comment_ids")
            or []
        )
        if reviewer_ids and not addressed_ids:
            _add_issue(
                issues,
                severity="warning",
                record_index=idx,
                record_id=rid,
                field="rebuttal_addressed_ids",
                message="Reviewer comments exist but rebuttal addressed IDs are empty.",
            )

        expected = _to_int(
            record.get("cross_modal_items_expected")
            or record.get("cross_modal_expected")
        )
        used = _to_int(
            record.get("cross_modal_items_used") or record.get("cross_modal_used")
        )
        if used is not None and used < 0:
            _add_issue(
                issues,
                severity="error",
                record_index=idx,
                record_id=rid,
                field="cross_modal_items_used",
                message="cross_modal_items_used cannot be negative.",
            )
        if expected is not None and expected < 0:
            _add_issue(
                issues,
                severity="error",
                record_index=idx,
                record_id=rid,
                field="cross_modal_items_expected",
                message="cross_modal_items_expected cannot be negative.",
            )
        if (
            expected is not None
            and used is not None
            and expected > 0
            and used > expected
        ):
            _add_issue(
                issues,
                severity="warning",
                record_index=idx,
                record_id=rid,
                field="cross_modal_items_used",
                message=f"cross_modal_items_used ({used}) exceeds expected ({expected}).",
            )

        revision_terms = record.get("revision_terms")
        revision_numbers = record.get("revision_numbers")
        if isinstance(revision_terms, list) and len(revision_terms) < 2:
            _add_issue(
                issues,
                severity="warning",
                record_index=idx,
                record_id=rid,
                field="revision_terms",
                message="Less than 2 revision_terms snapshots; weak long-horizon signal.",
            )
        if isinstance(revision_numbers, list) and len(revision_numbers) < 2:
            _add_issue(
                issues,
                severity="warning",
                record_index=idx,
                record_id=rid,
                field="revision_numbers",
                message="Less than 2 revision_numbers snapshots; weak long-horizon signal.",
            )

        candidate_texts: list[str] = []
        if isinstance(claims, list):
            for claim in claims:
                if isinstance(claim, dict) and isinstance(claim.get("text"), str):
                    candidate_texts.append(claim["text"])
                elif isinstance(claim, str):
                    candidate_texts.append(claim)
        for text in candidate_texts:
            if _contains_sensitive_patterns(text):
                _add_issue(
                    issues,
                    severity="warning",
                    record_index=idx,
                    record_id=rid,
                    field="claims.text",
                    message="Potential sensitive tokens detected (email/url/doi/orcid); anonymization strongly recommended.",
                )
                break

    error_count = len([item for item in issues if item["severity"] == "error"])
    warning_count = len([item for item in issues if item["severity"] == "warning"])
    status = "pass"
    if error_count > 0:
        status = "has_errors"
    elif warning_count > 0:
        status = "has_warnings"

    by_field: dict[str, dict[str, int]] = {}
    for item in issues:
        field = item["field"]
        severity = item["severity"]
        if field not in by_field:
            by_field[field] = {"error": 0, "warning": 0, "total": 0}
        by_field[field][severity] += 1
        by_field[field]["total"] += 1

    repair_suggestions = _build_repair_suggestions(by_field)

    return {
        "validated_at": _now_iso(),
        "source_path": source_path_label,
        "source_fingerprint": source_fingerprint,
        "source_record_count": len(records),
        "error_count": error_count,
        "warning_count": warning_count,
        "status": status,
        "issues": issues,
        "field_issue_counts": by_field,
        "repair_suggestions": repair_suggestions,
    }


def validate_accept_reject_dataset(source_path: Path) -> dict[str, Any]:
    """Validate raw accept/reject dataset loaded from file."""
    raw_text = source_path.read_text(encoding="utf-8")
    payload = json.loads(raw_text)
    return _validate_payload(
        payload,
        source_path_label=str(source_path),
        source_fingerprint=_sha256_text(raw_text),
    )


def validate_accept_reject_payload(
    raw_payload: Any,
    *,
    source_path_label: str = "<in-memory>",
    source_fingerprint: str | None = None,
) -> dict[str, Any]:
    """Validate raw accept/reject payload already loaded in memory."""
    if source_fingerprint is None:
        source_fingerprint = _sha256_text(
            json.dumps(raw_payload, ensure_ascii=False, sort_keys=True)
        )
    return _validate_payload(
        raw_payload,
        source_path_label=source_path_label,
        source_fingerprint=source_fingerprint,
    )


def render_validation_report_markdown(report: dict[str, Any]) -> str:
    """Render validation result as readable markdown."""
    lines: list[str] = []
    lines.append("# Raw Dataset Validation Report")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Status: `{report.get('status', 'unknown')}`")
    lines.append(f"- Source: `{report.get('source_path', '')}`")
    lines.append(f"- Records: `{report.get('source_record_count', 0)}`")
    lines.append(f"- Errors: `{report.get('error_count', 0)}`")
    lines.append(f"- Warnings: `{report.get('warning_count', 0)}`")
    lines.append("")
    lines.append("## Field Issue Counts")
    lines.append("")
    lines.append("| Field | Errors | Warnings | Total |")
    lines.append("| --- | ---: | ---: | ---: |")
    field_issue_counts = report.get("field_issue_counts", {})
    if isinstance(field_issue_counts, dict) and field_issue_counts:
        for field, counts in sorted(field_issue_counts.items(), key=lambda x: x[0]):
            if not isinstance(counts, dict):
                continue
            lines.append(
                f"| `{field}` | {int(counts.get('error', 0))} | "
                f"{int(counts.get('warning', 0))} | {int(counts.get('total', 0))} |"
            )
    else:
        lines.append("| _none_ | 0 | 0 | 0 |")
    lines.append("")
    lines.append("## Repair Suggestions")
    lines.append("")
    repair_suggestions = report.get("repair_suggestions", [])
    if isinstance(repair_suggestions, list) and repair_suggestions:
        for item in repair_suggestions:
            if not isinstance(item, dict):
                continue
            field = item.get("field", "unknown")
            issue_count = int(item.get("issue_count", 0))
            error_count = int(item.get("error_count", 0))
            warning_count = int(item.get("warning_count", 0))
            lines.append(
                f"- `{field}` (issues={issue_count}, "
                f"errors={error_count}, warnings={warning_count})"
            )
            actions = item.get("actions", [])
            if isinstance(actions, list) and actions:
                for action in actions:
                    if isinstance(action, str) and action.strip():
                        lines.append(f"  - {action}")
    else:
        lines.append("No repair suggestions needed.")
    lines.append("")
    lines.append("## Issues")
    lines.append("")
    issues = report.get("issues", [])
    if not isinstance(issues, list) or not issues:
        lines.append("No issues found.")
        lines.append("")
        return "\n".join(lines)

    for item in issues:
        if not isinstance(item, dict):
            continue
        severity = item.get("severity", "warning")
        record_index = item.get("record_index", "?")
        record_id = item.get("record_id", "?")
        field = item.get("field", "unknown")
        message = item.get("message", "")
        lines.append(
            f"- **[{severity}]** record#{record_index} `{record_id}` "
            f"`{field}`: {message}"
        )
    lines.append("")
    return "\n".join(lines)

