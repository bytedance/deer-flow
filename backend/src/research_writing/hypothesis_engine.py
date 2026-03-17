"""Hypothesis-driven reasoning engine for research-writing runtime."""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Literal

from pydantic import BaseModel, Field

from src.research_writing.citation_registry import CitationRecord, CitationRegistry
from src.research_writing.evidence_store import EvidenceStore, EvidenceUnit
from src.research_writing.source_of_truth import NumericFact, SourceOfTruthStore

HypothesisConfidence = Literal["high", "medium", "low"]

_STOPWORDS = {
    "that",
    "with",
    "from",
    "this",
    "these",
    "those",
    "were",
    "have",
    "has",
    "into",
    "between",
    "across",
    "through",
    "using",
    "results",
    "result",
    "method",
    "methods",
    "study",
    "analysis",
    "data",
    "based",
    "evidence",
    "shows",
    "showed",
    "showing",
    "observed",
    "observation",
    "significant",
}


class HypothesisScore(BaseModel):
    """Scoring dimensions for one hypothesis candidate."""

    data_support: float = Field(ge=0.0, le=1.0)
    literature_support: float = Field(ge=0.0, le=1.0)
    novelty: float = Field(ge=0.0, le=1.0)
    overall: float = Field(ge=0.0, le=1.0)


class HypothesisCandidate(BaseModel):
    """One ranked hypothesis candidate."""

    hypothesis_id: str
    statement: str
    mechanism_rationale: str
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    supporting_citation_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)
    score: HypothesisScore
    confidence: HypothesisConfidence
    proposed_validation: list[str] = Field(default_factory=list)


class HypothesisBundle(BaseModel):
    """Generated hypothesis set and synthesis paragraph."""

    feature_summary: list[str] = Field(default_factory=list)
    hypotheses: list[HypothesisCandidate] = Field(default_factory=list)
    synthesis_paragraph: str = ""


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _confidence_from_score(score: float) -> HypothesisConfidence:
    if score >= 0.78:
        return "high"
    if score >= 0.58:
        return "medium"
    return "low"


def _tokenize(text: str) -> list[str]:
    tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{3,}", text.lower())
    return [tok for tok in tokens if tok not in _STOPWORDS]


def _top_terms(evidences: list[EvidenceUnit], limit: int = 4) -> list[str]:
    counter: Counter[str] = Counter()
    for ev in evidences:
        counter.update(_tokenize(f"{ev.summary} {ev.quote or ''}"))
    if not counter:
        return ["signal", "response", "mechanism", "cohort"][:limit]
    return [term for term, _count in counter.most_common(limit)]


def _collect_focused_evidence(evidence_store: EvidenceStore, focus_evidence_ids: list[str] | None) -> list[EvidenceUnit]:
    if focus_evidence_ids:
        focused = [evidence_store.get(eid) for eid in focus_evidence_ids]
        return [ev for ev in focused if ev is not None]
    return evidence_store.list()


def _collect_focused_facts(source_of_truth_store: SourceOfTruthStore | None, focus_fact_ids: list[str] | None) -> list[NumericFact]:
    if source_of_truth_store is None:
        return []
    if focus_fact_ids:
        facts = [source_of_truth_store.get_fact(fid) for fid in focus_fact_ids]
        return [fact for fact in facts if fact is not None]
    return source_of_truth_store.list_facts()


def _collect_candidate_citations(citation_registry: CitationRegistry, evidences: list[EvidenceUnit]) -> dict[str, CitationRecord]:
    citation_ids: set[str] = set()
    for ev in evidences:
        citation_ids.update(ev.citation_ids)
    records: dict[str, CitationRecord] = {}
    for cid in citation_ids:
        record = citation_registry.get(cid)
        if record is not None:
            records[cid] = record
    return records


def _feature_summary(evidences: list[EvidenceUnit], facts: list[NumericFact], terms: list[str]) -> list[str]:
    lines: list[str] = []
    if evidences:
        by_type = Counter(ev.evidence_type for ev in evidences)
        type_summary = ", ".join(f"{count} {etype}" for etype, count in sorted(by_type.items()))
        lines.append(f"Evidence coverage: {len(evidences)} units ({type_summary}).")
    if facts:
        values = [fact.value for fact in facts]
        lines.append(f"Numeric trend range: min={min(values):g}, max={max(values):g}, n={len(values)}.")
    if terms:
        lines.append(f"Dominant signals: {', '.join(terms[:3])}.")
    if not lines:
        lines.append("Limited structured evidence was available; generated hypotheses are exploratory.")
    return lines


def _template_statements(primary: str, secondary: str, tertiary: str) -> list[tuple[str, str, list[str], list[str]]]:
    return [
        (
            "H1",
            f"The observed effect is likely driven by a {primary}-mediated mechanism that propagates into {secondary}.",
            f"Evidence repeatedly references {primary} and {secondary}, suggesting a linked mechanistic chain rather than an isolated artifact.",
            ["Run targeted perturbation on the proposed upstream pathway.", "Quantify downstream response kinetics across independent cohorts."],
            [primary, secondary],
        ),
        (
            "H2",
            f"A context-dependent adaptation hypothesis explains the signal, where {secondary} changes are buffered by {tertiary}.",
            f"Heterogeneous evidence patterns can be reconciled if {tertiary} acts as a compensatory factor under variable conditions.",
            ["Stratify by cohort/context to test interaction effects.", "Perform sensitivity analysis under perturbation stressors."],
            [secondary, tertiary],
        ),
        (
            "H3",
            f"The current pattern may reflect a two-stage process: early {primary} perturbation followed by delayed {tertiary} stabilization.",
            "A two-phase interpretation better aligns with mixed evidence timing and non-monotonic numeric trajectories.",
            ["Collect denser temporal readouts to resolve phase boundaries.", "Fit competing one-stage vs two-stage models and compare goodness-of-fit."],
            [primary, tertiary],
        ),
        (
            "H4",
            f"An alternative explanation is residual measurement or batch effects amplifying apparent {secondary} differences.",
            "Some evidence may be susceptible to protocol or acquisition variance, which can inflate apparent biological or algorithmic effect size.",
            ["Run batch-effect diagnostics and negative controls.", "Recompute key metrics with robustness corrections."],
            [secondary, "batch"],
        ),
        (
            "H5",
            f"A hybrid model is plausible: true {primary} signal exists, but magnitude is modulated by {tertiary}-linked confounders.",
            "This reconciles supportive evidence with inconsistent segments by separating directionality from effect-size inflation.",
            ["Estimate confounder-adjusted effect sizes.", "Validate on external datasets with matched acquisition protocols."],
            [primary, tertiary, "confounder"],
        ),
    ]


def _candidate_scores(
    terms: list[str],
    evidences: list[EvidenceUnit],
    facts: list[NumericFact],
    citations: dict[str, CitationRecord],
) -> list[HypothesisCandidate]:
    primary = terms[0] if len(terms) > 0 else "signal"
    secondary = terms[1] if len(terms) > 1 else "response"
    tertiary = terms[2] if len(terms) > 2 else "cohort"
    templates = _template_statements(primary, secondary, tertiary)
    candidates: list[HypothesisCandidate] = []

    for idx, (hypothesis_id, statement, rationale, validations, marker_terms) in enumerate(templates, start=1):
        marker_terms_lower = [term.lower() for term in marker_terms if term]
        matched_evidence: list[EvidenceUnit] = []
        contradictory_evidence: list[EvidenceUnit] = []
        for evidence in evidences:
            text = f"{evidence.summary} {evidence.quote or ''}".lower()
            if any(term in text for term in marker_terms_lower):
                matched_evidence.append(evidence)
            if any(tok in text for tok in ("inconsistent", "contradict", "however", "not significant", "artifact")):
                contradictory_evidence.append(evidence)

        supporting_citation_ids: list[str] = []
        for evidence in matched_evidence:
            supporting_citation_ids.extend([cid for cid in evidence.citation_ids if cid in citations])
        supporting_citation_ids = sorted(set(supporting_citation_ids))

        verified_count = sum(1 for cid in supporting_citation_ids if citations[cid].verified)
        citation_count = len(supporting_citation_ids)
        matched_count = len(matched_evidence)
        contradictory_count = len({ev.evidence_id for ev in contradictory_evidence})

        data_support = _clamp01(0.25 + 0.14 * matched_count + 0.05 * min(len(facts), 4) - 0.08 * contradictory_count)
        literature_support = _clamp01(0.2 + 0.15 * citation_count + (0.25 * verified_count / citation_count if citation_count else 0.0))
        novelty = _clamp01(0.85 - 0.08 * citation_count + 0.03 * math.log(idx + 1))
        overall = _clamp01(0.45 * data_support + 0.35 * literature_support + 0.2 * novelty)

        candidates.append(
            HypothesisCandidate(
                hypothesis_id=hypothesis_id,
                statement=statement,
                mechanism_rationale=rationale,
                supporting_evidence_ids=sorted({ev.evidence_id for ev in matched_evidence}),
                supporting_citation_ids=supporting_citation_ids,
                contradicting_evidence_ids=sorted({ev.evidence_id for ev in contradictory_evidence}),
                score=HypothesisScore(
                    data_support=round(data_support, 3),
                    literature_support=round(literature_support, 3),
                    novelty=round(novelty, 3),
                    overall=round(overall, 3),
                ),
                confidence=_confidence_from_score(overall),
                proposed_validation=validations,
            )
        )
    return sorted(candidates, key=lambda c: c.score.overall, reverse=True)


def render_hypothesis_synthesis(bundle: HypothesisBundle) -> str:
    """Render a short manuscript-ready hypothesis synthesis paragraph."""
    if not bundle.hypotheses:
        return "Hypothesis-driven synthesis is currently unavailable due to missing structured evidence."
    best = bundle.hypotheses[0]
    alternatives = bundle.hypotheses[1:3]
    alt_text = "; ".join(f"{item.hypothesis_id} score={item.score.overall:g}" for item in alternatives) if alternatives else "no ranked alternatives"
    return (
        f"Top-ranked hypothesis ({best.hypothesis_id}, overall={best.score.overall:g}) proposes: {best.statement} "
        f"This interpretation is supported by data_score={best.score.data_support:g} and literature_score={best.score.literature_support:g}. "
        f"Competing hypotheses remain ({alt_text}); targeted falsification tests are recommended before strong causal claims."
    ).strip()


def generate_hypotheses(
    *,
    evidence_store: EvidenceStore,
    citation_registry: CitationRegistry,
    source_of_truth_store: SourceOfTruthStore | None = None,
    focus_evidence_ids: list[str] | None = None,
    focus_fact_ids: list[str] | None = None,
    max_hypotheses: int = 5,
) -> HypothesisBundle:
    """Generate 3-5 scored hypothesis candidates from evidence + literature + facts."""
    bounded_n = max(3, min(max_hypotheses, 5))
    evidences = _collect_focused_evidence(evidence_store, focus_evidence_ids)
    facts = _collect_focused_facts(source_of_truth_store, focus_fact_ids)
    citations = _collect_candidate_citations(citation_registry, evidences)
    terms = _top_terms(evidences, limit=4)

    candidates = _candidate_scores(terms, evidences, facts, citations)[:bounded_n]
    bundle = HypothesisBundle(
        feature_summary=_feature_summary(evidences, facts, terms),
        hypotheses=candidates,
    )
    bundle.synthesis_paragraph = render_hypothesis_synthesis(bundle)
    return bundle

