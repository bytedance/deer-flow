"""OpenReview raw comment importer for offline benchmark construction."""

from __future__ import annotations

import re
from typing import Any

from .offline_benchmark_suite import REQUIRED_RAW_RECORD_FIELDS

_DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")

_MODE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("citation_hallucination", ("hallucinated citation", "fake citation", "fabricated reference", "invalid doi")),
    ("overclaim", ("overclaim", "over-claim", "overstated", "causal claim", "too strong")),
    ("numeric_drift", ("number mismatch", "numeric mismatch", "inconsistent number", "drift", "does not match the table")),
    ("evidence_chain_break", ("not supported by evidence", "missing evidence", "unsupported claim", "evidence chain")),
    ("style_mismatch", ("style mismatch", "off-topic style", "venue style", "writing style does not fit")),
    ("superficial_rebuttal", ("superficial rebuttal", "did not address", "does not address", "not addressed", "surface-level response")),
    ("ethics_gap", ("ethics", "irb", "consent", "bias risk", "missing reproducibility", "reproducibility concern")),
)


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _normalize_decision(value: str) -> str:
    lowered = _as_text(value).lower()
    if "accept" in lowered:
        return "accepted"
    if "reject" in lowered:
        return "rejected"
    if "revise" in lowered:
        return "revise"
    return "unknown"


def _infer_domain(venue: str, raw_domain: str | None = None) -> str:
    if raw_domain:
        normalized = _as_text(raw_domain).lower()
        if normalized in {"ai_cs", "biomed", "cross_discipline"}:
            return normalized
    lowered = _as_text(venue).lower()
    if any(token in lowered for token in ("neurips", "icml", "iclr", "acl", "emnlp", "aaai", "cvpr")):
        return "ai_cs"
    if any(token in lowered for token in ("nature", "cell", "science", "nejm", "lancet", "jama")):
        return "biomed"
    return "cross_discipline"


def _collect_review_texts(row: dict[str, Any]) -> list[str]:
    texts: list[str] = []
    for key in ("reviews", "review_comments", "comments", "notes"):
        payload = row.get(key)
        if not isinstance(payload, list):
            continue
        for item in payload:
            if isinstance(item, str):
                token = _as_text(item)
                if token:
                    texts.append(token)
                continue
            if not isinstance(item, dict):
                continue
            for sub_key in ("text", "comment", "review", "body", "summary", "strengths", "weaknesses", "limitations"):
                token = _as_text(item.get(sub_key))
                if token:
                    texts.append(token)
            content = item.get("content")
            if isinstance(content, str):
                token = _as_text(content)
                if token:
                    texts.append(token)
            elif isinstance(content, dict):
                for val in content.values():
                    token = _as_text(val)
                    if token:
                        texts.append(token)
    return texts


def _classify_failure_modes(text: str) -> list[str]:
    lowered = _as_text(text).lower()
    modes: list[str] = []
    for mode, keywords in _MODE_KEYWORDS:
        if any(keyword in lowered for keyword in keywords):
            modes.append(mode)
    return modes


def _extract_doi_tokens(text: str) -> list[str]:
    found = _DOI_RE.findall(text or "")
    out: list[str] = []
    seen: set[str] = set()
    for token in found:
        normalized = token.strip()
        key = normalized.lower()
        if not normalized or key in seen:
            continue
        seen.add(key)
        out.append(normalized)
    return out


def _coerce_case_id(row: dict[str, Any], index: int) -> str:
    for key in ("case_id", "id", "forum", "submission_id"):
        token = _as_text(row.get(key))
        if token:
            return token
    return f"openreview-{index:05d}"


def build_openreview_raw_records(
    records: list[dict[str, Any]],
    *,
    venue_default: str = "OpenReview",
) -> list[dict[str, Any]]:
    """Convert OpenReview records to raw benchmark records."""
    out: list[dict[str, Any]] = []
    for index, row in enumerate(records, start=1):
        if not isinstance(row, dict):
            continue
        venue = _as_text(row.get("venue")) or venue_default
        decision = _normalize_decision(_as_text(row.get("decision")) or _as_text((row.get("content") or {}).get("decision")))
        review_texts = _collect_review_texts(row)
        joined = "\n".join(review_texts)
        failure_modes = _classify_failure_modes(joined)
        generated = _extract_doi_tokens(joined)
        verified_raw = row.get("verified_citations")
        if isinstance(verified_raw, list):
            verified = [token for token in [_as_text(item) for item in verified_raw] if token]
        else:
            verified = list(generated)
        case = {
            "manuscript_id": _coerce_case_id(row, index),
            "decision": decision,
            "domain": _infer_domain(venue, _as_text(row.get("domain")) or None),
            "venue": venue,
            "generated_citations": generated,
            "verified_citations": verified,
            "claims": row.get("claims") if isinstance(row.get("claims"), list) else [],
            "abstract_numbers": row.get("abstract_numbers") if isinstance(row.get("abstract_numbers"), list) else [],
            "body_numbers": row.get("body_numbers") if isinstance(row.get("body_numbers"), list) else [],
            "reviewer_comment_ids": [f"R{i + 1}" for i in range(len(review_texts))] or ["R1"],
            "rebuttal_addressed_ids": row.get("rebuttal_addressed_ids") if isinstance(row.get("rebuttal_addressed_ids"), list) else [],
            "venue_checklist_items": row.get("venue_checklist_items") if isinstance(row.get("venue_checklist_items"), list) else [],
            "venue_satisfied_items": row.get("venue_satisfied_items") if isinstance(row.get("venue_satisfied_items"), list) else [],
            "cross_modal_items_expected": int(row.get("cross_modal_items_expected") or 0),
            "cross_modal_items_used": int(row.get("cross_modal_items_used") or 0),
            "revision_terms": row.get("revision_terms") if isinstance(row.get("revision_terms"), list) else [],
            "revision_numbers": row.get("revision_numbers") if isinstance(row.get("revision_numbers"), list) else [],
            "failure_modes": failure_modes,
        }
        for key in REQUIRED_RAW_RECORD_FIELDS:
            case.setdefault(key, [] if key not in {"manuscript_id", "decision", "domain", "venue", "cross_modal_items_expected", "cross_modal_items_used"} else None)
        case["cross_modal_items_expected"] = int(case.get("cross_modal_items_expected") or 0)
        case["cross_modal_items_used"] = int(case.get("cross_modal_items_used") or 0)
        out.append(case)
    return out


def build_openreview_raw_payload(
    records: list[dict[str, Any]],
    *,
    dataset_name: str,
    benchmark_split: str = "openreview_offline_benchmark",
    source_name: str = "openreview",
    venue_default: str = "OpenReview",
) -> dict[str, Any]:
    """Build import-ready raw payload from OpenReview source rows."""
    return {
        "metadata": {
            "dataset_name": dataset_name,
            "benchmark_split": benchmark_split,
            "source_name": source_name,
            "venue_default": venue_default,
        },
        "records": build_openreview_raw_records(records, venue_default=venue_default),
    }

