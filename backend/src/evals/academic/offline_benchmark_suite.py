"""Offline benchmark suite builder for academic eval loops.

Builds layered raw datasets that can be imported by
`scripts/import_academic_eval_dataset.py`:
- core accept/reject calibration set,
- failure-mode hard negatives set,
- domain splits (ai_cs / biomed / cross_discipline).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .loader import load_builtin_eval_cases
from .schemas import AcademicEvalCase

OFFLINE_BENCHMARK_SUITE_VERSION = "academic_offline_benchmark_suite.v1"

REQUIRED_RAW_RECORD_FIELDS: tuple[str, ...] = (
    "manuscript_id",
    "decision",
    "domain",
    "venue",
    "generated_citations",
    "verified_citations",
    "claims",
    "abstract_numbers",
    "body_numbers",
    "reviewer_comment_ids",
    "rebuttal_addressed_ids",
    "venue_checklist_items",
    "venue_satisfied_items",
    "cross_modal_items_expected",
    "cross_modal_items_used",
    "revision_terms",
    "revision_numbers",
    "failure_modes",
)

TARGET_HARD_NEGATIVE_FAILURE_MODES: tuple[str, ...] = (
    "citation_hallucination",
    "overclaim",
    "numeric_drift",
    "evidence_chain_break",
    "style_mismatch",
    "superficial_rebuttal",
    "ethics_gap",
)

LAYER_FILE_NAMES: dict[str, str] = {
    "core": "core_top_venue_accept_reject_raw.json",
    "failure_mode": "failure_mode_hard_negatives_raw.json",
    "domain_ai_cs": "domain_ai_cs_raw.json",
    "domain_biomed": "domain_biomed_raw.json",
    "domain_cross_discipline": "domain_cross_discipline_raw.json",
}


def _dedup_str_list(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in values:
        token = str(item).strip()
        if not token:
            continue
        lowered = token.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        out.append(token)
    return out


def _normalize_claims(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for claim in claims:
        payload = dict(claim)
        payload.setdefault("type", "weak")
        payload["has_evidence"] = bool(payload.get("has_evidence"))
        payload["has_citation"] = bool(payload.get("has_citation"))
        normalized.append(payload)
    return normalized


def _to_raw_record(case: AcademicEvalCase) -> dict[str, Any]:
    record: dict[str, Any] = {
        "manuscript_id": case.case_id,
        "decision": case.decision,
        "domain": case.domain,
        "venue": case.venue,
        "generated_citations": list(case.generated_citations),
        "verified_citations": list(case.verified_citations),
        "claims": _normalize_claims(list(case.claims)),
        "abstract_numbers": [float(x) for x in case.abstract_numbers],
        "body_numbers": [float(x) for x in case.body_numbers],
        "reviewer_comment_ids": list(case.reviewer_comment_ids),
        "rebuttal_addressed_ids": list(case.rebuttal_addressed_ids),
        "venue_checklist_items": list(case.venue_checklist_items),
        "venue_satisfied_items": list(case.venue_satisfied_items),
        "cross_modal_items_expected": int(case.cross_modal_items_expected),
        "cross_modal_items_used": int(case.cross_modal_items_used),
        "revision_terms": [list(row) for row in case.revision_terms],
        "revision_numbers": [[float(x) for x in row] for row in case.revision_numbers],
        "failure_modes": [str(x).strip().lower() for x in case.failure_modes if str(x).strip()],
    }
    if case.manuscript_text:
        record["manuscript_text"] = str(case.manuscript_text)
    return record


def _ensure_required_fields(record: dict[str, Any]) -> dict[str, Any]:
    payload = dict(record)
    payload.setdefault("generated_citations", [])
    payload.setdefault("verified_citations", [])
    payload.setdefault("claims", [])
    payload.setdefault("abstract_numbers", [])
    payload.setdefault("body_numbers", [])
    payload.setdefault("reviewer_comment_ids", [])
    payload.setdefault("rebuttal_addressed_ids", [])
    payload.setdefault("venue_checklist_items", [])
    payload.setdefault("venue_satisfied_items", [])
    payload.setdefault("cross_modal_items_expected", 0)
    payload.setdefault("cross_modal_items_used", 0)
    payload.setdefault("revision_terms", [])
    payload.setdefault("revision_numbers", [])
    payload.setdefault("failure_modes", [])
    return payload


def _merge_cross_case(case_id: str, left: AcademicEvalCase, right: AcademicEvalCase, *, decision: str) -> dict[str, Any]:
    claims = _normalize_claims(list(left.claims)[:1] + list(right.claims)[:1])
    combined = {
        "manuscript_id": case_id,
        "decision": decision,
        "domain": "cross_discipline",
        "venue": f"{left.venue}+{right.venue}",
        "generated_citations": _dedup_str_list(list(left.generated_citations) + list(right.generated_citations)),
        "verified_citations": _dedup_str_list(list(left.verified_citations) + list(right.verified_citations)),
        "claims": claims,
        "abstract_numbers": [*left.abstract_numbers[:1], *right.abstract_numbers[:1]],
        "body_numbers": [*left.body_numbers[:1], *right.body_numbers[:1]],
        "reviewer_comment_ids": _dedup_str_list(list(left.reviewer_comment_ids) + list(right.reviewer_comment_ids)),
        "rebuttal_addressed_ids": _dedup_str_list(list(left.rebuttal_addressed_ids) + list(right.rebuttal_addressed_ids)),
        "venue_checklist_items": _dedup_str_list(list(left.venue_checklist_items) + list(right.venue_checklist_items)),
        "venue_satisfied_items": _dedup_str_list(list(left.venue_satisfied_items) + list(right.venue_satisfied_items)),
        "cross_modal_items_expected": int(left.cross_modal_items_expected) + int(right.cross_modal_items_expected),
        "cross_modal_items_used": int(left.cross_modal_items_used) + int(right.cross_modal_items_used),
        "revision_terms": [list(left.revision_terms[0] if left.revision_terms else []), list(right.revision_terms[0] if right.revision_terms else [])],
        "revision_numbers": [[float(x) for x in (left.revision_numbers[0] if left.revision_numbers else [])], [float(x) for x in (right.revision_numbers[0] if right.revision_numbers else [])]],
        "failure_modes": [],
    }
    return _ensure_required_fields(combined)


def _build_cross_discipline_records(cases: list[AcademicEvalCase]) -> list[dict[str, Any]]:
    ai_cases = [case for case in cases if str(case.domain).strip().lower() == "ai_cs"]
    biomed_cases = [case for case in cases if str(case.domain).strip().lower() == "biomed"]
    ai_acc = next((case for case in ai_cases if case.decision == "accepted"), None)
    bio_acc = next((case for case in biomed_cases if case.decision == "accepted"), None)
    ai_rej = next((case for case in ai_cases if case.decision == "rejected"), None)
    bio_rej = next((case for case in biomed_cases if case.decision == "rejected"), None)
    if ai_acc is None or bio_acc is None or ai_rej is None or bio_rej is None:
        return []
    return [
        _merge_cross_case("cross-acc-01", ai_acc, bio_acc, decision="accepted"),
        _merge_cross_case("cross-rej-01", ai_rej, bio_rej, decision="rejected"),
    ]


def build_offline_benchmark_layers(core_cases: list[AcademicEvalCase], failure_mode_cases: list[AcademicEvalCase]) -> dict[str, dict[str, Any]]:
    core_records = [_ensure_required_fields(_to_raw_record(case)) for case in core_cases]
    hard_mode_set = set(TARGET_HARD_NEGATIVE_FAILURE_MODES)
    hard_negative_cases = [
        case for case in failure_mode_cases if set(str(item).strip().lower() for item in case.failure_modes).intersection(hard_mode_set)
    ]
    failure_records = [_ensure_required_fields(_to_raw_record(case)) for case in hard_negative_cases]
    all_cases = [*core_cases, *failure_mode_cases]
    ai_records = [_ensure_required_fields(_to_raw_record(case)) for case in all_cases if str(case.domain).strip().lower() == "ai_cs"]
    biomed_records = [_ensure_required_fields(_to_raw_record(case)) for case in all_cases if str(case.domain).strip().lower() == "biomed"]
    cross_records = _build_cross_discipline_records(all_cases)

    return {
        "core": {
            "metadata": {
                "suite_version": OFFLINE_BENCHMARK_SUITE_VERSION,
                "layer": "core",
                "source_name": "deerflow-offline-benchmark-core",
                "domain": "mixed",
                "note": "Top venue accept/reject cases for AUC/ECE/Brier calibration.",
            },
            "records": core_records,
        },
        "failure_mode": {
            "metadata": {
                "suite_version": OFFLINE_BENCHMARK_SUITE_VERSION,
                "layer": "failure_mode",
                "source_name": "deerflow-offline-benchmark-failure-mode",
                "domain": "mixed",
                "note": (
                    "Hard negatives covering seven red-team risk classes: citation hallucination, overclaim, "
                    "numeric drift, evidence chain break, style mismatch, superficial rebuttal, and ethics gap."
                ),
            },
            "records": failure_records,
        },
        "domain_ai_cs": {
            "metadata": {
                "suite_version": OFFLINE_BENCHMARK_SUITE_VERSION,
                "layer": "domain_split",
                "source_name": "deerflow-offline-benchmark-domain-ai-cs",
                "domain": "ai_cs",
                "note": "Domain slice for AI/CS weighting profile.",
            },
            "records": ai_records,
        },
        "domain_biomed": {
            "metadata": {
                "suite_version": OFFLINE_BENCHMARK_SUITE_VERSION,
                "layer": "domain_split",
                "source_name": "deerflow-offline-benchmark-domain-biomed",
                "domain": "biomed",
                "note": "Domain slice for biomed weighting profile.",
            },
            "records": biomed_records,
        },
        "domain_cross_discipline": {
            "metadata": {
                "suite_version": OFFLINE_BENCHMARK_SUITE_VERSION,
                "layer": "domain_split",
                "source_name": "deerflow-offline-benchmark-domain-cross",
                "domain": "cross_discipline",
                "note": "Cross-disciplinary synthetic slice for mixed-venue robustness.",
            },
            "records": cross_records,
        },
    }


def write_offline_benchmark_layers(output_dir: Path, *, overwrite: bool = False, core_dataset_name: str = "top_tier_accept_reject_v1", failure_mode_dataset_name: str = "failure_mode_library_v1") -> dict[str, Path]:
    core_cases = load_builtin_eval_cases(core_dataset_name)
    failure_cases = load_builtin_eval_cases(failure_mode_dataset_name)
    layers = build_offline_benchmark_layers(core_cases, failure_cases)
    output_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for layer_key, payload in layers.items():
        file_name = LAYER_FILE_NAMES[layer_key]
        target = output_dir / file_name
        if target.exists() and not overwrite:
            raise FileExistsError(f"Refusing to overwrite existing file: {target}")
        target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        written[layer_key] = target
    return written

