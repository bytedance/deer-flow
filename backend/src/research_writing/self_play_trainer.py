"""Self-play trainer for Reviewer/Author/Area-Chair debate loops."""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel, Field

from src.research_writing.ethics_compliance import ComplianceAuditReport, audit_scientific_compliance
from src.research_writing.peer_review_loop import PeerReviewLoopResult, run_peer_review_loop


class SelfPlayEpisodeInput(BaseModel):
    """One self-play episode seed."""

    manuscript_text: str
    venue_name: str | None = None
    section_id: str | None = None
    episode_id: str | None = None


class HardNegativeExample(BaseModel):
    """Hard-negative sample mined from a failed or risky debate trajectory."""

    hard_negative_id: str
    episode_id: str
    venue_name: str
    section_id: str | None = None
    original_text: str
    final_text: str
    final_decision: Literal["accept", "needs_human_intervention"] = "needs_human_intervention"
    round_count: int = 0
    initial_major_issue_count: int = 0
    unresolved_issue_count: int = 0
    reasons: list[str] = Field(default_factory=list)
    issue_types: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class SelfPlayEpisodeResult(BaseModel):
    """Episode-level outcome statistics."""

    episode_id: str
    venue_name: str
    section_id: str | None = None
    round_count: int = 0
    initial_major_issue_count: int = 0
    final_decision: Literal["accept", "needs_human_intervention"] = "needs_human_intervention"
    unresolved_issue_count: int = 0
    issue_types: list[str] = Field(default_factory=list)
    compliance_risk_level: Literal["low", "medium", "high"] = "low"
    hard_negative: bool = False
    hard_negative_reasons: list[str] = Field(default_factory=list)
    artifact_summary: dict[str, float | int | str] = Field(default_factory=dict)


class SelfPlayTrainingResult(BaseModel):
    """Aggregated result for one self-play training run."""

    run_name: str
    total_episodes: int
    accepted_episodes: int
    hard_negative_count: int
    hard_negative_rate: float
    episodes: list[SelfPlayEpisodeResult] = Field(default_factory=list)
    hard_negatives: list[HardNegativeExample] = Field(default_factory=list)


def _stable_id(prefix: str, text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _collect_issue_types(result: PeerReviewLoopResult) -> list[str]:
    types: list[str] = []
    for row in result.rounds:
        for issue in row.reviewer_issues:
            if issue.issue_type not in types:
                types.append(issue.issue_type)
    return types


def _collect_recommendations(result: PeerReviewLoopResult, compliance: ComplianceAuditReport) -> list[str]:
    out: list[str] = []
    for row in result.rounds:
        for note in row.author_revision_notes:
            item = note.strip()
            if item and item not in out:
                out.append(item)
    for finding in compliance.findings:
        if finding.recommendation not in out:
            out.append(finding.recommendation)
    return out[:10]


def _hard_negative_reasons(
    result: PeerReviewLoopResult,
    compliance: ComplianceAuditReport,
    *,
    major_issue_threshold: int = 2,
) -> tuple[list[str], int]:
    reasons: list[str] = []
    major_count = 0
    if result.final_decision != "accept":
        reasons.append("peer_loop_not_converged")
    if result.unresolved_issue_count > 0:
        reasons.append("unresolved_reviewer_issues")
    if compliance.blocked_by_critical:
        reasons.append("critical_compliance_gap")
    if compliance.risk_level == "high":
        reasons.append("high_ethics_risk")

    first_round = result.rounds[0] if result.rounds else None
    if first_round is not None:
        major_count = sum(1 for issue in first_round.reviewer_issues if issue.severity == "major")
        if major_count >= major_issue_threshold:
            reasons.append("high_major_issue_density")
        if result.final_decision == "accept" and len(result.rounds) >= 2:
            # Mine difficult recovered trajectories: severe first-round rebuttal but eventually accepted.
            reasons.append("initial_major_rebuttal_then_accept")
    return reasons, major_count


def run_self_play_training(
    *,
    episodes: list[SelfPlayEpisodeInput],
    max_rounds: int = 3,
    default_venue_name: str = "NeurIPS",
    default_section_id: str | None = "discussion",
    run_name: str = "peer-self-play",
) -> SelfPlayTrainingResult:
    """Run multi-episode self-play and mine hard negatives."""
    if not episodes:
        return SelfPlayTrainingResult(
            run_name=run_name,
            total_episodes=0,
            accepted_episodes=0,
            hard_negative_count=0,
            hard_negative_rate=0.0,
            episodes=[],
            hard_negatives=[],
        )

    episode_results: list[SelfPlayEpisodeResult] = []
    hard_negatives: list[HardNegativeExample] = []
    accepted = 0

    for idx, episode in enumerate(episodes, start=1):
        venue = (episode.venue_name or default_venue_name or "NeurIPS").strip() or "NeurIPS"
        section_id = (episode.section_id if episode.section_id is not None else default_section_id) or None
        episode_id = episode.episode_id or f"episode-{idx:04d}"
        seed_text = episode.manuscript_text.strip()
        result = run_peer_review_loop(
            manuscript_text=seed_text,
            venue_name=venue,
            section_id=section_id,
            max_rounds=max_rounds,
        )
        compliance = audit_scientific_compliance(result.final_text)
        reasons, initial_major_issue_count = _hard_negative_reasons(result, compliance)
        issue_types = _collect_issue_types(result)
        hard_negative = len(reasons) > 0
        if result.final_decision == "accept":
            accepted += 1

        episode_results.append(
            SelfPlayEpisodeResult(
                episode_id=episode_id,
                venue_name=venue,
                section_id=section_id,
                round_count=len(result.rounds),
                initial_major_issue_count=initial_major_issue_count,
                final_decision=result.final_decision,
                unresolved_issue_count=result.unresolved_issue_count,
                issue_types=issue_types,
                compliance_risk_level=compliance.risk_level,
                hard_negative=hard_negative,
                hard_negative_reasons=reasons,
                artifact_summary={
                    "rubric_rounds": len(result.rounds),
                    "compliance_score": compliance.compliance_score,
                },
            )
        )
        if hard_negative:
            hard_negatives.append(
                HardNegativeExample(
                    hard_negative_id=_stable_id("hn", f"{episode_id}:{seed_text}:{result.final_text}"),
                    episode_id=episode_id,
                    venue_name=venue,
                    section_id=section_id,
                    original_text=seed_text,
                    final_text=result.final_text,
                    final_decision=result.final_decision,
                    round_count=len(result.rounds),
                    initial_major_issue_count=initial_major_issue_count,
                    unresolved_issue_count=result.unresolved_issue_count,
                    reasons=reasons,
                    issue_types=issue_types,
                    recommendations=_collect_recommendations(result, compliance),
                )
            )

    hard_negative_count = len(hard_negatives)
    total = len(episodes)
    return SelfPlayTrainingResult(
        run_name=run_name,
        total_episodes=total,
        accepted_episodes=accepted,
        hard_negative_count=hard_negative_count,
        hard_negative_rate=round(hard_negative_count / float(total), 4),
        episodes=episode_results,
        hard_negatives=hard_negatives,
    )

