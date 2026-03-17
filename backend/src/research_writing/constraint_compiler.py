"""Hard-constraint compiler for claim -> evidence -> citation grounding."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from src.research_writing.citation_registry import CitationRegistry
from src.research_writing.claim_graph import Claim
from src.research_writing.evidence_store import EvidenceStore

ClaimSentenceType = Literal["numeric", "comparative", "causal", "novelty", "general"]
ConstraintMode = Literal["strict", "lenient"]


class ConstraintIssue(BaseModel):
    """Issue produced by hard-constraint compilation."""

    claim_id: str
    severity: Literal["error", "warning"]
    message: str


class GroundingBindings(BaseModel):
    """Resolved claim grounding IDs (explicit + implicit)."""

    data_ids: list[str] = Field(default_factory=list)
    citation_ids: list[str] = Field(default_factory=list)
    explicit_data_ids: list[str] = Field(default_factory=list)
    explicit_citation_ids: list[str] = Field(default_factory=list)
    implicit_data_ids: list[str] = Field(default_factory=list)
    implicit_citation_ids: list[str] = Field(default_factory=list)


class CompiledClaim(BaseModel):
    """Claim compilation output with grounding bindings."""

    claim_id: str
    compiled_text: str
    grounding: GroundingBindings
    issues: list[ConstraintIssue] = Field(default_factory=list)


class ClaimMapEntry(BaseModel):
    """Pre-writing claim map row used for bind-first drafting."""

    claim_id: str
    core_claim: str = ""
    claim_type: str
    sentence_type: ClaimSentenceType
    sentence_draft: str
    data_ids: list[str] = Field(default_factory=list)
    citation_ids: list[str] = Field(default_factory=list)
    support_data_ids: list[str] = Field(default_factory=list)
    support_citation_ids: list[str] = Field(default_factory=list)
    caveat: str = ""
    invalid_data_ids: list[str] = Field(default_factory=list)
    invalid_citation_ids: list[str] = Field(default_factory=list)
    rewrite_required: bool = False
    rewrite_reason: str | None = None
    marker_count: int = 0


@dataclass(frozen=True)
class _ResolvedBindingState:
    """Normalized claim binding state (explicit + implicit)."""

    explicit_data_ids_raw: list[str]
    explicit_citation_ids_raw: list[str]
    valid_explicit_data_ids: list[str]
    valid_explicit_citation_ids: list[str]
    valid_implicit_data_ids: list[str]
    valid_implicit_citation_ids: list[str]
    invalid_explicit_data_ids: list[str]
    invalid_explicit_citation_ids: list[str]
    data_ids: list[str]
    citation_ids: list[str]


def classify_claim_sentence(text: str) -> ClaimSentenceType:
    lowered = text.lower()
    if re.search(r"\b\d+(\.\d+)?%?\b", lowered):
        return "numeric"
    if any(tok in lowered for tok in ["outperform", "better than", "compared to", "higher than", "lower than"]):
        return "comparative"
    if any(tok in lowered for tok in ["cause", "causal", "lead to", "drives", "because"]):
        return "causal"
    if any(tok in lowered for tok in ["first", "novel", "to the best of our knowledge", "state-of-the-art"]):
        return "novelty"
    return "general"


def _downgrade_text(text: str) -> str:
    rules = (
        (r"\b(demonstrates|demonstrate|demonstrated)\b", "suggests"),
        (r"\b(proves|prove|proved)\b", "supports"),
        (r"\b(causes|cause|caused)\b", "is associated with"),
        (r"\b(first|novel|state-of-the-art)\b", "potentially"),
    )
    output = text
    for pattern, replacement in rules:
        output = re.sub(pattern, replacement, output, flags=re.IGNORECASE)
    return output


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _extract_binding_ids(text: str, *, prefixes: tuple[str, ...]) -> list[str]:
    escaped = "|".join(re.escape(prefix) for prefix in prefixes)
    bracket_pattern = re.compile(rf"\[(?:{escaped})\s*:\s*([^\]\s]+)\]", flags=re.IGNORECASE)
    inline_pattern = re.compile(rf"\b(?:{escaped})\s*id\s*[:=]\s*([^\s,\.;]+)", flags=re.IGNORECASE)
    matches = bracket_pattern.findall(text) + inline_pattern.findall(text)
    return _dedupe_preserve_order(matches)


def _append_binding_markers(text: str, *, data_ids: list[str], citation_ids: list[str]) -> str:
    output = text.strip()
    for data_id in data_ids[:2]:
        marker = f"[data:{data_id}]"
        if marker.lower() not in output.lower():
            output = f"{output} {marker}"
    for citation_id in citation_ids[:2]:
        marker = f"[citation:{citation_id}]"
        if marker.lower() not in output.lower():
            output = f"{output} {marker}"
    return output


_CLAIM_MARKER_RE = re.compile(r"\[(?:data|evidence|ev|citation|cite|cit|fact)\s*:[^\]]+\]", flags=re.IGNORECASE)


def _strip_binding_markers(text: str) -> str:
    stripped = _CLAIM_MARKER_RE.sub("", text or "")
    return re.sub(r"\s{2,}", " ", stripped).strip()


def _pick_terminal_markers(
    *,
    data_ids: list[str],
    citation_ids: list[str],
    max_markers: int = 2,
) -> tuple[list[str], list[str]]:
    """Pick 1-2 terminal markers for claim sentence draft."""

    budget = max(0, int(max_markers))
    if budget <= 0:
        return [], []
    if data_ids and citation_ids:
        if budget == 1:
            return [data_ids[0]], []
        return [data_ids[0]], [citation_ids[0]]
    if data_ids:
        return data_ids[:budget], []
    return [], citation_ids[:budget]


def _derive_claim_map_caveat(
    *,
    sentence_type: ClaimSentenceType,
    claim_type: str,
    has_data: bool,
    has_citation: bool,
    invalid_binding_count: int,
) -> str:
    if invalid_binding_count > 0:
        return "Claim Map contains unknown binding IDs and requires rewrite before drafting."
    if not has_data and not has_citation:
        return "No verifiable [data:*] or [citation:*] binding found; downgrade certainty and collect missing evidence."
    if sentence_type in {"numeric", "comparative", "causal"} and not has_data:
        return "Core assertion is quantitative/causal but lacks direct data linkage; treat as preliminary."
    if claim_type in {"strong", "result"} and not has_citation:
        return "Strong/result claim is weakly contextualized without citation linkage."
    return "Calibrate wording to avoid overclaim and keep unresolved confounders explicit."


class ClaimConstraintCompiler:
    """Compile and hard-validate one claim against evidence/citation stores."""

    def __init__(
        self,
        evidence_store: EvidenceStore,
        citation_registry: CitationRegistry,
        *,
        mode: ConstraintMode = "strict",
    ) -> None:
        self._evidence_store = evidence_store
        self._citation_registry = citation_registry
        self._mode = mode

    def _resolve_binding_state(self, claim: Claim) -> _ResolvedBindingState:
        explicit_data_ids_raw = _extract_binding_ids(claim.text, prefixes=("data", "evidence", "ev"))
        explicit_citation_ids_raw = _extract_binding_ids(claim.text, prefixes=("citation", "cite", "cit"))
        implicit_data_ids = _dedupe_preserve_order(claim.evidence_ids)
        implicit_citation_ids = _dedupe_preserve_order(claim.citation_ids)

        valid_explicit_data_ids = [evidence_id for evidence_id in explicit_data_ids_raw if self._evidence_store.get(evidence_id) is not None]
        valid_explicit_citation_ids = [citation_id for citation_id in explicit_citation_ids_raw if self._citation_registry.get(citation_id) is not None]
        valid_implicit_data_ids = [evidence_id for evidence_id in implicit_data_ids if self._evidence_store.get(evidence_id) is not None]
        valid_implicit_citation_ids = [citation_id for citation_id in implicit_citation_ids if self._citation_registry.get(citation_id) is not None]

        invalid_explicit_data_ids = [evidence_id for evidence_id in explicit_data_ids_raw if self._evidence_store.get(evidence_id) is None]
        invalid_explicit_citation_ids = [citation_id for citation_id in explicit_citation_ids_raw if self._citation_registry.get(citation_id) is None]

        data_ids = _dedupe_preserve_order(valid_explicit_data_ids + valid_implicit_data_ids)
        citation_ids = _dedupe_preserve_order(valid_explicit_citation_ids + valid_implicit_citation_ids)
        return _ResolvedBindingState(
            explicit_data_ids_raw=explicit_data_ids_raw,
            explicit_citation_ids_raw=explicit_citation_ids_raw,
            valid_explicit_data_ids=valid_explicit_data_ids,
            valid_explicit_citation_ids=valid_explicit_citation_ids,
            valid_implicit_data_ids=valid_implicit_data_ids,
            valid_implicit_citation_ids=valid_implicit_citation_ids,
            invalid_explicit_data_ids=invalid_explicit_data_ids,
            invalid_explicit_citation_ids=invalid_explicit_citation_ids,
            data_ids=data_ids,
            citation_ids=citation_ids,
        )

    def build_claim_map_entry(self, claim: Claim, *, max_markers: int = 2) -> ClaimMapEntry:
        """Build bind-first claim map row before prose generation."""

        sentence_type = classify_claim_sentence(claim.text)
        state = self._resolve_binding_state(claim)
        core_claim = _strip_binding_markers(claim.text.strip())
        selected_data_ids, selected_citation_ids = _pick_terminal_markers(
            data_ids=state.data_ids,
            citation_ids=state.citation_ids,
            max_markers=max_markers,
        )
        rewrite_reasons: list[str] = []
        if state.invalid_explicit_data_ids:
            rewrite_reasons.append(
                "Unknown Data ID(s): " + ", ".join(state.invalid_explicit_data_ids)
            )
        if state.invalid_explicit_citation_ids:
            rewrite_reasons.append(
                "Unknown Citation ID(s): " + ", ".join(state.invalid_explicit_citation_ids)
            )
        requires_binding = claim.claim_type in {"strong", "result", "method"} or sentence_type in {
            "numeric",
            "comparative",
            "causal",
            "novelty",
        }
        if requires_binding and not (state.data_ids or state.citation_ids):
            rewrite_reasons.append("No valid binding IDs available for a claim that requires grounding.")
        sentence_draft = _append_binding_markers(
            core_claim or claim.text.strip(),
            data_ids=selected_data_ids,
            citation_ids=selected_citation_ids,
        )
        rewrite_reason = "; ".join(rewrite_reasons) if rewrite_reasons else None
        return ClaimMapEntry(
            claim_id=claim.claim_id,
            core_claim=core_claim,
            claim_type=claim.claim_type,
            sentence_type=sentence_type,
            sentence_draft=sentence_draft,
            data_ids=state.data_ids,
            citation_ids=state.citation_ids,
            support_data_ids=state.data_ids,
            support_citation_ids=state.citation_ids,
            caveat=_derive_claim_map_caveat(
                sentence_type=sentence_type,
                claim_type=claim.claim_type,
                has_data=bool(state.data_ids),
                has_citation=bool(state.citation_ids),
                invalid_binding_count=len(state.invalid_explicit_data_ids) + len(state.invalid_explicit_citation_ids),
            ),
            invalid_data_ids=state.invalid_explicit_data_ids,
            invalid_citation_ids=state.invalid_explicit_citation_ids,
            rewrite_required=bool(rewrite_reasons),
            rewrite_reason=rewrite_reason,
            marker_count=len(selected_data_ids) + len(selected_citation_ids),
        )

    def validate_claim_map_entry(self, entry: ClaimMapEntry) -> list[ConstraintIssue]:
        """Validate Claim Map row IDs and rewrite requirement flags."""

        issues: list[ConstraintIssue] = []
        for evidence_id in entry.invalid_data_ids:
            issues.append(
                ConstraintIssue(
                    claim_id=entry.claim_id,
                    severity="error",
                    message=f"Claim Map references unknown Data ID '{evidence_id}'. Rewrite required.",
                )
            )
        for citation_id in entry.invalid_citation_ids:
            issues.append(
                ConstraintIssue(
                    claim_id=entry.claim_id,
                    severity="error",
                    message=f"Claim Map references unknown Citation ID '{citation_id}'. Rewrite required.",
                )
            )
        for evidence_id in entry.data_ids:
            if self._evidence_store.get(evidence_id) is None:
                issues.append(
                    ConstraintIssue(
                        claim_id=entry.claim_id,
                        severity="error",
                        message=f"Claim Map Data ID '{evidence_id}' is not present in evidence store.",
                    )
                )
        for citation_id in entry.citation_ids:
            if self._citation_registry.get(citation_id) is None:
                issues.append(
                    ConstraintIssue(
                        claim_id=entry.claim_id,
                        severity="error",
                        message=f"Claim Map Citation ID '{citation_id}' is not present in citation registry.",
                    )
                )
        if entry.rewrite_required:
            issues.append(
                ConstraintIssue(
                    claim_id=entry.claim_id,
                    severity="error",
                    message=entry.rewrite_reason or "Claim Map row requires rewrite before prose generation.",
                )
            )
        return issues

    def compile(self, claim: Claim) -> CompiledClaim:
        sentence_type = classify_claim_sentence(claim.text)
        compiled = claim.text.strip()
        issues: list[ConstraintIssue] = []

        state = self._resolve_binding_state(claim)

        for evidence_id in state.invalid_explicit_data_ids:
            issues.append(
                ConstraintIssue(
                    claim_id=claim.claim_id,
                    severity="error",
                    message=f"Claim references unknown Data ID '{evidence_id}'.",
                )
            )
        for citation_id in state.invalid_explicit_citation_ids:
            issues.append(
                ConstraintIssue(
                    claim_id=claim.claim_id,
                    severity="warning",
                    message=f"Claim references unknown Citation ID '{citation_id}'.",
                )
            )

        data_ids = state.data_ids
        citation_ids = state.citation_ids
        has_data_binding = bool(data_ids)
        has_citation_binding = bool(citation_ids)

        requires_evidence = claim.claim_type in {"strong", "result"} or sentence_type in {"numeric", "comparative", "causal", "novelty"}
        requires_citation = claim.claim_type in {"strong", "result", "method"} or sentence_type in {"numeric", "comparative", "causal", "novelty"}
        has_any_binding = has_data_binding or has_citation_binding

        if not has_any_binding:
            issues.append(
                ConstraintIssue(
                    claim_id=claim.claim_id,
                    severity="error",
                    message="Claim must bind to at least one Data ID or Citation ID.",
                )
            )
            compiled = _downgrade_text(compiled)
            if self._mode == "strict":
                compiled = f"{compiled} [grounding required]"

        if requires_evidence and not has_data_binding:
            issues.append(
                ConstraintIssue(
                    claim_id=claim.claim_id,
                    severity="error",
                    message=f"Missing Data ID grounding for {sentence_type} claim.",
                )
            )
            if self._mode == "strict":
                compiled = f"{_downgrade_text(compiled)} [insufficient data]"
            else:
                compiled = _downgrade_text(compiled)

        if requires_citation and not has_citation_binding:
            issues.append(
                ConstraintIssue(
                    claim_id=claim.claim_id,
                    severity="warning",
                    message=f"Missing Citation ID grounding for {sentence_type} claim.",
                )
            )
            compiled = f"{compiled} [citation needed]"

        if has_any_binding:
            compiled = _append_binding_markers(compiled, data_ids=data_ids, citation_ids=citation_ids)

        grounding = GroundingBindings(
            data_ids=data_ids,
            citation_ids=citation_ids,
            explicit_data_ids=state.valid_explicit_data_ids,
            explicit_citation_ids=state.valid_explicit_citation_ids,
            implicit_data_ids=state.valid_implicit_data_ids,
            implicit_citation_ids=state.valid_implicit_citation_ids,
        )
        return CompiledClaim(
            claim_id=claim.claim_id,
            compiled_text=compiled,
            grounding=grounding,
            issues=issues,
        )


def enforce_claim_constraints(
    claim: Claim,
    evidence_store: EvidenceStore,
    citation_registry: CitationRegistry,
    *,
    mode: ConstraintMode = "strict",
) -> tuple[str, list[ConstraintIssue]]:
    """Enforce hard constraints for a single claim sentence."""
    compiled = ClaimConstraintCompiler(
        evidence_store=evidence_store,
        citation_registry=citation_registry,
        mode=mode,
    ).compile(claim)
    return compiled.compiled_text, compiled.issues


# Backward-compatible alias with user-requested naming.
Claim_Constraint_Compiler = ClaimConstraintCompiler
