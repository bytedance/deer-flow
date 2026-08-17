from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from deerflow.agents.memory.backends.deermem.deermem.core.eviction import EVICTION_POLICY_HYBRID_V1, select_facts_for_capacity

from .config import HybridPolicyConfig
from .pool import PreparedCase

PolicyName = Literal["confidence", "hybrid-v1"]


def require_production_policy(version: str) -> None:
    """Reject a config whose required policy version has drifted from the production implementation."""
    if version != EVICTION_POLICY_HYBRID_V1:
        raise ValueError(f"config requires eviction policy {version!r} but production implements {EVICTION_POLICY_HYBRID_V1!r}")


@dataclass(frozen=True)
class PolicyResult:
    case_id: str
    source: str
    scenario: str
    question_type: str
    policy: PolicyName
    capacity: int
    support_fact_ids: tuple[str, ...]
    kept_fact_ids: tuple[str, ...]
    evicted: tuple[dict[str, Any], ...]
    scores: dict[str, dict[str, Any]]
    support_all_retained: bool
    support_recall: float
    reserved_correction_slots: int

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "case_id": self.case_id,
            "source": self.source,
            "scenario": self.scenario,
            "question_type": self.question_type,
            "policy": self.policy,
            "capacity": self.capacity,
            "support_fact_ids": list(self.support_fact_ids),
            "kept_fact_ids": list(self.kept_fact_ids),
            "evicted": list(self.evicted),
            "scores": self.scores,
            "support_all_retained": self.support_all_retained,
            "support_recall": self.support_recall,
            "reserved_correction_slots": self.reserved_correction_slots,
        }


def evaluate_case(
    case: PreparedCase,
    *,
    policy_name: PolicyName,
    capacity: int,
    hybrid_config: HybridPolicyConfig | None = None,
) -> PolicyResult:
    kwargs: dict[str, Any] = {}
    if hybrid_config is not None:
        kwargs = {
            "confidence_weight": hybrid_config.weights["confidence"],
            "confirmation_weight": hybrid_config.weights["confirmation"],
            "access_weight": hybrid_config.weights["access"],
            "confirmation_half_life_days": hybrid_config.confirmation_half_life_days,
            "access_half_life_days": hybrid_config.access_half_life_days,
            "correction_reserved_fraction": hybrid_config.correction_reserved_fraction,
            "correction_reserved_max": hybrid_config.correction_reserved_max,
        }
    decision = select_facts_for_capacity(
        case.facts,
        max_facts=capacity,
        policy=policy_name,
        usage=case.usage,
        now=case.evaluation_time,
        **kwargs,
    )
    kept_fact_ids = tuple(str(fact["id"]) for fact in decision.kept)
    retained_support = set(case.support_fact_ids) & set(kept_fact_ids)
    evicted = tuple(
        {
            "fact_id": item.fact_id,
            "category": item.category,
            "score": item.score,
            "components": dict(item.components),
        }
        for item in decision.evicted
    )
    scores = {fact_id: {"value": score.value, "components": dict(score.components)} for fact_id, score in sorted(decision.scores.items())}
    return PolicyResult(
        case_id=case.case_id,
        source=case.source,
        scenario=case.scenario,
        question_type=case.question_type,
        policy=policy_name,
        capacity=capacity,
        support_fact_ids=case.support_fact_ids,
        kept_fact_ids=kept_fact_ids,
        evicted=evicted,
        scores=scores,
        support_all_retained=len(retained_support) == len(case.support_fact_ids),
        support_recall=len(retained_support) / len(case.support_fact_ids),
        reserved_correction_slots=decision.reserved_correction_slots,
    )
