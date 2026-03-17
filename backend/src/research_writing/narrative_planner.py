"""Narrative planning agent for PI-level scientific storytelling."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from src.research_writing.citation_registry import CitationRecord
from src.research_writing.claim_graph import Claim
from src.research_writing.evidence_store import EvidenceUnit
from src.research_writing.project_state import ResearchProject, SectionDraft


def _dedup_keep_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in values:
        item = str(raw).strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _split_sentences(text: str) -> list[str]:
    if not text.strip():
        return []
    chunks = re.split(r"(?<=[.!?])\s+|\n{2,}", text.strip())
    return [chunk.strip() for chunk in chunks if chunk.strip()]


def _first_sentence(text: str, fallback: str) -> str:
    sentences = _split_sentences(text)
    if sentences:
        return sentences[0].rstrip(".")
    return fallback


class NarrativeSelfQuestion(BaseModel):
    """One self-questioning turn before drafting."""

    round_index: int
    question: str
    answer: str
    anchor_claim_ids: list[str] = Field(default_factory=list)
    anchor_evidence_ids: list[str] = Field(default_factory=list)
    anchor_citation_ids: list[str] = Field(default_factory=list)


class FigureStoryboardFrame(BaseModel):
    """One figure card in storyline planning."""

    figure_id: str
    title: str
    narrative_role: Literal["setup", "conflict", "resolution", "impact"] = "setup"
    objective: str
    linked_claim_ids: list[str] = Field(default_factory=list)
    linked_evidence_ids: list[str] = Field(default_factory=list)
    suggested_plot: str | None = None


class NarrativePlan(BaseModel):
    """Structured narrative planning payload consumed by runtime compile."""

    planner_version: str = "deerflow.narrative_plan.v1"
    project_id: str
    section_id: str
    section_name: str
    takeaway_message: str
    gap_statement: str
    disruption_statement: str
    logical_flow: list[str] = Field(default_factory=list)
    figure_storyboard: list[FigureStoryboardFrame] = Field(default_factory=list)
    self_questioning: list[NarrativeSelfQuestion] = Field(default_factory=list)
    introduction_hook: str
    discussion_pivot: str
    introduction_cars: list[dict[str, str]] = Field(default_factory=list)
    meal_outline: list[dict[str, str]] = Field(default_factory=list)
    discussion_five_layers: list[dict[str, str]] = Field(default_factory=list)


class NarrativePlannerAgent:
    """Builds PI-style narrative strategy before section compilation."""

    _QUESTION_BANK: tuple[str, ...] = (
        "Why does this finding matter now?",
        "Which existing assumption does it challenge?",
        "What is the strongest reviewer objection and how do we answer it with evidence?",
        "If this claim holds, what decisions or experiments should change next?",
        "Is the narrative reproducible from figures and evidence artifacts?",
    )

    @classmethod
    def _pick_primary_claim(cls, claims: list[Claim], section: SectionDraft) -> tuple[str, list[str]]:
        prioritized = [claim for claim in claims if claim.claim_type in {"strong", "result"}]
        if prioritized:
            primary = prioritized[0]
            return primary.text.strip(), [primary.claim_id]
        if claims:
            return claims[0].text.strip(), [claims[0].claim_id]
        fallback = _first_sentence(
            section.content,
            fallback=f"{section.section_name} proposes a testable mechanism-level claim",
        )
        return fallback, []

    @classmethod
    def _build_gap_statement(
        cls,
        *,
        project: ResearchProject,
        primary_claim_text: str,
        graph_threads: list[str],
    ) -> str:
        question = next((item for item in project.research_questions if str(item).strip()), "")
        if graph_threads:
            return f"Literature graph shows unresolved conflict: {graph_threads[0]}; this gap remains unintegrated."
        if question:
            return f"Primary research gap: {question.strip()}."
        return f"Current work still lacks a closed evidence chain around the core claim '{primary_claim_text}'."

    @classmethod
    def _build_disruption_statement(cls, *, primary_claim_text: str, graph_threads: list[str]) -> str:
        if graph_threads:
            return f"This study reframes prior knowledge via support-refute-reconcile synthesis and centers debate on '{primary_claim_text}'."
        return f"This study shifts discussion from correlation-level description to a falsifiable mechanism claim: {primary_claim_text}."

    @classmethod
    def _build_logical_flow(
        cls,
        *,
        gap_statement: str,
        section: SectionDraft,
        primary_claim_text: str,
        evidence_count: int,
        citation_count: int,
    ) -> list[str]:
        flow = [
            f"Problem and gap: {gap_statement}",
            f"Method and evidence: organize {evidence_count} evidence units and {citation_count} citations in section '{section.section_name}'.",
            f"Core finding: {primary_claim_text}",
            "Impact and boundary: state applicability limits and next-step validation experiments.",
        ]
        return flow

    @classmethod
    def _build_storyboard(
        cls,
        *,
        section: SectionDraft,
        primary_claim_text: str,
        gap_statement: str,
        disruption_statement: str,
        claim_ids: list[str],
        evidence_ids: list[str],
        include_storyboard: bool,
    ) -> list[FigureStoryboardFrame]:
        if not include_storyboard:
            return []
        selected_evidence = evidence_ids[:6]
        frames = [
            FigureStoryboardFrame(
                figure_id="F1",
                title="Problem framing and gap",
                narrative_role="setup",
                objective=gap_statement,
                linked_claim_ids=claim_ids,
                linked_evidence_ids=selected_evidence[:2],
                suggested_plot="concept-map",
            ),
            FigureStoryboardFrame(
                figure_id="F2",
                title="Evidence conflict and competing interpretations",
                narrative_role="conflict",
                objective="Show literature support and refutation paths and mark critical dispute nodes.",
                linked_claim_ids=claim_ids,
                linked_evidence_ids=selected_evidence[2:4],
                suggested_plot="graph-network",
            ),
            FigureStoryboardFrame(
                figure_id="F3",
                title="Core result and mechanistic reconciliation",
                narrative_role="resolution",
                objective=disruption_statement,
                linked_claim_ids=claim_ids,
                linked_evidence_ids=selected_evidence[4:6],
                suggested_plot="multi-panel-figure",
            ),
            FigureStoryboardFrame(
                figure_id="F4",
                title="Translational impact and reproducibility path",
                narrative_role="impact",
                objective=f"Translate '{primary_claim_text}' into follow-up experiments and a reproducibility checklist.",
                linked_claim_ids=claim_ids,
                linked_evidence_ids=selected_evidence,
                suggested_plot="roadmap",
            ),
        ]
        return frames

    @classmethod
    def _build_introduction_cars(
        cls,
        *,
        section_name: str,
        gap_statement: str,
        disruption_statement: str,
        primary_claim_text: str,
    ) -> list[dict[str, str]]:
        return [
            {
                "move": "Move 1: Establish Territory",
                "objective": "Explain why the topic matters now.",
                "statement": f"In {section_name}, the field-level territory is the unresolved scientific importance of '{primary_claim_text}'.",
            },
            {
                "move": "Move 2: Establish Niche",
                "objective": "Expose conflict or evidence gap.",
                "statement": gap_statement,
            },
            {
                "move": "Move 3: Occupy Niche",
                "objective": "Position this work as a concrete response.",
                "statement": disruption_statement,
            },
        ]

    @classmethod
    def _build_meal_outline(
        cls,
        *,
        logical_flow: list[str],
        evidence_count: int,
        citation_count: int,
    ) -> list[dict[str, str]]:
        if not logical_flow:
            logical_flow = ["State one testable main point and connect it to grounded evidence."]
        units: list[dict[str, str]] = []
        for index, flow_item in enumerate(logical_flow, start=1):
            units.append(
                {
                    "paragraph": f"P{index}",
                    "main_point": flow_item,
                    "evidence": f"Anchor with data/citation bindings (available: {evidence_count} evidence units, {citation_count} citations).",
                    "analysis": "Interpret support/refute tension and explicitly calibrate uncertainty.",
                    "link": "Bridge to next paragraph with a falsifiable next-step or boundary condition.",
                }
            )
        return units

    @classmethod
    def _build_discussion_five_layers(
        cls,
        *,
        primary_claim_text: str,
        disruption_statement: str,
    ) -> list[dict[str, str]]:
        return [
            {
                "layer": "Findings",
                "statement": f"Summarize the highest-confidence finding: {primary_claim_text}.",
            },
            {
                "layer": "Mechanisms",
                "statement": "Explain candidate mechanism chain and identify unresolved confounders.",
            },
            {
                "layer": "Theory",
                "statement": disruption_statement,
            },
            {
                "layer": "Practice",
                "statement": "Translate findings into concrete decision or experimental protocol changes.",
            },
            {
                "layer": "Limitations",
                "statement": "State boundary conditions, failure modes, and what evidence is still missing.",
            },
        ]

    @classmethod
    def _build_self_questioning(
        cls,
        *,
        rounds: int,
        claim_ids: list[str],
        evidence_ids: list[str],
        citation_ids: list[str],
        gap_statement: str,
        disruption_statement: str,
        primary_claim_text: str,
        logical_flow: list[str],
    ) -> list[NarrativeSelfQuestion]:
        bounded_rounds = max(1, min(rounds, 8))
        questions = list(cls._QUESTION_BANK)
        turns: list[NarrativeSelfQuestion] = []
        for idx in range(bounded_rounds):
            question = questions[idx % len(questions)]
            if idx == 0:
                answer = f"It directly closes the key gap: {gap_statement}"
            elif idx == 1:
                answer = disruption_statement
            elif idx == 2:
                answer = (
                    "The strongest response is a closed evidence chain: "
                    f"{len(evidence_ids)} evidence units + {len(citation_ids)} citations around '{primary_claim_text}'."
                )
            else:
                pivot = logical_flow[min(idx, len(logical_flow) - 1)]
                answer = f"Use '{pivot}' to turn the result into a reproducible and reviewable storyline."
            turns.append(
                NarrativeSelfQuestion(
                    round_index=idx + 1,
                    question=question,
                    answer=answer,
                    anchor_claim_ids=claim_ids,
                    anchor_evidence_ids=evidence_ids[:8],
                    anchor_citation_ids=citation_ids[:8],
                )
            )
        return turns

    @classmethod
    def plan(
        cls,
        *,
        project: ResearchProject,
        section: SectionDraft,
        claims: list[Claim],
        evidence_units: list[EvidenceUnit],
        citations: list[CitationRecord],
        self_question_rounds: int = 3,
        include_storyboard: bool = True,
    ) -> NarrativePlan:
        primary_claim_text, claim_ids = cls._pick_primary_claim(claims, section)
        evidence_ids = _dedup_keep_order([unit.evidence_id for unit in evidence_units if unit.evidence_id])
        citation_ids = _dedup_keep_order([item.citation_id for item in citations if item.citation_id])
        graph_threads = [
            (unit.quote or unit.summary or "").strip()
            for unit in evidence_units
            if isinstance(unit.location, dict)
            and str(unit.location.get("kind") or "").startswith(("citation_graph_", "literature_graph_"))
            and (unit.quote or unit.summary)
        ]
        graph_threads = [item for item in graph_threads if item]
        takeaway = f"{primary_claim_text.rstrip('.')}; this is the section's single takeaway."
        gap_statement = cls._build_gap_statement(
            project=project,
            primary_claim_text=primary_claim_text,
            graph_threads=graph_threads,
        )
        disruption_statement = cls._build_disruption_statement(
            primary_claim_text=primary_claim_text,
            graph_threads=graph_threads,
        )
        logical_flow = cls._build_logical_flow(
            gap_statement=gap_statement,
            section=section,
            primary_claim_text=primary_claim_text,
            evidence_count=len(evidence_ids),
            citation_count=len(citation_ids),
        )
        storyboard = cls._build_storyboard(
            section=section,
            primary_claim_text=primary_claim_text,
            gap_statement=gap_statement,
            disruption_statement=disruption_statement,
            claim_ids=claim_ids,
            evidence_ids=evidence_ids,
            include_storyboard=include_storyboard,
        )
        self_questioning = cls._build_self_questioning(
            rounds=self_question_rounds,
            claim_ids=claim_ids,
            evidence_ids=evidence_ids,
            citation_ids=citation_ids,
            gap_statement=gap_statement,
            disruption_statement=disruption_statement,
            primary_claim_text=primary_claim_text,
            logical_flow=logical_flow,
        )
        introduction_cars = cls._build_introduction_cars(
            section_name=section.section_name,
            gap_statement=gap_statement,
            disruption_statement=disruption_statement,
            primary_claim_text=primary_claim_text,
        )
        meal_outline = cls._build_meal_outline(
            logical_flow=logical_flow,
            evidence_count=len(evidence_ids),
            citation_count=len(citation_ids),
        )
        discussion_five_layers = cls._build_discussion_five_layers(
            primary_claim_text=primary_claim_text,
            disruption_statement=disruption_statement,
        )
        return NarrativePlan(
            project_id=project.project_id,
            section_id=section.section_id,
            section_name=section.section_name,
            takeaway_message=takeaway,
            gap_statement=gap_statement,
            disruption_statement=disruption_statement,
            logical_flow=logical_flow,
            figure_storyboard=storyboard,
            self_questioning=self_questioning,
            introduction_hook=f"Introduction hook: {gap_statement}",
            discussion_pivot=f"Discussion pivot: {disruption_statement}",
            introduction_cars=introduction_cars,
            meal_outline=meal_outline,
            discussion_five_layers=discussion_five_layers,
        )

