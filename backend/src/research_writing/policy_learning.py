"""Policy-learning utilities that convert HITL decisions into update signals."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Literal

from pydantic import BaseModel, Field

from src.research_writing.project_state import HitlDecision

SignalDecision = Literal["pending", "approved", "rejected"]

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = {
    "peer",
    "loop",
    "round",
    "hitl",
    "confirm",
    "select",
    "lock",
    "set",
    "add",
    "the",
    "and",
    "for",
}
_CONSERVATIVE_HINTS = {"causal", "definitive", "overclaim", "strong", "certainty"}
_VALIDATION_HINTS = {"ablation", "baseline", "control", "experiment", "validation"}
_COMPLIANCE_HINTS = {"ethics", "irb", "consent", "reproducibility", "reproducible", "code", "data"}


class PolicySignal(BaseModel):
    """One HITL-derived reward signal."""

    action_id: str
    section_id: str | None = None
    decision: SignalDecision
    reward: float = 0.0
    source: str = ""
    label: str = ""
    feature_tokens: list[str] = Field(default_factory=list)


class PolicyActionStat(BaseModel):
    """Aggregated action-level statistics used for strategy updates."""

    action_id: str
    approvals: int = 0
    rejections: int = 0
    pendings: int = 0
    support: int = 0
    mean_reward: float = 0.0
    weight_delta: float = 0.0
    feature_tokens: list[str] = Field(default_factory=list)


class PolicyLearningSnapshot(BaseModel):
    """Current policy-learning state distilled from HITL feedback."""

    policy_name: str = "HITLPolicy.v1"
    signal_count: int = 0
    approval_count: int = 0
    rejection_count: int = 0
    pending_count: int = 0
    average_reward: float = 0.0
    recommended_tone: Literal["conservative", "balanced", "aggressive"] = "balanced"
    prefer_conservative_claims: bool = False
    require_stronger_validation: bool = False
    require_ethics_reproducibility: bool = False
    action_stats: list[PolicyActionStat] = Field(default_factory=list)
    signals: list[PolicySignal] = Field(default_factory=list)


def _tokenize(text: str) -> list[str]:
    tokens = [item.lower() for item in _TOKEN_RE.findall(text or "")]
    filtered = [token for token in tokens if token not in _STOPWORDS and len(token) > 2]
    # Keep order and remove duplicates.
    out: list[str] = []
    seen: set[str] = set()
    for token in filtered:
        if token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out[:12]


def _decision_reward(decision: SignalDecision) -> float:
    if decision == "approved":
        return 1.0
    if decision == "rejected":
        return -1.0
    return 0.0


def _recommended_tone(avg_reward: float) -> Literal["conservative", "balanced", "aggressive"]:
    if avg_reward <= -0.15:
        return "conservative"
    if avg_reward >= 0.25:
        return "aggressive"
    return "balanced"


def learn_policy_from_hitl_decisions(
    decisions: list[HitlDecision],
    *,
    section_id: str | None = None,
) -> PolicyLearningSnapshot:
    """Convert HITL approve/reject signals into policy-learning snapshot."""
    scoped = decisions
    if section_id is not None:
        scoped = [item for item in decisions if item.section_id == section_id]
    if not scoped:
        return PolicyLearningSnapshot()

    signals: list[PolicySignal] = []
    grouped: dict[str, list[PolicySignal]] = defaultdict(list)
    approvals = 0
    rejections = 0
    pendings = 0

    for item in scoped:
        decision = item.decision
        if decision == "approved":
            approvals += 1
        elif decision == "rejected":
            rejections += 1
        else:
            pendings += 1
        tokens = _tokenize(f"{item.action_id} {item.label} {item.source}")
        signal = PolicySignal(
            action_id=item.action_id,
            section_id=item.section_id,
            decision=decision,
            reward=_decision_reward(decision),
            source=item.source,
            label=item.label,
            feature_tokens=tokens,
        )
        signals.append(signal)
        grouped[item.action_id].append(signal)

    action_stats: list[PolicyActionStat] = []
    conservative_votes = 0
    validation_votes = 0
    compliance_votes = 0

    for action_id, rows in grouped.items():
        support = len(rows)
        rewards = [row.reward for row in rows]
        mean_reward = sum(rewards) / float(support)
        feature_tokens: list[str] = []
        for row in rows:
            for token in row.feature_tokens:
                if token not in feature_tokens:
                    feature_tokens.append(token)

        approvals_n = sum(1 for row in rows if row.decision == "approved")
        rejections_n = sum(1 for row in rows if row.decision == "rejected")
        pendings_n = support - approvals_n - rejections_n
        # Keep update magnitude bounded and data-efficient.
        weight_delta = max(-0.35, min(0.35, mean_reward * min(1.0, support / 4.0)))
        action_stats.append(
            PolicyActionStat(
                action_id=action_id,
                approvals=approvals_n,
                rejections=rejections_n,
                pendings=pendings_n,
                support=support,
                mean_reward=round(mean_reward, 4),
                weight_delta=round(weight_delta, 4),
                feature_tokens=feature_tokens,
            )
        )

        if rejections_n > approvals_n:
            token_set = set(feature_tokens)
            if token_set & _CONSERVATIVE_HINTS:
                conservative_votes += 1
            if token_set & _VALIDATION_HINTS:
                validation_votes += 1
            if token_set & _COMPLIANCE_HINTS:
                compliance_votes += 1

    action_stats.sort(key=lambda row: (row.mean_reward, row.support), reverse=True)
    average_reward = sum(item.reward for item in signals) / float(len(signals))
    return PolicyLearningSnapshot(
        signal_count=len(signals),
        approval_count=approvals,
        rejection_count=rejections,
        pending_count=pendings,
        average_reward=round(average_reward, 4),
        recommended_tone=_recommended_tone(average_reward),
        prefer_conservative_claims=conservative_votes > 0 or average_reward < -0.2,
        require_stronger_validation=validation_votes > 0,
        require_ethics_reproducibility=compliance_votes > 0,
        action_stats=action_stats,
        signals=signals,
    )

