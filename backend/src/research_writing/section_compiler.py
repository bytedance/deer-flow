"""Section compiler with claim-grounding constraints."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from src.research_writing.citation_registry import CitationRegistry
from src.research_writing.claim_graph import ClaimGraph
from src.research_writing.constraint_compiler import ClaimConstraintCompiler, ClaimMapEntry
from src.research_writing.evidence_store import EvidenceStore, EvidenceUnit
from src.research_writing.project_state import SectionDraft
from src.research_writing.source_of_truth import SourceOfTruthStore

CompileMode = Literal["strict", "lenient"]
NarrativeTone = Literal["conservative", "balanced", "aggressive"]
NarrativeEvidenceDensity = Literal["low", "medium", "high"]
NarrativeSectionType = Literal["introduction", "results", "discussion", "general"]
_QUOTED_TITLE_PATTERN = re.compile(r"'([^']+)'")


class CompileIssue(BaseModel):
    """Issue detected during compilation."""

    claim_id: str
    severity: Literal["error", "warning"]
    message: str


class CompileResult(BaseModel):
    """Compilation output for one section."""

    section_id: str
    compiled_text: str
    issues: list[CompileIssue] = Field(default_factory=list)
    narrative_sentence_count: int = 0
    narrative_strategy: NarrativeWritingStrategy | None = None
    claim_map: list[ClaimMapEntry] = Field(default_factory=list)


class NarrativeWritingStrategy(BaseModel):
    """Configurable narrative writing strategy for literature-lineage templates."""

    tone: NarrativeTone = "balanced"
    max_templates: int = Field(default=2, ge=1, le=5)
    evidence_density: NarrativeEvidenceDensity = "medium"
    auto_by_section_type: bool = False
    section_type: NarrativeSectionType = "general"
    paragraph_tones: list[NarrativeTone] = Field(default_factory=list)
    paragraph_evidence_densities: list[NarrativeEvidenceDensity] = Field(default_factory=list)


def _paragraph_tone(strategy: NarrativeWritingStrategy, paragraph_index: int) -> NarrativeTone:
    if paragraph_index < len(strategy.paragraph_tones):
        return strategy.paragraph_tones[paragraph_index]
    return strategy.tone


def _paragraph_density(
    strategy: NarrativeWritingStrategy,
    paragraph_index: int,
) -> NarrativeEvidenceDensity:
    if paragraph_index < len(strategy.paragraph_evidence_densities):
        return strategy.paragraph_evidence_densities[paragraph_index]
    return strategy.evidence_density


def _is_graph_narrative_unit(unit: EvidenceUnit | None) -> bool:
    if unit is None:
        return False
    if not unit.evidence_id.startswith("graph:"):
        return False
    if unit.evidence_type != "manual_note":
        return False
    kind = unit.location.get("kind") if isinstance(unit.location, dict) else None
    return kind in {
        "citation_graph_narrative",
        "literature_graph_claim_cluster",
        "literature_graph_synthesis",
    }


def _thread_index(unit: EvidenceUnit) -> int:
    if not isinstance(unit.location, dict):
        return 0
    raw = unit.location.get("thread_index")
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str) and raw.isdigit():
        return int(raw)
    return 0


def _graph_group_key(unit: EvidenceUnit) -> tuple[str, str]:
    if not isinstance(unit.location, dict):
        return ("", "")
    source = unit.location.get("source")
    external_id = unit.location.get("external_id")
    return (str(source or ""), str(external_id or ""))


def _select_graph_narrative_units(section: SectionDraft, evidence_store: EvidenceStore, *, max_units: int = 3) -> list[EvidenceUnit]:
    scoped: list[EvidenceUnit] = []
    for evidence_id in section.evidence_ids:
        unit = evidence_store.get(evidence_id)
        if _is_graph_narrative_unit(unit):
            scoped.append(unit)
    if scoped:
        scoped.sort(key=_thread_index)
        return scoped[:max_units]

    global_units = [unit for unit in evidence_store.list_by_type("manual_note") if _is_graph_narrative_unit(unit)]
    if not global_units:
        return []
    latest_group_key = _graph_group_key(global_units[-1])
    latest_group = [unit for unit in global_units if _graph_group_key(unit) == latest_group_key]
    latest_group.sort(key=_thread_index)
    return latest_group[:max_units]


def _citation_budget(density: NarrativeEvidenceDensity) -> int:
    if density == "low":
        return 0
    if density == "medium":
        return 1
    return 2


def _tone_phrase(tone: NarrativeTone, *, conservative: str, balanced: str, aggressive: str) -> str:
    if tone == "conservative":
        return conservative
    if tone == "aggressive":
        return aggressive
    return balanced


def _render_professor_style_sentence(unit: EvidenceUnit, *, tone: NarrativeTone) -> str:
    source_text = (unit.quote or unit.summary or "").strip()
    lowered = source_text.lower()
    titles = _QUOTED_TITLE_PATTERN.findall(source_text)
    if "supports the anchor claim" in lowered and "refutes it" in lowered:
        bridge = _tone_phrase(
            tone,
            conservative="highlights a testable disagreement in the current literature",
            balanced="reveals a disagreement in the current literature that needs direct response",
            aggressive="shows a core disagreement in the literature that must be resolved head-on",
        )
        return (
            "[支持] Literature evidence supports the anchor mechanism. "
            "[反驳] Counter-evidence reports an incompatible observation. "
            f"[调和] GraphRAG debate mapping {bridge}; the introduction should present support and refutation evidence in parallel."
        )
    if "synthesis route:" in lowered:
        tail = _tone_phrase(
            tone,
            conservative="and discuss reconciliation boundaries cautiously.",
            balanced="and discuss a falsifiable reconciliation mechanism.",
            aggressive="and position reconciliation as the main narrative axis in discussion.",
        )
        return f"[调和] {source_text.rstrip('.')} {tail}"
    if "co-citation signal" in lowered and len(titles) >= 2:
        lead = _tone_phrase(
            tone,
            conservative=f"Although {titles[0]} may outline one explanatory path,",
            balanced=f"Although {titles[0]} outlines one explanatory path,",
            aggressive=f"Although {titles[0]} establishes one explanatory path,",
        )
        tail = _tone_phrase(
            tone,
            conservative=f"recent co-citation patterns around {titles[1]} could suggest a competing mechanism worth testing.",
            balanced=f"recent co-citation patterns around {titles[1]} suggest a competing mechanism worth explicit comparison.",
            aggressive=f"recent co-citation patterns around {titles[1]} strongly suggest a competing mechanism that should be foregrounded.",
        )
        return f"{lead} {tail}"
    if "timeline:" in lowered and len(titles) >= 2:
        signal = _tone_phrase(
            tone,
            conservative="may indicate",
            balanced="indicates",
            aggressive="demonstrates",
        )
        return (
            f"From {titles[0]} to {titles[1]}, the publication timeline {signal} that the field's core assumptions are shifting."
        )
    if "narrative contrast candidate" in lowered and len(titles) >= 2:
        tail = _tone_phrase(
            tone,
            conservative=f"{titles[1]} offers a viable alternative interpretation that should be considered.",
            balanced=f"{titles[1]} provides a viable alternative interpretation that should be discussed in parallel.",
            aggressive=f"{titles[1]} provides a stronger alternative interpretation that should be presented as a central axis of debate.",
        )
        return (
            f"While {titles[0]} is often treated as the default narrative, {tail}"
        )
    if len(titles) >= 2:
        bridge = _tone_phrase(
            tone,
            conservative="may suggest",
            balanced="suggests",
            aggressive="strongly suggests",
        )
        return (
            f"Although {titles[0]} supports one interpretation, {titles[1]} {bridge} an alternative account of the same phenomenon."
        )
    stripped = source_text.rstrip(".")
    if stripped:
        lead = _tone_phrase(
            tone,
            conservative="Citation-graph evidence may indicate the following narrative thread:",
            balanced="Citation-graph evidence indicates the following narrative thread:",
            aggressive="Citation-graph evidence strongly indicates the following narrative thread:",
        )
        return f"{lead} {stripped}."
    return _tone_phrase(
        tone,
        conservative="Citation-graph evidence may indicate a narrative thread that should be discussed alongside the dominant interpretation.",
        balanced="Citation-graph evidence indicates a narrative thread that should be discussed alongside the dominant interpretation.",
        aggressive="Citation-graph evidence strongly indicates a narrative thread that should be foregrounded alongside the dominant interpretation.",
    )


def _render_binding_suffix(
    unit: EvidenceUnit,
    citation_registry: CitationRegistry,
    *,
    evidence_density: NarrativeEvidenceDensity,
) -> tuple[str, int, int]:
    markers = [f"[data:{unit.evidence_id}]"]
    available_citation_ids = [citation_id for citation_id in unit.citation_ids if citation_registry.get(citation_id) is not None]
    required_citations = _citation_budget(evidence_density)
    used_citations = 0
    for citation_id in available_citation_ids[:required_citations]:
        if citation_registry.get(citation_id) is not None:
            markers.append(f"[citation:{citation_id}]")
            used_citations += 1
    return " ".join(markers), used_citations, required_citations


def _build_narrative_template_block(
    section: SectionDraft,
    evidence_store: EvidenceStore,
    citation_registry: CitationRegistry,
    strategy: NarrativeWritingStrategy,
) -> tuple[str, list[CompileIssue], int]:
    units = _select_graph_narrative_units(section, evidence_store, max_units=strategy.max_templates)
    if not units:
        return "", [], 0
    lines: list[str] = []
    issues: list[CompileIssue] = []
    for paragraph_index, unit in enumerate(units):
        tone = _paragraph_tone(strategy, paragraph_index)
        evidence_density = _paragraph_density(strategy, paragraph_index)
        sentence = _render_professor_style_sentence(unit, tone=tone)
        binding, used_citations, required_citations = _render_binding_suffix(
            unit,
            citation_registry,
            evidence_density=evidence_density,
        )
        lines.append(f"{sentence} {binding}".strip())
        if required_citations > used_citations:
            issues.append(
                CompileIssue(
                    claim_id=f"narrative:{unit.evidence_id}",
                    severity="warning",
                    message=(
                        "Narrative template evidence density target unmet: "
                        f"required {required_citations} citation marker(s), got {used_citations} "
                        f"for paragraph {paragraph_index + 1}."
                    ),
                )
            )
    intro = "The following literature-lineage templates are auto-generated from the citation graph:"
    return f"{intro}\n\n" + "\n\n".join(lines), issues, len(lines)


def _build_claim_map_for_section(
    *,
    section: SectionDraft,
    claim_graph: ClaimGraph,
    compiler: ClaimConstraintCompiler,
) -> tuple[list[ClaimMapEntry], list[CompileIssue]]:
    claim_map: list[ClaimMapEntry] = []
    issues: list[CompileIssue] = []
    for claim_id in section.claim_ids:
        claim = claim_graph.get(claim_id)
        if claim is None:
            issues.append(CompileIssue(claim_id=claim_id, severity="error", message="Claim ID not found in claim graph."))
            continue
        entry = compiler.build_claim_map_entry(claim, max_markers=2)
        claim_map.append(entry)
        validation_issues = compiler.validate_claim_map_entry(entry)
        issues.extend(
            CompileIssue(
                claim_id=item.claim_id,
                severity=item.severity,
                message=item.message,
            )
            for item in validation_issues
        )
        if entry.marker_count == 0:
            issues.append(
                CompileIssue(
                    claim_id=claim_id,
                    severity="warning",
                    message="Claim Map has no valid binding markers; strict mode may downgrade this sentence.",
                )
            )
    return claim_map, issues


class SectionCompiler:
    """Compile section drafts from structured claims/evidence/citations."""

    @classmethod
    def compile_section(
        cls,
        section: SectionDraft,
        claim_graph: ClaimGraph,
        evidence_store: EvidenceStore,
        citation_registry: CitationRegistry,
        source_of_truth_store: SourceOfTruthStore | None = None,
        *,
        mode: CompileMode = "strict",
        narrative_strategy: NarrativeWritingStrategy | None = None,
    ) -> CompileResult:
        issues: list[CompileIssue] = []
        lines: list[str] = []
        resolved_strategy = narrative_strategy or NarrativeWritingStrategy()
        compiler = ClaimConstraintCompiler(
            evidence_store=evidence_store,
            citation_registry=citation_registry,
            mode=mode,
        )
        claim_map, claim_map_issues = _build_claim_map_for_section(
            section=section,
            claim_graph=claim_graph,
            compiler=compiler,
        )
        issues.extend(claim_map_issues)
        claim_map_by_id = {item.claim_id: item for item in claim_map}

        for claim_id in section.claim_ids:
            claim = claim_graph.get(claim_id)
            if claim is None:
                continue

            claim_map_row = claim_map_by_id.get(claim_id)
            prebound_text = claim_map_row.sentence_draft if claim_map_row is not None else claim.text
            compiled_claim = compiler.compile(claim.model_copy(update={"text": prebound_text}))
            line = compiled_claim.compiled_text
            marker = f"[claim:{claim.claim_id}]"
            if marker.lower() not in line.lower():
                line = f"{line} {marker}".strip()
            raw_issues = compiled_claim.issues
            issues.extend(CompileIssue(claim_id=i.claim_id, severity=i.severity, message=i.message) for i in raw_issues)

            lines.append(line)

        compiled = "\n\n".join(line for line in lines if line)
        if source_of_truth_store is not None and section.fact_ids:
            fact_paragraph = source_of_truth_store.compile_results_paragraph(section.fact_ids)
            if fact_paragraph:
                compiled = f"{fact_paragraph}\n\n{compiled}".strip()
        if section.content.strip():
            compiled = f"{section.content.strip()}\n\n{compiled}".strip()
        narrative_templates, narrative_issues, narrative_sentence_count = _build_narrative_template_block(
            section,
            evidence_store,
            citation_registry,
            resolved_strategy,
        )
        issues.extend(narrative_issues)
        if narrative_templates:
            compiled = f"{compiled}\n\n### Literature Lineage Templates\n{narrative_templates}".strip()
        return CompileResult(
            section_id=section.section_id,
            compiled_text=compiled,
            issues=issues,
            narrative_sentence_count=narrative_sentence_count,
            narrative_strategy=resolved_strategy,
            claim_map=claim_map,
        )
