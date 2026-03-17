"""Low-risk auto-fix preprocessor for raw accept/reject datasets."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

AutoFixLevel = Literal["safe", "balanced", "aggressive"]

_LEVEL_ORDER: dict[AutoFixLevel, int] = {
    "safe": 0,
    "balanced": 1,
    "aggressive": 2,
}


def _extract_raw_records_with_key(
    payload: Any,
) -> tuple[list[dict[str, Any]], dict[str, Any], str | None]:
    metadata: dict[str, Any] = {}
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)], metadata, None
    if isinstance(payload, dict):
        if isinstance(payload.get("metadata"), dict):
            metadata = payload["metadata"]
        for key in ("records", "cases", "items", "submissions"):
            raw = payload.get(key)
            if isinstance(raw, list):
                return [item for item in raw if isinstance(item, dict)], metadata, key
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


def _is_at_least(level: AutoFixLevel, threshold: AutoFixLevel) -> bool:
    return _LEVEL_ORDER[level] >= _LEVEL_ORDER[threshold]


def _split_scalar_tokens(value: str) -> list[str]:
    parts = re.split(r"[,\n;|]+", value)
    return [item.strip() for item in parts if item.strip()]


def _as_str_list_or_scalar(value: Any, *, split_scalar: bool = False) -> list[str]:
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        if split_scalar:
            return _split_scalar_tokens(stripped)
        return [stripped]
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
        return out
    return []


def _extract_reviewer_ids(value: Any, *, split_scalar: bool = False) -> list[str]:
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        if split_scalar:
            return _split_scalar_tokens(stripped)
        return [stripped]
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


def _unique(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in values:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _non_empty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return len(value) > 0
    return True


def _action(actions: list[dict[str, str]], key: str, detail: str) -> None:
    actions.append({"key": key, "detail": detail})


def _rename_if_missing(
    record: dict[str, Any],
    actions: list[dict[str, str]],
    *,
    target: str,
    aliases: tuple[str, ...],
) -> None:
    if _non_empty(record.get(target)):
        return
    for alias in aliases:
        if _non_empty(record.get(alias)):
            record[target] = record.get(alias)
            _action(actions, f"rename:{alias}->{target}", f"{alias} -> {target}")
            return


def preprocess_accept_reject_payload(
    raw_payload: Any,
    *,
    apply_autofix: bool = True,
    autofix_level: AutoFixLevel = "balanced",
) -> dict[str, Any]:
    """Apply low-risk canonicalization before import."""
    if autofix_level not in _LEVEL_ORDER:
        raise ValueError(f"Unsupported autofix_level: {autofix_level}")
    records, metadata, container_key = _extract_raw_records_with_key(raw_payload)
    fixed_records: list[dict[str, Any]] = []
    fix_counts: dict[str, int] = {}
    fix_logs: list[dict[str, Any]] = []

    for idx, original in enumerate(records, start=1):
        record = dict(original)
        actions: list[dict[str, str]] = []

        if apply_autofix:
            split_scalars = _is_at_least(autofix_level, "aggressive")
            _rename_if_missing(record, actions, target="decision", aliases=("outcome", "review_decision"))
            _rename_if_missing(record, actions, target="venue", aliases=("journal", "conference"))
            _rename_if_missing(record, actions, target="claims", aliases=("claim_annotations",))
            _rename_if_missing(record, actions, target="cross_modal_items_expected", aliases=("cross_modal_expected",))
            _rename_if_missing(record, actions, target="cross_modal_items_used", aliases=("cross_modal_used",))
            _rename_if_missing(record, actions, target="rebuttal_addressed_ids", aliases=("addressed_comment_ids",))

            generated = _unique(
                _as_str_list_or_scalar(record.get("generated_citations"), split_scalar=split_scalars)
                + _as_str_list_or_scalar(record.get("output_citations"), split_scalar=split_scalars)
            )
            if generated and generated != _as_str_list_or_scalar(
                record.get("generated_citations"),
                split_scalar=split_scalars,
            ):
                record["generated_citations"] = generated
                _action(
                    actions,
                    "merge:output_citations->generated_citations",
                    "Merged output_citations into generated_citations",
                )
            if "output_citations" in record:
                record.pop("output_citations", None)

            verified = _unique(
                _as_str_list_or_scalar(record.get("verified_citations"), split_scalar=split_scalars)
                + _as_str_list_or_scalar(record.get("ground_truth_citations"), split_scalar=split_scalars)
            )
            if verified and verified != _as_str_list_or_scalar(
                record.get("verified_citations"),
                split_scalar=split_scalars,
            ):
                record["verified_citations"] = verified
                _action(
                    actions,
                    "merge:ground_truth_citations->verified_citations",
                    "Merged ground_truth_citations into verified_citations",
                )
            if "ground_truth_citations" in record:
                record.pop("ground_truth_citations", None)

            reviewer_ids = _unique(
                _extract_reviewer_ids(record.get("reviewer_comment_ids"), split_scalar=split_scalars)
                + _extract_reviewer_ids(record.get("reviewer_comments"), split_scalar=split_scalars)
                + _extract_reviewer_ids(record.get("review_comments"), split_scalar=split_scalars)
            )
            if reviewer_ids and reviewer_ids != _extract_reviewer_ids(
                record.get("reviewer_comment_ids"),
                split_scalar=split_scalars,
            ):
                record["reviewer_comment_ids"] = reviewer_ids
                _action(
                    actions,
                    "merge:reviewer_comments->reviewer_comment_ids",
                    "Mapped reviewer_comments/review_comments into reviewer_comment_ids",
                )
            if "reviewer_comments" in record:
                record.pop("reviewer_comments", None)
            if "review_comments" in record:
                record.pop("review_comments", None)

            rebuttal_ids = _unique(
                _extract_reviewer_ids(record.get("rebuttal_addressed_ids"), split_scalar=split_scalars)
                + _extract_reviewer_ids(record.get("addressed_comment_ids"), split_scalar=split_scalars)
            )
            if rebuttal_ids and rebuttal_ids != _extract_reviewer_ids(
                record.get("rebuttal_addressed_ids"),
                split_scalar=split_scalars,
            ):
                record["rebuttal_addressed_ids"] = rebuttal_ids
                _action(
                    actions,
                    "merge:addressed_comment_ids->rebuttal_addressed_ids",
                    "Mapped addressed_comment_ids into rebuttal_addressed_ids",
                )
            if "addressed_comment_ids" in record:
                record.pop("addressed_comment_ids", None)

            checklist = _unique(
                _as_str_list_or_scalar(record.get("venue_checklist_items"), split_scalar=split_scalars)
                + _as_str_list_or_scalar(record.get("acceptance_checklist"), split_scalar=split_scalars)
            )
            if checklist and checklist != _as_str_list_or_scalar(
                record.get("venue_checklist_items"),
                split_scalar=split_scalars,
            ):
                record["venue_checklist_items"] = checklist
                _action(
                    actions,
                    "merge:acceptance_checklist->venue_checklist_items",
                    "Mapped acceptance_checklist into venue_checklist_items",
                )
            if "acceptance_checklist" in record:
                record.pop("acceptance_checklist", None)

            satisfied = _unique(
                _as_str_list_or_scalar(record.get("venue_satisfied_items"), split_scalar=split_scalars)
                + _as_str_list_or_scalar(record.get("satisfied_checklist"), split_scalar=split_scalars)
            )
            if satisfied and satisfied != _as_str_list_or_scalar(
                record.get("venue_satisfied_items"),
                split_scalar=split_scalars,
            ):
                record["venue_satisfied_items"] = satisfied
                _action(
                    actions,
                    "merge:satisfied_checklist->venue_satisfied_items",
                    "Mapped satisfied_checklist into venue_satisfied_items",
                )
            if "satisfied_checklist" in record:
                record.pop("satisfied_checklist", None)

            claims = record.get("claims")
            if _is_at_least(autofix_level, "balanced"):
                if isinstance(claims, dict):
                    record["claims"] = [claims]
                    _action(actions, "wrap:claims", "Wrapped object claims into array")

                for field in (
                    "generated_citations",
                    "verified_citations",
                    "rebuttal_addressed_ids",
                    "venue_checklist_items",
                    "venue_satisfied_items",
                ):
                    value = record.get(field)
                    if isinstance(value, str) and value.strip():
                        if split_scalars:
                            tokens = _split_scalar_tokens(value)
                            if tokens:
                                record[field] = tokens
                                _action(
                                    actions,
                                    f"split:{field}",
                                    f"Split scalar {field} by delimiters into array",
                                )
                        else:
                            record[field] = [value.strip()]
                            _action(
                                actions,
                                f"wrap:{field}",
                                f"Wrapped scalar {field} into array",
                            )

                revision_terms = record.get("revision_terms")
                if isinstance(revision_terms, list) and revision_terms:
                    first = revision_terms[0]
                    if not isinstance(first, list):
                        wrapped = [
                            [str(item).strip() for item in revision_terms if str(item).strip()]
                        ]
                        record["revision_terms"] = wrapped
                        _action(
                            actions,
                            "wrap:revision_terms",
                            "Wrapped flat revision_terms into 2D array",
                        )

                revision_numbers = record.get("revision_numbers")
                if isinstance(revision_numbers, list) and revision_numbers:
                    first = revision_numbers[0]
                    if not isinstance(first, list):
                        normalized_row: list[float] = []
                        for item in revision_numbers:
                            try:
                                normalized_row.append(float(item))
                            except Exception:
                                continue
                        record["revision_numbers"] = [normalized_row]
                        _action(
                            actions,
                            "wrap:revision_numbers",
                            "Wrapped flat revision_numbers into 2D array",
                        )

            if _is_at_least(autofix_level, "aggressive"):
                claims = record.get("claims")
                if isinstance(claims, str) and claims.strip():
                    segments = _split_scalar_tokens(claims)
                    if not segments:
                        segments = [claims.strip()]
                    record["claims"] = [
                        {
                            "type": "weak",
                            "has_evidence": False,
                            "has_citation": False,
                            "text": segment,
                        }
                        for segment in segments
                    ]
                    _action(
                        actions,
                        "split:claims",
                        "Split scalar claims into weak-claim array",
                    )

        fixed_records.append(record)
        if actions:
            for action in actions:
                key = action["key"]
                fix_counts[key] = fix_counts.get(key, 0) + 1
            fix_logs.append(
                {
                    "record_index": idx,
                    "record_id": _record_id(record, idx),
                    "actions": actions,
                }
            )

    if isinstance(raw_payload, dict):
        fixed_payload = dict(raw_payload)
        target_key = container_key or "records"
        fixed_payload[target_key] = fixed_records
        if "metadata" not in fixed_payload and metadata:
            fixed_payload["metadata"] = metadata
    else:
        fixed_payload = fixed_records

    report = {
        "applied": apply_autofix,
        "autofix_level": autofix_level,
        "source_record_count": len(records),
        "modified_record_count": len(fix_logs),
        "fix_counts": dict(sorted(fix_counts.items(), key=lambda x: x[0])),
        "fix_logs": fix_logs,
    }
    return {
        "fixed_payload": fixed_payload,
        "report": report,
    }


def preprocess_accept_reject_dataset(
    source_path: Path,
    *,
    apply_autofix: bool = True,
    autofix_level: AutoFixLevel = "balanced",
) -> dict[str, Any]:
    """Load JSON from file and run payload preprocessor."""
    raw_payload = json.loads(source_path.read_text(encoding="utf-8"))
    result = preprocess_accept_reject_payload(
        raw_payload,
        apply_autofix=apply_autofix,
        autofix_level=autofix_level,
    )
    result["source_path"] = str(source_path)
    return result


def render_autofix_report_markdown(report: dict[str, Any]) -> str:
    """Render auto-fix report as readable markdown."""
    lines: list[str] = []
    lines.append("# Raw Dataset Auto-Fix Report")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Applied: `{bool(report.get('applied'))}`")
    lines.append(f"- Level: `{str(report.get('autofix_level') or 'balanced')}`")
    lines.append(f"- Source records: `{int(report.get('source_record_count', 0))}`")
    lines.append(f"- Modified records: `{int(report.get('modified_record_count', 0))}`")
    lines.append("")
    lines.append("## Fix Counts")
    lines.append("")
    lines.append("| Fix Key | Count |")
    lines.append("| --- | ---: |")
    fix_counts = report.get("fix_counts", {})
    if isinstance(fix_counts, dict) and fix_counts:
        for key, count in sorted(fix_counts.items(), key=lambda x: x[0]):
            lines.append(f"| `{key}` | {int(count)} |")
    else:
        lines.append("| _none_ | 0 |")
    lines.append("")
    lines.append("## Record Actions")
    lines.append("")
    fix_logs = report.get("fix_logs", [])
    if isinstance(fix_logs, list) and fix_logs:
        for item in fix_logs:
            if not isinstance(item, dict):
                continue
            idx = item.get("record_index", "?")
            rid = item.get("record_id", "?")
            lines.append(f"- record#{idx} `{rid}`")
            actions = item.get("actions", [])
            if isinstance(actions, list):
                for action in actions:
                    if not isinstance(action, dict):
                        continue
                    detail = action.get("detail")
                    if isinstance(detail, str) and detail.strip():
                        lines.append(f"  - {detail}")
    else:
        lines.append("No record-level auto-fix actions.")
    lines.append("")
    return "\n".join(lines)

