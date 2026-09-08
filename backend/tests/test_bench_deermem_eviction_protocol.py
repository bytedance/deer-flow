from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from scripts.benchmark.deermem_eviction.dataset import DatasetIntegrityError, EvidenceRecord, LongMemEvalDataset
from scripts.benchmark.deermem_eviction.manifest import OfficialManifest
from scripts.benchmark.deermem_eviction.protocol import _distractors, validate_official_selection

SCENARIO_ORDER = ["confirmation_help", "access_help", "confidence_control", "noisy_signal_control"]


def _row(question_id: str, question_type: str, *, answer: str = "short answer", evidence_chars: int = 120) -> dict[str, Any]:
    return {
        "question_id": question_id,
        "question_type": question_type,
        "question": f"question for {question_id}?",
        "answer": answer,
        "haystack_session_ids": ["s1"],
        "haystack_dates": ["2023/05/20"],
        "haystack_sessions": [[{"role": "user", "content": "x" * evidence_chars, "has_answer": True}]],
    }


def _eligible_ids(prefix: str) -> list[str]:
    return [f"{prefix}-{index:03d}" for index in range(1, 21)]


def _dataset(rows: list[dict[str, Any]]) -> LongMemEvalDataset:
    return LongMemEvalDataset(path=Path("synthetic"), sha256="0" * 64, rows=tuple(rows), rows_by_id={row["question_id"]: row for row in rows})


def _rows_with_exclusions() -> list[dict[str, Any]]:
    rows = [_row(question_id, "knowledge-update") for question_id in _eligible_ids("ku")]
    rows += [_row(question_id, "temporal-reasoning") for question_id in _eligible_ids("tr")]
    # Every excluded row sorts before the eligible IDs, so a broken exclusion changes the recomputed selection.
    rows.append(_row("ku-000-pilot", "knowledge-update"))
    rows.append(_row("ku-000_abs", "knowledge-update"))
    rows.append(_row("ku-000-long-answer", "knowledge-update", answer="a" * 150))
    rows.append(_row("ku-000-refusal", "knowledge-update", answer="there is not enough information"))
    rows.append(_row("ku-000-evidence", "knowledge-update", evidence_chars=2500))
    return rows


def _manifest(*, excluded_pilot_ids: list[str] | None = None, scenarios: dict[str, list[str]] | None = None) -> OfficialManifest:
    if scenarios is None:
        ku, tr = _eligible_ids("ku"), _eligible_ids("tr")
        scenarios = {scenario: ku[index * 5 : (index + 1) * 5] + tr[index * 5 : (index + 1) * 5] for index, scenario in enumerate(SCENARIO_ORDER)}
    return OfficialManifest.model_validate(
        {
            "schema_version": 1,
            "protocol_id": "synthetic-protocol",
            "selection": {
                "eligible_question_types": ["knowledge-update", "temporal-reasoning"],
                "excluded_pilot_ids": ["ku-000-pilot"] if excluded_pilot_ids is None else excluded_pilot_ids,
                "exclude_abstention_suffix": "_abs",
                "answer_min_chars": 1,
                "answer_max_chars": 100,
                "answer_excluded_substrings": ["not enough", "only mentioned"],
                "evidence_min_chars": 1,
                "evidence_max_chars": 2000,
                "take_per_question_type": 20,
                "cases_per_type_per_scenario": 5,
            },
            "scenario_order": SCENARIO_ORDER,
            "loss_ranks": [6, 6, 6, 8, 8, 8, 10, 10, 10, 10],
            "scenarios": scenarios,
        }
    )


def test_selection_recomputation_accepts_a_manifest_matching_the_published_rule() -> None:
    validate_official_selection(_dataset(_rows_with_exclusions()), _manifest())


def test_selection_recomputation_rejects_ids_that_break_the_rule() -> None:
    ku, tr = _eligible_ids("ku"), _eligible_ids("tr")
    scenarios = {scenario: ku[index * 5 : (index + 1) * 5] + tr[index * 5 : (index + 1) * 5] for index, scenario in enumerate(SCENARIO_ORDER)}
    scenarios["confirmation_help"], scenarios["access_help"] = (
        scenarios["confirmation_help"][:9] + [scenarios["access_help"][9]],
        scenarios["access_help"][:9] + [scenarios["confirmation_help"][9]],
    )
    with pytest.raises(DatasetIntegrityError, match="do not match the declared selection rule"):
        validate_official_selection(_dataset(_rows_with_exclusions()), _manifest(scenarios=scenarios))


def test_selection_recomputation_applies_every_published_exclusion() -> None:
    manifest = _manifest()
    excluded = {"ku-000-pilot", "ku-000_abs", "ku-000-long-answer", "ku-000-refusal", "ku-000-evidence"}
    pinned = {question_id for question_ids in manifest.scenarios.values() for question_id in question_ids}
    assert not (excluded & pinned)
    # Dropping the pilot exclusion changes the recomputed selection, so validation must fail against the pinned IDs.
    with pytest.raises(DatasetIntegrityError):
        validate_official_selection(_dataset(_rows_with_exclusions()), _manifest(excluded_pilot_ids=[]))


def test_selection_recomputation_requires_enough_eligible_rows() -> None:
    rows = [row for row in _rows_with_exclusions() if row["question_id"] != "tr-020"]
    with pytest.raises(DatasetIntegrityError, match="not enough eligible"):
        validate_official_selection(_dataset(rows), _manifest())


def _bank(size: int = 5) -> list[EvidenceRecord]:
    return [EvidenceRecord(question_id=f"b{index}", question_type="single-session-user", question="q?", answer="a", question_date=None, content=f"evidence {index}") for index in range(size)]


def test_distractor_offset_derivation_and_wraparound_are_pinned() -> None:
    # Hardcoded expectations for sha256(f"offset-ns:{case_id}").digest()[:4] % 5;
    # a regression in the digest slice, modulus, or wraparound changes these indices.
    bank = _bank()
    no_wrap = _distractors("case-a", bank, count=3, namespace="offset-ns")
    assert [record.question_id for record in no_wrap] == ["b0", "b1", "b2"]
    wraps = _distractors("case-c", bank, count=3, namespace="offset-ns")
    assert [record.question_id for record in wraps] == ["b3", "b4", "b0"]
    assert [record.question_id for record in _distractors("case-a", bank, count=3, namespace="alt-ns")] == ["b1", "b2", "b3"]


def test_distractor_selection_requires_a_large_enough_bank() -> None:
    with pytest.raises(DatasetIntegrityError, match="required"):
        _distractors("case-a", _bank(size=2), count=3, namespace="offset-ns")
