"""Venue-calibrated reviewer simulation and rebuttal planning."""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.research_writing.project_state import RebuttalAction, ReviewerComment
from src.research_writing.venue_profiles import VenueProfile, get_venue_profile


@dataclass
class ReviewerSimulationResult:
    """Structured simulation result."""

    venue: str
    comments: list[ReviewerComment]
    overall_assessment: str


def _has_keyword(text: str, *keywords: str) -> bool:
    lowered = text.lower()
    return any(k in lowered for k in keywords)


def _estimate_word_count(text: str) -> int:
    return len(re.findall(r"\S+", text))


def _response_category(action: str) -> str:
    if action in {"new_experiment", "new_analysis", "manuscript_revision"}:
        return "Accept & Modify"
    if action == "clarification":
        return "Clarify"
    return "Rebut"


def simulate_reviewer_comments(manuscript_text: str, venue_name: str) -> ReviewerSimulationResult:
    """Generate venue-calibrated reviewer comments from a manuscript draft."""
    profile: VenueProfile = get_venue_profile(venue_name)
    comments: list[ReviewerComment] = []

    wc = _estimate_word_count(manuscript_text)
    if wc < 800:
        comments.append(
            ReviewerComment(
                comment_id="R1",
                reviewer_label="Reviewer 1",
                severity="major",
                content="Manuscript is underdeveloped for the target venue; methods/results detail is insufficient.",
                section_ref="overall",
            )
        )

    if profile.domain == "ai_cs":
        if not _has_keyword(manuscript_text, "ablation"):
            comments.append(
                ReviewerComment(
                    comment_id="R2",
                    reviewer_label="Reviewer 2",
                    severity="major",
                    content="Ablation study is missing; contribution attribution is not yet convincing.",
                    section_ref="experiments",
                )
            )
        if not _has_keyword(manuscript_text, "baseline", "compared to"):
            comments.append(
                ReviewerComment(
                    comment_id="R3",
                    reviewer_label="Reviewer 3",
                    severity="major",
                    content="Baseline comparison is incomplete for venue standards.",
                    section_ref="results",
                )
            )
    else:
        if not _has_keyword(manuscript_text, "control", "controls"):
            comments.append(
                ReviewerComment(
                    comment_id="R2",
                    reviewer_label="Reviewer 2",
                    severity="major",
                    content="Control experiments are insufficiently described.",
                    section_ref="methods",
                )
            )
        if not _has_keyword(manuscript_text, "ethics", "institutional review board", "irb"):
            comments.append(
                ReviewerComment(
                    comment_id="R3",
                    reviewer_label="Reviewer 3",
                    severity="minor",
                    content="Ethics statement is missing or unclear.",
                    section_ref="compliance",
                )
            )

    if not _has_keyword(manuscript_text, "limitation", "limitations"):
        comments.append(
            ReviewerComment(
                comment_id=f"R{len(comments) + 1}",
                reviewer_label="Reviewer 1",
                severity="minor",
                content="Limitations are not clearly discussed.",
                section_ref="discussion",
            )
        )

    if not comments:
        comments.append(
            ReviewerComment(
                comment_id="R1",
                reviewer_label="Reviewer 1",
                severity="minor",
                content="No major blocking issue detected; strengthen novelty positioning and reproducibility details.",
                section_ref="introduction",
            )
        )

    major_count = sum(1 for c in comments if c.severity == "major")
    assessment = "major revision" if major_count >= 2 else "minor revision"
    return ReviewerSimulationResult(venue=venue_name, comments=comments, overall_assessment=assessment)


def build_rebuttal_plan(
    comments: list[ReviewerComment],
    *,
    evidence_map: dict[str, list[str]] | None = None,
    section_map: dict[str, list[str]] | None = None,
) -> list[RebuttalAction]:
    """Create structured rebuttal actions linked to reviewer comments."""
    evidence_map = evidence_map or {}
    section_map = section_map or {}

    actions: list[RebuttalAction] = []
    for comment in comments:
        lowered = comment.content.lower()
        if any(token in lowered for token in ("ablation", "baseline", "control", "experiment")):
            action = "new_experiment"
        elif any(token in lowered for token in ("unclear", "clarify", "missing statement")):
            action = "clarification"
        elif any(token in lowered for token in ("incorrect", "misinterpret", "disagree", "not supported")):
            action = "decline_with_rationale"
        elif any(token in lowered for token in ("insufficient", "underdeveloped", "incomplete")):
            action = "new_analysis"
        else:
            action = "manuscript_revision"
        response_category = _response_category(action)
        if response_category == "Accept & Modify":
            rebuttal_text = "Accept & Modify: revise manuscript artifacts (code/statistics/figures) and update linked evidence."
        elif response_category == "Clarify":
            rebuttal_text = "Clarify: tighten wording, add caveats, and improve traceability for the cited section."
        else:
            rebuttal_text = "Rebut: provide strong counter-evidence/citations and justify why the reviewer assumption does not hold."

        actions.append(
            RebuttalAction(
                comment_id=comment.comment_id,
                action=action,
                status="planned",
                evidence_ids=evidence_map.get(comment.comment_id, []),
                section_ids=section_map.get(comment.comment_id, [comment.section_ref] if comment.section_ref else []),
                rebuttal_text=f"{rebuttal_text} (comment={comment.comment_id})",
            )
        )
    return actions


def render_rebuttal_letter(comments: list[ReviewerComment], actions: list[RebuttalAction]) -> str:
    """Render a point-by-point rebuttal draft."""
    action_by_comment = {a.comment_id: a for a in actions}
    lines = ["# Response to Reviewers", "", "We thank the reviewers for their constructive feedback.", ""]
    for idx, comment in enumerate(comments, start=1):
        action = action_by_comment.get(comment.comment_id)
        lines.extend(
            [
                f"## Comment {idx} ({comment.reviewer_label})",
                f"> {comment.content}",
                "",
                f"**Response plan:** {action.action if action else 'manuscript_revision'}",
                f"**Response category:** {_response_category(action.action if action else 'manuscript_revision')}",
                f"**Linked sections:** {', '.join(action.section_ids) if action and action.section_ids else 'N/A'}",
                f"**Linked evidence:** {', '.join(action.evidence_ids) if action and action.evidence_ids else 'N/A'}",
                f"**Execution note:** {action.rebuttal_text if action else 'Pending response detail.'}",
                "",
            ]
        )
    return "\n".join(lines).strip()
