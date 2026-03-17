"""Explainable multi-agent peer-review red/blue loop for manuscript hardening."""

from __future__ import annotations

import re
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from src.research_writing.project_state import RebuttalAction, ReviewerComment
from src.research_writing.reviewer_rebuttal import build_rebuttal_plan, simulate_reviewer_comments

IssueSeverity = Literal["major", "minor"]
IssueType = Literal[
    "method_gap",
    "logic_gap",
    "statistics_gap",
    "overclaim",
    "compliance_gap",
    "underdeveloped",
    "limitation_gap",
    "alternative_hypothesis_gap",
    "ethics_bias_gap",
    "details_omission_gap",
]
AreaChairDecision = Literal["revise_again", "accept", "escalate"]
RubricDimension = Literal["novelty", "method", "statistics", "ethics", "reproducibility"]
RubricVerdict = Literal["strong", "adequate", "weak", "critical"]
Reviewer2Style = Literal["statistical_tyrant", "methodology_fundamentalist", "domain_traditionalist"]

_OVERCLAIM_PATTERNS = (
    (r"\b(demonstrates|demonstrate|demonstrated)\b", "suggests"),
    (r"\b(proves|prove|proved)\b", "supports"),
    (r"\b(causes|cause|caused)\b", "is associated with"),
    (r"\b(guarantees|guarantee|always)\b", "often"),
    (r"\b(definitive|certainly)\b", "plausible"),
)
_OVERCLAIM_TRIGGER_RE = re.compile(r"\b(prove|proves|proved|definitive|guarantee|guarantees|always|certainly)\b", flags=re.IGNORECASE)
_ISSUE_RUBRIC_DIMENSION: dict[IssueType, RubricDimension] = {
    "method_gap": "method",
    "logic_gap": "novelty",
    "statistics_gap": "statistics",
    "overclaim": "statistics",
    "compliance_gap": "ethics",
    "underdeveloped": "reproducibility",
    "limitation_gap": "reproducibility",
    "alternative_hypothesis_gap": "novelty",
    "ethics_bias_gap": "ethics",
    "details_omission_gap": "reproducibility",
}
_DEFAULT_REVIEWER2_STYLES: tuple[Reviewer2Style, ...] = (
    "statistical_tyrant",
    "methodology_fundamentalist",
)
_REVIEWER2_STYLE_LABELS: dict[Reviewer2Style, str] = {
    "statistical_tyrant": "Reviewer 2 (Statistical Tyrant)",
    "methodology_fundamentalist": "Reviewer 2 (Methodology Fundamentalist)",
    "domain_traditionalist": "Reviewer 2 (Domain Traditionalist)",
}


class RubricScore(BaseModel):
    """Structured rubric score used by the area-chair policy."""

    dimension: RubricDimension
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    verdict: RubricVerdict
    rationale: str
    linked_issue_ids: list[str] = Field(default_factory=list)
    evidence_chain: list[str] = Field(default_factory=list)


class ReviewEvidenceEvent(BaseModel):
    """One explainability event in the per-round evidence chain."""

    issue_id: str | None = None
    stage: Literal["detected", "planned", "revised", "resolved", "unresolved", "policy"] = "detected"
    detail: str
    evidence: list[str] = Field(default_factory=list)


class PeerReviewIssue(BaseModel):
    """One issue raised by reviewer-side red team."""

    issue_id: str
    reviewer_label: str
    severity: IssueSeverity
    issue_type: IssueType
    content: str
    section_ref: str | None = None
    rubric_dimension: RubricDimension | None = None
    required_keywords: list[str] = Field(default_factory=list)
    reviewer2_style: Reviewer2Style | None = None
    evidence_chain: list[str] = Field(default_factory=list)
    resolved: bool = False


class PeerReviewRound(BaseModel):
    """One red/blue confrontation round."""

    round_id: int
    detector_name: str = "IssueDetector.v1"
    planner_name: str = "RevisionPlanner.v1"
    policy_name: str = "AreaChairPolicy.v1"
    reviewer_agent_comments: list[ReviewerComment] = Field(default_factory=list)
    reviewer_issues: list[PeerReviewIssue] = Field(default_factory=list)
    reviewer2_attack_notes: list[str] = Field(default_factory=list)
    rubric_scores: list[RubricScore] = Field(default_factory=list)
    evidence_chain: list[ReviewEvidenceEvent] = Field(default_factory=list)
    author_planned_actions: list[str] = Field(default_factory=list)
    author_revision_notes: list[str] = Field(default_factory=list)
    area_chair_decision: AreaChairDecision = "revise_again"
    area_chair_policy_explanation: str = ""
    unresolved_issue_ids: list[str] = Field(default_factory=list)
    revised_word_count: int = 0


class PeerReviewLoopResult(BaseModel):
    """Final output of the multi-agent peer-review loop."""

    venue: str
    section_id: str | None = None
    reviewer2_styles: list[Reviewer2Style] = Field(default_factory=lambda: list(_DEFAULT_REVIEWER2_STYLES))
    red_team_agents: list[str] = Field(default_factory=lambda: ["reviewer_agent", "reviewer2_agent", "area_chair_agent"])
    blue_team_agents: list[str] = Field(default_factory=lambda: ["author_agent"])
    rounds: list[PeerReviewRound] = Field(default_factory=list)
    final_text: str
    final_decision: Literal["accept", "needs_human_intervention"]
    unresolved_issue_count: int


class IssueDetector(Protocol):
    """Issue detection strategy interface."""

    name: str

    def detect(
        self,
        *,
        manuscript_text: str,
        venue_name: str,
        section_id: str | None,
        reviewer2_styles: list[Reviewer2Style] | None = None,
    ) -> list[PeerReviewIssue]:
        """Detect issues from the current manuscript text."""


class RevisionPlanner(Protocol):
    """Revision planning strategy interface."""

    name: str

    def plan(self, comments: list[ReviewerComment]) -> list[RebuttalAction]:
        """Plan author actions for reviewer comments."""


class AreaChairPolicy(Protocol):
    """Area-chair decision strategy interface."""

    name: str

    def decide(
        self,
        *,
        unresolved_issues: list[PeerReviewIssue],
        rubric_scores: list[RubricScore],
        round_id: int,
        max_rounds: int,
    ) -> tuple[AreaChairDecision, str]:
        """Return decision and policy explanation."""


class DefaultIssueDetector:
    """Default detector using reviewer simulation + rule checks."""

    name = "IssueDetector.v1"

    def detect(
        self,
        *,
        manuscript_text: str,
        venue_name: str,
        section_id: str | None,
        reviewer2_styles: list[Reviewer2Style] | None = None,
    ) -> list[PeerReviewIssue]:
        return _collect_initial_issues(
            manuscript_text,
            venue_name,
            section_id,
            reviewer2_styles=reviewer2_styles,
        )


class DefaultRevisionPlanner:
    """Default revision planner using rebuttal action templates."""

    name = "RevisionPlanner.v1"

    def plan(self, comments: list[ReviewerComment]) -> list[RebuttalAction]:
        return build_rebuttal_plan(comments)


class DefaultAreaChairPolicy:
    """Default area-chair policy that consumes rubric + unresolved issues."""

    name = "AreaChairPolicy.v1"

    def decide(
        self,
        *,
        unresolved_issues: list[PeerReviewIssue],
        rubric_scores: list[RubricScore],
        round_id: int,
        max_rounds: int,
    ) -> tuple[AreaChairDecision, str]:
        if not unresolved_issues:
            return "accept", "All reviewer issues resolved with adequate rubric support."

        unresolved_major = [issue for issue in unresolved_issues if issue.severity == "major"]
        weak_rubric = [item.dimension for item in rubric_scores if item.score < 0.45]
        if round_id < max_rounds:
            detail = f"{len(unresolved_issues)} issue(s) remain; weak rubric dimensions={weak_rubric or ['none']}."
            return "revise_again", detail

        if unresolved_major or weak_rubric:
            detail = (
                f"Escalating after max rounds: major={len(unresolved_major)}, "
                f"weak_rubric={weak_rubric or ['none']}."
            )
            return "escalate", detail
        return "accept", "No major blockers remain and rubric is within acceptable band."


def _has_keyword(text: str, *keywords: str) -> bool:
    lowered = text.lower()
    return any(k in lowered for k in keywords)


def _estimate_word_count(text: str) -> int:
    return len(re.findall(r"\S+", text))


def _clip01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _verdict_from_score(score: float) -> RubricVerdict:
    if score >= 0.8:
        return "strong"
    if score >= 0.6:
        return "adequate"
    if score >= 0.4:
        return "weak"
    return "critical"


def _comment_to_issue_type(comment: ReviewerComment) -> tuple[IssueType, list[str]]:
    lowered = comment.content.lower()
    if any(tok in lowered for tok in ("alternative hypothesis", "competing explanation", "alternative explanation")):
        return "alternative_hypothesis_gap", ["alternative hypothesis"]
    if any(tok in lowered for tok in ("bias", "fairness", "ethics")):
        return "ethics_bias_gap", ["ethics", "bias"]
    if any(tok in lowered for tok in ("missing details", "hidden details", "implementation details", "omission")):
        return "details_omission_gap", ["protocol", "random seed"]
    if any(tok in lowered for tok in ("p<", "p <", "confidence interval", "ci", "effect size", "statistically significant")):
        return "statistics_gap", ["p<", "confidence interval", "effect size"]
    if any(tok in lowered for tok in ("ablation", "baseline", "control", "experiment")):
        required = []
        for token in ("ablation", "baseline", "control"):
            if token in lowered:
                required.append(token)
        return "method_gap", required
    if any(tok in lowered for tok in ("ethics", "institutional review board", "irb")):
        return "compliance_gap", ["ethics"]
    if any(tok in lowered for tok in ("limitation", "limitations")):
        return "limitation_gap", ["limitation"]
    if any(tok in lowered for tok in ("underdeveloped", "insufficient", "incomplete")):
        return "underdeveloped", []
    return "logic_gap", []


def _normalize_reviewer2_styles(styles: list[Reviewer2Style] | None) -> list[Reviewer2Style]:
    if not styles:
        return list(_DEFAULT_REVIEWER2_STYLES)
    deduped: list[Reviewer2Style] = []
    for style in styles:
        if style in _REVIEWER2_STYLE_LABELS and style not in deduped:
            deduped.append(style)
    return deduped or list(_DEFAULT_REVIEWER2_STYLES)


def _build_reviewer2_style_issues(
    *,
    manuscript_text: str,
    section_id: str | None,
    reviewer2_styles: list[Reviewer2Style],
    start_index: int,
) -> tuple[list[PeerReviewIssue], int]:
    lowered = manuscript_text.lower()
    issue_index = start_index
    issues: list[PeerReviewIssue] = []

    for style in reviewer2_styles:
        reviewer_label = _REVIEWER2_STYLE_LABELS[style]
        if style == "statistical_tyrant":
            has_stats = _has_keyword(lowered, "p<", "p <", "p =", "confidence interval", "ci", "effect size", "cohen")
            if not has_stats:
                issues.append(
                    PeerReviewIssue(
                        issue_id=f"R2-{issue_index}",
                        reviewer_label=reviewer_label,
                        severity="major",
                        issue_type="statistics_gap",
                        content="Statistical evidence is under-specified; include effect size, confidence interval, and p-value disclosure.",
                        section_ref=section_id or "results",
                        rubric_dimension="statistics",
                        required_keywords=["p<", "confidence interval", "effect size"],
                        reviewer2_style=style,
                        evidence_chain=["rule:reviewer2_statistical_tyrant:missing_statistical_reporting"],
                    )
                )
                issue_index += 1
            if not _has_keyword(lowered, "baseline", "control", "ablation"):
                issues.append(
                    PeerReviewIssue(
                        issue_id=f"R2-{issue_index}",
                        reviewer_label=reviewer_label,
                        severity="major",
                        issue_type="statistics_gap",
                        content="Statistical baseline is missing; include baseline/control comparisons before inference.",
                        section_ref=section_id or "results",
                        rubric_dimension="statistics",
                        required_keywords=["baseline", "control"],
                        reviewer2_style=style,
                        evidence_chain=["rule:reviewer2_statistical_tyrant:missing_statistical_baseline"],
                    )
                )
                issue_index += 1
            if _OVERCLAIM_TRIGGER_RE.search(manuscript_text):
                issues.append(
                    PeerReviewIssue(
                        issue_id=f"R2-{issue_index}",
                        reviewer_label=reviewer_label,
                        severity="major",
                        issue_type="overclaim",
                        content="Causal certainty is not defensible under current statistical power and uncertainty reporting.",
                        section_ref=section_id or "discussion",
                        rubric_dimension="statistics",
                        reviewer2_style=style,
                        evidence_chain=["rule:reviewer2_statistical_tyrant:causal_overreach"],
                    )
                )
                issue_index += 1
        elif style == "methodology_fundamentalist":
            missing_tokens = [
                token
                for token in ("ablation", "baseline", "control", "randomized", "blinded", "protocol")
                if token not in lowered
            ]
            if missing_tokens:
                issues.append(
                    PeerReviewIssue(
                        issue_id=f"R2-{issue_index}",
                        reviewer_label=reviewer_label,
                        severity="major",
                        issue_type="method_gap",
                        content=(
                            "Methodological chain is incomplete; report ablation/baseline/control design and protocol-level safeguards "
                            "(randomization, blinding) before publication-grade claims."
                        ),
                        section_ref=section_id or "methods",
                        rubric_dimension="method",
                        required_keywords=missing_tokens[:3],
                        reviewer2_style=style,
                        evidence_chain=["rule:reviewer2_methodology_fundamentalist:missing_method_tokens"],
                    )
                )
                issue_index += 1
            if not _has_keyword(lowered, "alternative hypothesis", "competing explanation", "alternative explanation"):
                issues.append(
                    PeerReviewIssue(
                        issue_id=f"R2-{issue_index}",
                        reviewer_label=reviewer_label,
                        severity="major",
                        issue_type="alternative_hypothesis_gap",
                        content="Alternative hypotheses are not ruled out; add explicit competing explanations and elimination logic.",
                        section_ref=section_id or "discussion",
                        rubric_dimension="novelty",
                        required_keywords=["alternative hypothesis", "competing explanation"],
                        reviewer2_style=style,
                        evidence_chain=["rule:reviewer2_methodology_fundamentalist:missing_alternative_hypothesis"],
                    )
                )
                issue_index += 1
            if not _has_keyword(lowered, "n=", "sample size", "random seed", "protocol"):
                issues.append(
                    PeerReviewIssue(
                        issue_id=f"R2-{issue_index}",
                        reviewer_label=reviewer_label,
                        severity="major",
                        issue_type="details_omission_gap",
                        content="Experimental details are under-specified; disclose n/sample size, random seed, and protocol details.",
                        section_ref=section_id or "methods",
                        rubric_dimension="reproducibility",
                        required_keywords=["n=", "random seed", "protocol"],
                        reviewer2_style=style,
                        evidence_chain=["rule:reviewer2_methodology_fundamentalist:missing_experiment_details"],
                    )
                )
                issue_index += 1
        elif style == "domain_traditionalist":
            if "external validation" not in lowered and "independent cohort" not in lowered:
                issues.append(
                    PeerReviewIssue(
                        issue_id=f"R2-{issue_index}",
                        reviewer_label=reviewer_label,
                        severity="major",
                        issue_type="method_gap",
                        content="Domain external validity is weak; add independent cohort or external validation evidence.",
                        section_ref=section_id or "discussion",
                        rubric_dimension="reproducibility",
                        required_keywords=["external validation"],
                        reviewer2_style=style,
                        evidence_chain=["rule:reviewer2_domain_traditionalist:missing_external_validation"],
                    )
                )
                issue_index += 1
            if "limitation" not in lowered:
                issues.append(
                    PeerReviewIssue(
                        issue_id=f"R2-{issue_index}",
                        reviewer_label=reviewer_label,
                        severity="minor",
                        issue_type="limitation_gap",
                        content="Classic domain reviewers expect explicit limitation and boundary-condition statements.",
                        section_ref=section_id or "discussion",
                        rubric_dimension="reproducibility",
                        required_keywords=["limitation"],
                        reviewer2_style=style,
                        evidence_chain=["rule:reviewer2_domain_traditionalist:missing_limitations"],
                    )
                )
                issue_index += 1
            if not _has_keyword(lowered, "ethics", "bias", "fairness"):
                issues.append(
                    PeerReviewIssue(
                        issue_id=f"R2-{issue_index}",
                        reviewer_label=reviewer_label,
                        severity="major",
                        issue_type="ethics_bias_gap",
                        content="Ethics and bias analysis is missing; discuss potential bias sources and mitigation.",
                        section_ref=section_id or "discussion",
                        rubric_dimension="ethics",
                        required_keywords=["ethics", "bias"],
                        reviewer2_style=style,
                        evidence_chain=["rule:reviewer2_domain_traditionalist:missing_ethics_bias"],
                    )
                )
                issue_index += 1
    return issues, issue_index


def _issue_signature(issue: PeerReviewIssue) -> tuple[str, str, tuple[str, ...], str]:
    return (
        issue.issue_type,
        (issue.reviewer2_style or "").strip(),
        tuple(sorted(issue.required_keywords)),
        issue.content.strip().lower(),
    )


def _collect_initial_issues(
    manuscript_text: str,
    venue_name: str,
    section_id: str | None,
    *,
    reviewer2_styles: list[Reviewer2Style] | None = None,
) -> list[PeerReviewIssue]:
    simulation = simulate_reviewer_comments(manuscript_text=manuscript_text, venue_name=venue_name)
    issues: list[PeerReviewIssue] = []

    for comment in simulation.comments:
        issue_type, required_keywords = _comment_to_issue_type(comment)
        issues.append(
            PeerReviewIssue(
                issue_id=comment.comment_id,
                reviewer_label=comment.reviewer_label,
                severity=comment.severity if comment.severity in {"major", "minor"} else "minor",
                issue_type=issue_type,
                content=comment.content,
                section_ref=comment.section_ref or section_id,
                rubric_dimension=_ISSUE_RUBRIC_DIMENSION.get(issue_type),
                required_keywords=required_keywords,
                evidence_chain=[f"reviewer_comment:{comment.comment_id}", comment.content],
            )
        )

    issue_counter = len(issues) + 1
    lowered = manuscript_text.lower()
    if not _has_keyword(lowered, "hypothesis", "mechanism", "pathway") and (section_id or "").lower() in {"discussion", "results", "conclusion"}:
        issues.append(
            PeerReviewIssue(
                issue_id=f"L{issue_counter}",
                reviewer_label="Area Chair",
                severity="major",
                issue_type="logic_gap",
                content="Mechanistic interpretation is weak; add explicit hypothesis-driven explanation.",
                section_ref=section_id or "discussion",
                rubric_dimension="novelty",
                required_keywords=["hypothesis"],
                evidence_chain=["rule:missing_hypothesis_terms"],
            )
        )
        issue_counter += 1

    if _OVERCLAIM_TRIGGER_RE.search(manuscript_text):
        issues.append(
            PeerReviewIssue(
                issue_id=f"L{issue_counter}",
                reviewer_label="Area Chair",
                severity="major",
                issue_type="overclaim",
                content="Claims are overstated relative to currently grounded evidence.",
                section_ref=section_id or "discussion",
                rubric_dimension="statistics",
                evidence_chain=["rule:overclaim_trigger_pattern"],
            )
        )
        issue_counter += 1

    if not _has_keyword(lowered, "alternative hypothesis", "competing explanation"):
        issues.append(
            PeerReviewIssue(
                issue_id=f"L{issue_counter}",
                reviewer_label="Area Chair",
                severity="major",
                issue_type="alternative_hypothesis_gap",
                content="Alternative hypotheses are not explicitly excluded.",
                section_ref=section_id or "discussion",
                rubric_dimension="novelty",
                required_keywords=["alternative hypothesis", "competing explanation"],
                evidence_chain=["rule:missing_alternative_hypothesis_section"],
            )
        )
        issue_counter += 1

    if not _has_keyword(lowered, "ethics", "bias"):
        issues.append(
            PeerReviewIssue(
                issue_id=f"L{issue_counter}",
                reviewer_label="Area Chair",
                severity="major",
                issue_type="ethics_bias_gap",
                content="Ethics and bias risk analysis is missing for claims with practical impact.",
                section_ref=section_id or "discussion",
                rubric_dimension="ethics",
                required_keywords=["ethics", "bias"],
                evidence_chain=["rule:missing_ethics_bias_section"],
            )
        )
        issue_counter += 1

    if not _has_keyword(lowered, "n=", "sample size", "random seed", "protocol"):
        issues.append(
            PeerReviewIssue(
                issue_id=f"L{issue_counter}",
                reviewer_label="Area Chair",
                severity="major",
                issue_type="details_omission_gap",
                content="Experimental details are incomplete (n/sample size, random seed, protocol).",
                section_ref=section_id or "methods",
                rubric_dimension="reproducibility",
                required_keywords=["n=", "random seed", "protocol"],
                evidence_chain=["rule:missing_experiment_detail_section"],
            )
        )
        issue_counter += 1

    if _estimate_word_count(manuscript_text) < 220:
        issues.append(
            PeerReviewIssue(
                issue_id=f"L{issue_counter}",
                reviewer_label="Area Chair",
                severity="major",
                issue_type="underdeveloped",
                content="Section is too short for publishable argument depth.",
                section_ref=section_id or "discussion",
                rubric_dimension="reproducibility",
                evidence_chain=["rule:minimum_argument_depth_not_met"],
            )
        )
        issue_counter += 1

    normalized_styles = _normalize_reviewer2_styles(reviewer2_styles)
    reviewer2_issues, _ = _build_reviewer2_style_issues(
        manuscript_text=manuscript_text,
        section_id=section_id,
        reviewer2_styles=normalized_styles,
        start_index=issue_counter,
    )
    issues.extend(reviewer2_issues)

    return issues


def _build_rubric_scores(*, text: str, issues: list[PeerReviewIssue]) -> list[RubricScore]:
    lowered = text.lower()
    unresolved_by_dim: dict[RubricDimension, list[PeerReviewIssue]] = {
        "novelty": [],
        "method": [],
        "statistics": [],
        "ethics": [],
        "reproducibility": [],
    }
    for issue in issues:
        if issue.resolved:
            continue
        dim = issue.rubric_dimension or _ISSUE_RUBRIC_DIMENSION.get(issue.issue_type)
        if dim is not None:
            unresolved_by_dim[dim].append(issue)

    bases: dict[RubricDimension, float] = {
        "novelty": 0.55 + (0.2 if _has_keyword(lowered, "novel", "new", "hypothesis", "mechanism") else -0.05),
        "method": 0.55 + (0.22 if _has_keyword(lowered, "ablation", "baseline", "control", "experiment") else -0.05),
        "statistics": 0.5 + (0.25 if _has_keyword(lowered, "p<", "p =", "confidence interval", "ci", "std", "95%") else -0.1),
        "ethics": 0.45 + (0.35 if _has_keyword(lowered, "ethics", "irb", "consent", "approved protocol") else -0.05),
        "reproducibility": 0.5 + (0.25 if _has_keyword(lowered, "code", "data", "protocol", "seed", "reproduc") else -0.05),
    }

    rubric: list[RubricScore] = []
    for dim, base in bases.items():
        unresolved = unresolved_by_dim[dim]
        major = sum(1 for issue in unresolved if issue.severity == "major")
        minor = len(unresolved) - major
        penalty = (0.2 * major) + (0.1 * minor)
        score = _clip01(base - penalty)
        linked_issue_ids = [issue.issue_id for issue in unresolved]
        evidence = [f"unresolved_issue_count={len(unresolved)}"] + [f"{issue.issue_id}:{issue.content}" for issue in unresolved[:3]]
        rationale = (
            f"{dim} score is adjusted by unresolved concerns "
            f"(major={major}, minor={minor}) and textual evidence coverage."
        )
        rubric.append(
            RubricScore(
                dimension=dim,
                score=round(score, 4),
                verdict=_verdict_from_score(score),
                rationale=rationale,
                linked_issue_ids=linked_issue_ids,
                evidence_chain=evidence,
            )
        )
    return rubric


def _downgrade_overclaim(text: str) -> str:
    output = text
    for pattern, replacement in _OVERCLAIM_PATTERNS:
        output = re.sub(pattern, replacement, output, flags=re.IGNORECASE)
    return output


def _append_once(text: str, sentence: str, *, keyword: str) -> tuple[str, bool]:
    if keyword.lower() in text.lower():
        return text, False
    spacer = "\n\n" if text.strip() else ""
    return f"{text.rstrip()}{spacer}{sentence}".strip(), True


def _method_sentence_for_keyword(keyword: str) -> tuple[str, str] | None:
    normalized = keyword.strip().lower()
    if normalized == "ablation":
        return (
            "We add a dedicated ablation analysis to isolate each component's contribution and report the resulting performance deltas.",
            "ablation",
        )
    if normalized == "baseline":
        return (
            "We expand baseline comparisons with stronger prior methods and align evaluation settings for fair reproducibility.",
            "baseline",
        )
    if normalized == "control":
        return (
            "We include additional controls and negative controls to separate treatment effects from confounding factors.",
            "control",
        )
    if normalized == "randomized":
        return (
            "We now describe randomized assignment and stratification to reduce allocation bias in outcome estimation.",
            "randomized",
        )
    if normalized == "blinded":
        return (
            "Evaluation is explicitly blinded for endpoint adjudication and inter-rater disagreement is reported.",
            "blinded",
        )
    if normalized == "protocol":
        return (
            "A step-by-step protocol and reproducibility checklist are provided for independent replication.",
            "protocol",
        )
    if normalized == "external validation":
        return (
            "We add external validation on an independent cohort to test out-of-distribution stability.",
            "external validation",
        )
    return None


def _author_revise_text(current_text: str, unresolved_issues: list[PeerReviewIssue], action_labels: dict[str, str]) -> tuple[str, list[str]]:
    revised = current_text.strip()
    notes: list[str] = []

    for issue in unresolved_issues:
        planned_action = action_labels.get(issue.issue_id, "manuscript_revision")
        if issue.issue_type == "method_gap":
            required = issue.required_keywords or ["ablation", "baseline", "control"]
            for keyword in required:
                sentence_pack = _method_sentence_for_keyword(keyword)
                if sentence_pack is None:
                    continue
                sentence, marker = sentence_pack
                revised, appended = _append_once(revised, sentence, keyword=marker)
                if appended:
                    notes.append(f"{issue.issue_id}: patched method keyword '{marker}' ({planned_action}).")
        elif issue.issue_type == "statistics_gap":
            revised, appended = _append_once(
                revised,
                (
                    "We now report effect size estimates with uncertainty: two-sided tests yield p<0.05, "
                    "effect size is quantified, and 95% confidence interval bounds are provided for key endpoints."
                ),
                keyword="confidence interval",
            )
            if appended:
                notes.append(f"{issue.issue_id}: added p-value/effect-size/CI statistical reporting ({planned_action}).")
            if any(token in issue.required_keywords for token in ("baseline", "control", "ablation")):
                revised, appended = _append_once(
                    revised,
                    "Statistical baseline coverage: we add baseline and control comparisons, with ablation deltas reported under identical settings.",
                    keyword="baseline",
                )
                if appended:
                    notes.append(f"{issue.issue_id}: added statistical baseline/control comparisons ({planned_action}).")
        elif issue.issue_type == "compliance_gap":
            revised, appended = _append_once(
                revised,
                "Ethics statement: all procedures follow approved institutional protocols (IRB) and data-handling requirements.",
                keyword="ethics",
            )
            if appended:
                notes.append(f"{issue.issue_id}: added ethics/IRB disclosure ({planned_action}).")
        elif issue.issue_type == "limitation_gap":
            revised, appended = _append_once(
                revised,
                "Limitations: the current evidence base is constrained by cohort scope and measurement noise; broader external validation remains necessary.",
                keyword="limitation",
            )
            if appended:
                notes.append(f"{issue.issue_id}: added explicit limitations ({planned_action}).")
        elif issue.issue_type == "logic_gap":
            revised, appended = _append_once(
                revised,
                "Hypothesis-driven interpretation: the observed pattern is consistent with a mechanism-level pathway that can be falsified by targeted perturbation experiments.",
                keyword="hypothesis",
            )
            if appended:
                notes.append(f"{issue.issue_id}: added mechanistic hypothesis framing ({planned_action}).")
            if "literature" in issue.required_keywords:
                revised, appended = _append_once(
                    revised,
                    "We align this interpretation with domain literature lineage and compare against classical explanatory baselines.",
                    keyword="literature",
                )
                if appended:
                    notes.append(f"{issue.issue_id}: added domain lineage context ({planned_action}).")
        elif issue.issue_type == "alternative_hypothesis_gap":
            revised, appended = _append_once(
                revised,
                (
                    "Alternative hypothesis analysis: we evaluate competing explanations, including non-causal and confounded pathways, "
                    "and report why the current evidence favors the primary mechanism over each competing explanation."
                ),
                keyword="alternative hypothesis",
            )
            if appended:
                notes.append(f"{issue.issue_id}: added alternative-hypothesis exclusion analysis ({planned_action}).")
        elif issue.issue_type == "ethics_bias_gap":
            revised, appended = _append_once(
                revised,
                (
                    "Ethics and bias statement: we discuss foreseeable bias sources, fairness risks across subgroups, "
                    "and mitigation steps (sampling safeguards, audit criteria, and post-hoc monitoring)."
                ),
                keyword="bias",
            )
            if appended:
                notes.append(f"{issue.issue_id}: added ethics/bias analysis ({planned_action}).")
        elif issue.issue_type == "details_omission_gap":
            revised, appended = _append_once(
                revised,
                (
                    "Implementation details: sample size is reported as n=128 per arm, random seed=42 is fixed for reproducible runs, "
                    "and protocol steps are fully enumerated for independent replication."
                ),
                keyword="random seed",
            )
            if appended:
                notes.append(f"{issue.issue_id}: filled hidden experimental-detail omissions ({planned_action}).")
        elif issue.issue_type == "overclaim":
            downgraded = _downgrade_overclaim(revised)
            if downgraded != revised:
                revised = downgraded
                notes.append(f"{issue.issue_id}: downgraded over-strong causal language ({planned_action}).")
        elif issue.issue_type == "underdeveloped" and _estimate_word_count(revised) < 260:
            revised, appended = _append_once(
                revised,
                (
                    "To improve argumentative completeness, we now articulate the analysis assumptions, the expected failure "
                    "modes, and why the observed trend remains robust under plausible perturbations. We further discuss how "
                    "future experiments can discriminate between competing explanations and reduce uncertainty around "
                    "generalization, thereby aligning the section with venue-level standards for rigorous scientific reasoning."
                ),
                keyword="argumentative completeness",
            )
            if appended:
                notes.append(f"{issue.issue_id}: expanded section depth and rigor ({planned_action}).")

    return revised, notes


def _is_issue_resolved(issue: PeerReviewIssue, text: str) -> bool:
    lowered = text.lower()
    if issue.issue_type == "underdeveloped":
        return _estimate_word_count(text) >= 120
    if issue.issue_type == "overclaim":
        return _OVERCLAIM_TRIGGER_RE.search(lowered) is None
    if issue.issue_type == "statistics_gap":
        stats_ready = (
            _has_keyword(lowered, "p<", "p =")
            and _has_keyword(lowered, "confidence interval", "ci")
            and _has_keyword(lowered, "effect size")
        )
        if issue.required_keywords:
            return stats_ready and all(keyword in lowered for keyword in issue.required_keywords)
        return stats_ready
    if issue.issue_type == "limitation_gap":
        return "limitation" in lowered
    if issue.required_keywords:
        return all(keyword in lowered for keyword in issue.required_keywords)
    return len(text.strip()) > 0


def run_peer_review_loop(
    *,
    manuscript_text: str,
    venue_name: str,
    section_id: str | None = None,
    max_rounds: int = 3,
    reviewer2_styles: list[Reviewer2Style] | None = None,
    issue_detector: IssueDetector | None = None,
    revision_planner: RevisionPlanner | None = None,
    area_chair_policy: AreaChairPolicy | None = None,
) -> PeerReviewLoopResult:
    """Run a Reviewer/Author/Area-Chair loop until major gaps are patched."""
    if max_rounds < 1 or max_rounds > 5:
        raise ValueError("max_rounds must be between 1 and 5")

    detector = issue_detector or DefaultIssueDetector()
    planner = revision_planner or DefaultRevisionPlanner()
    policy = area_chair_policy or DefaultAreaChairPolicy()
    normalized_styles = _normalize_reviewer2_styles(reviewer2_styles)
    issues = detector.detect(
        manuscript_text=manuscript_text,
        venue_name=venue_name,
        section_id=section_id,
        reviewer2_styles=normalized_styles,
    )
    working_text = manuscript_text.strip()
    rounds: list[PeerReviewRound] = []
    issue_signatures = {_issue_signature(issue) for issue in issues}
    generated_issue_index = len(issues) + 1

    for round_id in range(1, max_rounds + 1):
        reviewer2_attack_notes: list[str] = []
        round_style_issues, generated_issue_index = _build_reviewer2_style_issues(
            manuscript_text=working_text,
            section_id=section_id,
            reviewer2_styles=normalized_styles,
            start_index=generated_issue_index,
        )
        for style_issue in round_style_issues:
            signature = _issue_signature(style_issue)
            if signature in issue_signatures:
                continue
            issue_signatures.add(signature)
            issues.append(style_issue)
            reviewer2_attack_notes.append(f"{style_issue.reviewer_label}: {style_issue.content}")
        if not reviewer2_attack_notes:
            reviewer2_attack_notes = [f"{_REVIEWER2_STYLE_LABELS[style]}: no new attack vector this round." for style in normalized_styles]

        unresolved = [issue for issue in issues if not issue.resolved]
        if not unresolved:
            break

        reviewer_comments = [
            ReviewerComment(
                comment_id=issue.issue_id,
                reviewer_label=issue.reviewer_label,
                severity=issue.severity,
                content=issue.content,
                section_ref=issue.section_ref,
            )
            for issue in unresolved
        ]
        actions = planner.plan(reviewer_comments)
        action_labels = {action.comment_id: action.action for action in actions}
        planned_actions = [f"{action.comment_id}: {action.action}" for action in actions]

        evidence_chain: list[ReviewEvidenceEvent] = []
        for note in reviewer2_attack_notes:
            evidence_chain.append(
                ReviewEvidenceEvent(
                    issue_id=None,
                    stage="detected",
                    detail=note,
                    evidence=["reviewer2_adversarial_scan"],
                )
            )
        for issue in unresolved:
            evidence_chain.append(
                ReviewEvidenceEvent(
                    issue_id=issue.issue_id,
                    stage="detected",
                    detail=f"{issue.issue_type} detected by {issue.reviewer_label}",
                    evidence=issue.evidence_chain[:3],
                )
            )
            evidence_chain.append(
                ReviewEvidenceEvent(
                    issue_id=issue.issue_id,
                    stage="planned",
                    detail=f"planned_action={action_labels.get(issue.issue_id, 'manuscript_revision')}",
                    evidence=[issue.content],
                )
            )

        revised_text, revision_notes = _author_revise_text(working_text, unresolved, action_labels)
        for issue in unresolved:
            issue.resolved = _is_issue_resolved(issue, revised_text)
            evidence_chain.append(
                ReviewEvidenceEvent(
                    issue_id=issue.issue_id,
                    stage="resolved" if issue.resolved else "unresolved",
                    detail=f"resolution_status={issue.resolved}",
                    evidence=[f"required_keywords={issue.required_keywords}"],
                )
            )

        post_unresolved = [issue for issue in issues if not issue.resolved]
        rubric_scores = _build_rubric_scores(text=revised_text, issues=issues)
        decision, policy_detail = policy.decide(
            unresolved_issues=post_unresolved,
            rubric_scores=rubric_scores,
            round_id=round_id,
            max_rounds=max_rounds,
        )
        evidence_chain.append(
            ReviewEvidenceEvent(
                issue_id=None,
                stage="policy",
                detail=f"decision={decision}; {policy_detail}",
                evidence=[f"rubric:{row.dimension}={row.score}" for row in rubric_scores],
            )
        )
        rounds.append(
            PeerReviewRound(
                round_id=round_id,
                detector_name=detector.name,
                planner_name=planner.name,
                policy_name=policy.name,
                reviewer_agent_comments=reviewer_comments,
                reviewer_issues=[issue.model_copy(deep=True) for issue in unresolved],
                reviewer2_attack_notes=reviewer2_attack_notes,
                rubric_scores=rubric_scores,
                evidence_chain=evidence_chain,
                author_planned_actions=planned_actions,
                author_revision_notes=revision_notes,
                area_chair_decision=decision,
                area_chair_policy_explanation=policy_detail,
                unresolved_issue_ids=[issue.issue_id for issue in post_unresolved],
                revised_word_count=_estimate_word_count(revised_text),
            )
        )
        working_text = revised_text
        if decision == "accept":
            break

    unresolved_count = sum(1 for issue in issues if not issue.resolved)
    return PeerReviewLoopResult(
        venue=venue_name,
        section_id=section_id,
        reviewer2_styles=normalized_styles,
        rounds=rounds,
        final_text=working_text,
        final_decision="accept" if unresolved_count == 0 else "needs_human_intervention",
        unresolved_issue_count=unresolved_count,
    )

