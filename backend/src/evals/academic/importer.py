"""Import pipeline for real accept/reject academic benchmark datasets.

This module converts raw manuscript-review records into normalized
`AcademicEvalCase` entries with:
- anonymization (PII redaction + stable hashed case ids),
- field standardization (schema alignment),
- dataset versioning metadata.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .schemas import AcademicEvalCase, ManuscriptDecision

DATASET_SCHEMA_VERSION = "academic_eval_dataset.v2"
IMPORT_PIPELINE_VERSION = "accept_reject_importer.v1"
NORMALIZATION_PROFILE = "accept_reject_standardization.v1"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _slugify(value: str, *, default: str = "dataset") -> str:
    lowered = (value or "").strip().lower()
    lowered = re.sub(r"[^a-z0-9._-]+", "-", lowered)
    lowered = re.sub(r"-{2,}", "-", lowered).strip("-")
    return lowered or default


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _stable_anon(value: str, *, salt: str) -> str:
    token = _sha256_text(f"{salt}:{value}")
    return f"anon_{token[:14]}"


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
    return out


def _normalize_failure_modes(value: Any) -> list[str]:
    modes = _as_str_list(value)
    deduped: list[str] = []
    seen: set[str] = set()
    for token in modes:
        lowered = token.strip().lower()
        if not lowered or lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(lowered)
    return deduped


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


def _normalize_claims(value: Any, *, redact: bool = False) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    claims: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            claim_type = str(
                item.get("type")
                or item.get("claim_type")
                or "weak"
            ).lower()
            has_evidence = bool(item.get("has_evidence") or item.get("evidence"))
            has_citation = bool(item.get("has_citation") or item.get("citation"))
            payload: dict[str, Any] = {
                "type": claim_type,
                "has_evidence": has_evidence,
                "has_citation": has_citation,
            }
            if isinstance(item.get("text"), str) and item["text"].strip():
                payload["text"] = _anonymize_text(item["text"]) if redact else item["text"].strip()
            claims.append(payload)
            continue
        if isinstance(item, str) and item.strip():
            claims.append(
                {
                    "type": "weak",
                    "has_evidence": False,
                    "has_citation": False,
                    "text": _anonymize_text(item) if redact else item,
                }
            )
    return claims


def _normalize_revision_terms(value: Any, *, redact: bool = False) -> list[list[str]]:
    if not isinstance(value, list):
        return []
    out: list[list[str]] = []
    for row in value:
        if not isinstance(row, list):
            continue
        tokens = [str(token).strip() for token in row if str(token).strip()]
        if redact:
            tokens = [_anonymize_text(token) for token in tokens]
        out.append(tokens)
    return out


def _normalize_revision_numbers(value: Any) -> list[list[float]]:
    if not isinstance(value, list):
        return []
    out: list[list[float]] = []
    for row in value:
        out.append(_as_float_list(row))
    return out


def _normalize_reviewer_ids(value: Any) -> list[str]:
    if isinstance(value, list):
        ids: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                ids.append(item.strip())
            elif isinstance(item, dict):
                candidate = item.get("id") or item.get("comment_id") or item.get("reviewer_id")
                if isinstance(candidate, str) and candidate.strip():
                    ids.append(candidate.strip())
        return ids
    return []


def _normalize_decision(value: Any) -> ManuscriptDecision:
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


def _anonymize_text(value: str) -> str:
    text = value
    text = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[EMAIL]", text)
    text = re.sub(r"https?://\S+", "[URL]", text)
    text = re.sub(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\b", "[DOI]", text)
    text = re.sub(r"\b(?:orcid\.org/)?\d{4}-\d{4}-\d{4}-\d{3}[\dX]\b", "[ORCID]", text, flags=re.IGNORECASE)
    return text


def _normalize_optional_text(value: Any, *, redact: bool) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    return _anonymize_text(text) if redact else text


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
    raise ValueError("Raw dataset must be a JSON array or object containing `records`/`cases`/`items`/`submissions` list")


def import_accept_reject_payload(
    raw_payload: Any,
    *,
    source_path_label: str,
    dataset_name: str,
    dataset_version: str,
    benchmark_split: str | None = None,
    source_name: str | None = None,
    anonymize: bool = True,
    strict: bool = False,
    source_fingerprint: str | None = None,
) -> dict[str, Any]:
    """Import raw accept/reject payload as normalized eval dataset."""
    normalized_name = _slugify(dataset_name, default="top-tier-accept-reject")
    normalized_version = _slugify(dataset_version, default="v1")
    resolved_split = _slugify(
        benchmark_split or f"{normalized_name}_{normalized_version}",
        default=f"{normalized_name}_{normalized_version}",
    )
    resolved_source_name = (source_name or "").strip() or None

    raw_records, source_metadata = _extract_raw_records(raw_payload)
    if source_fingerprint is None:
        source_fingerprint = _sha256_text(
            json.dumps(raw_payload, ensure_ascii=False, sort_keys=True)
        )
    salt = source_fingerprint[:12]

    warnings: list[str] = []
    skipped = 0
    cases: list[AcademicEvalCase] = []
    accepted_count = 0
    rejected_count = 0

    for index, record in enumerate(raw_records, start=1):
        try:
            decision = _normalize_decision(
                record.get("decision")
                or record.get("outcome")
                or record.get("review_decision")
            )
            record_source_name = (
                resolved_source_name
                or record.get("source_name")
                or source_metadata.get("source_name")
                or "top-tier-real-import"
            )
            raw_case_id = str(
                record.get("case_id")
                or record.get("manuscript_id")
                or record.get("submission_id")
                or f"{normalized_name}-{index:04d}"
            )
            case_id = _stable_anon(raw_case_id, salt=salt) if anonymize else _slugify(raw_case_id, default=f"case-{index:04d}")

            claims = _normalize_claims(
                record.get("claims") or record.get("claim_annotations") or [],
                redact=anonymize,
            )
            review_comments = (
                record.get("reviewer_comment_ids")
                or record.get("reviewer_comments")
                or record.get("review_comments")
                or []
            )
            rebuttal_addressed = (
                record.get("rebuttal_addressed_ids")
                or record.get("addressed_comment_ids")
                or []
            )

            case = AcademicEvalCase(
                case_id=case_id,
                domain=str(
                    record.get("domain")
                    or record.get("discipline")
                    or source_metadata.get("domain")
                    or "unknown"
                ),
                venue=str(
                    record.get("venue")
                    or record.get("journal")
                    or record.get("conference")
                    or source_metadata.get("venue")
                    or "unknown"
                ),
                generated_citations=_as_str_list(record.get("generated_citations") or record.get("output_citations")),
                verified_citations=_as_str_list(record.get("verified_citations") or record.get("ground_truth_citations")),
                claims=claims,
                abstract_numbers=_as_float_list(record.get("abstract_numbers") or record.get("abstract_text") or ""),
                body_numbers=_as_float_list(record.get("body_numbers") or record.get("body_text") or ""),
                reviewer_comment_ids=_normalize_reviewer_ids(review_comments),
                rebuttal_addressed_ids=_normalize_reviewer_ids(rebuttal_addressed),
                venue_checklist_items=_as_str_list(record.get("venue_checklist_items") or record.get("acceptance_checklist")),
                venue_satisfied_items=_as_str_list(record.get("venue_satisfied_items") or record.get("satisfied_checklist")),
                cross_modal_items_expected=int(record.get("cross_modal_items_expected") or record.get("cross_modal_expected") or 0),
                cross_modal_items_used=int(record.get("cross_modal_items_used") or record.get("cross_modal_used") or 0),
                revision_terms=_normalize_revision_terms(record.get("revision_terms") or [], redact=anonymize),
                revision_numbers=_normalize_revision_numbers(record.get("revision_numbers") or []),
                failure_modes=_normalize_failure_modes(record.get("failure_modes") or record.get("failure_mode_tags") or []),
                manuscript_text=_normalize_optional_text(
                    record.get("manuscript_text") or record.get("full_text"),
                    redact=anonymize,
                ),
                decision=decision,
                benchmark_split=resolved_split,
                source_name=str(record_source_name),
            )
            cases.append(case)
            if decision == "accepted":
                accepted_count += 1
            elif decision == "rejected":
                rejected_count += 1
        except Exception as exc:
            skipped += 1
            message = f"skip record #{index}: {exc}"
            if strict:
                raise ValueError(message) from exc
            warnings.append(message)

    dataset_payload = {
        "metadata": {
            "schema_version": DATASET_SCHEMA_VERSION,
            "pipeline_version": IMPORT_PIPELINE_VERSION,
            "normalization_profile": NORMALIZATION_PROFILE,
            "dataset_name": normalized_name,
            "dataset_version": normalized_version,
            "benchmark_split": resolved_split,
            "source_name": resolved_source_name or "top-tier-real-import",
            "imported_at": _now_iso(),
            "anonymized": anonymize,
            "source_record_count": len(raw_records),
            "record_count": len(cases),
            "accepted_count": accepted_count,
            "rejected_count": rejected_count,
            "skipped_count": skipped,
            "source_fingerprint": source_fingerprint,
            "source_path": source_path_label,
        },
        "cases": [item.model_dump() for item in cases],
    }

    manifest_payload = {
        "dataset_name": normalized_name,
        "dataset_version": normalized_version,
        "benchmark_split": resolved_split,
        "source_name": resolved_source_name or "top-tier-real-import",
        "imported_at": _now_iso(),
        "source_path": source_path_label,
        "source_fingerprint": source_fingerprint,
        "source_record_count": len(raw_records),
        "imported_case_count": len(cases),
        "accepted_case_count": accepted_count,
        "rejected_case_count": rejected_count,
        "skipped_case_count": skipped,
        "anonymized": anonymize,
        "warnings": warnings,
    }
    return {
        "dataset_name": normalized_name,
        "dataset_version": normalized_version,
        "benchmark_split": resolved_split,
        "source_name": resolved_source_name or "top-tier-real-import",
        "anonymized": anonymize,
        "imported_case_count": len(cases),
        "accepted_case_count": accepted_count,
        "rejected_case_count": rejected_count,
        "skipped_case_count": skipped,
        "warnings": warnings,
        "dataset_payload": dataset_payload,
        "manifest_payload": manifest_payload,
    }


def import_accept_reject_dataset(
    source_path: Path,
    *,
    dataset_name: str,
    dataset_version: str,
    benchmark_split: str | None = None,
    source_name: str | None = None,
    anonymize: bool = True,
    strict: bool = False,
) -> dict[str, Any]:
    """Import raw accept/reject records from a file."""
    raw_text = source_path.read_text(encoding="utf-8")
    raw_payload = json.loads(raw_text)
    return import_accept_reject_payload(
        raw_payload,
        source_path_label=str(source_path),
        dataset_name=dataset_name,
        dataset_version=dataset_version,
        benchmark_split=benchmark_split,
        source_name=source_name,
        anonymize=anonymize,
        strict=strict,
        source_fingerprint=_sha256_text(raw_text),
    )

