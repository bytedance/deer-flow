from __future__ import annotations

from datetime import UTC, datetime

from scripts.benchmark.deermem_eviction.dataset import EvidenceRecord
from scripts.benchmark.deermem_eviction.policy import evaluate_case
from scripts.benchmark.deermem_eviction.pool import build_case

NOW = datetime(2026, 8, 13, tzinfo=UTC)


def _evidence(question_id: str, question_type: str = "single-session-user") -> EvidenceRecord:
    return EvidenceRecord(
        question_id=question_id,
        question_type=question_type,
        question=f"Question for {question_id}?",
        answer="answer",
        question_date="2026/08/13 (Thu) 10:00",
        content=f"Evidence for {question_id}",
    )


def test_confirmation_scenario_is_deterministic_and_uses_production_policies() -> None:
    support = _evidence("support", "knowledge-update")
    distractors = [_evidence(f"d{i}") for i in range(9)]

    first = build_case(
        support=support,
        distractors=distractors,
        scenario="confirmation_help",
        loss_rank=8,
        evaluation_time=NOW,
    )
    second = build_case(
        support=support,
        distractors=distractors,
        scenario="confirmation_help",
        loss_rank=8,
        evaluation_time=NOW,
    )

    assert first == second
    assert len(first.facts) == 10
    assert [fact["id"] for fact in first.facts] == sorted(fact["id"] for fact in first.facts)

    confidence = evaluate_case(first, policy_name="confidence", capacity=7)
    hybrid = evaluate_case(first, policy_name="hybrid-v1", capacity=7)

    assert confidence.support_all_retained is False
    assert hybrid.support_all_retained is True
    assert confidence.kept_fact_ids != hybrid.kept_fact_ids
    assert all("content" not in evicted for evicted in hybrid.evicted)


def test_correction_reserve_retains_a_low_confidence_correction() -> None:
    support = _evidence("correction_case", "synthetic-correction")
    distractors = [_evidence(f"d{i}") for i in range(9)]
    case = build_case(
        support=support,
        distractors=distractors,
        scenario="correction_reserve",
        loss_rank=8,
        evaluation_time=NOW,
    )

    confidence = evaluate_case(case, policy_name="confidence", capacity=7)
    hybrid = evaluate_case(case, policy_name="hybrid-v1", capacity=7)

    assert confidence.support_all_retained is False
    assert hybrid.support_all_retained is True
    assert hybrid.reserved_correction_slots == 1


def test_policy_result_contains_ids_and_scores_but_not_dataset_text() -> None:
    case = build_case(
        support=_evidence("support", "knowledge-update"),
        distractors=[_evidence(f"d{i}") for i in range(9)],
        scenario="access_help",
        loss_rank=6,
        evaluation_time=NOW,
    )

    result = evaluate_case(case, policy_name="hybrid-v1", capacity=7).to_public_dict()

    assert result["case_id"] == "support"
    assert result["support_fact_ids"] == ["gold_support"]
    assert all(fact_id.startswith("d_support_") or fact_id == "gold_support" for fact_id in result["kept_fact_ids"])
    assert "question" not in result
    assert "answer" not in result
    assert "facts" not in result
