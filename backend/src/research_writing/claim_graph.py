"""Claim graph and validation utilities."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from src.research_writing.citation_registry import CitationRegistry
from src.research_writing.evidence_store import EvidenceStore

ClaimType = Literal["strong", "weak", "background", "method", "result", "limitation"]


class Claim(BaseModel):
    """Single scientific claim."""

    claim_id: str
    text: str
    claim_type: ClaimType = "weak"
    evidence_ids: list[str] = Field(default_factory=list)
    citation_ids: list[str] = Field(default_factory=list)
    related_claim_ids: list[str] = Field(default_factory=list)


class ClaimValidationIssue(BaseModel):
    """Validation issue found when checking claim-grounding constraints."""

    claim_id: str
    severity: Literal["error", "warning"]
    message: str


_DATA_TAG_RE = re.compile(r"\[(?:data|evidence|ev)\s*:\s*([^\]\s]+)\]", flags=re.IGNORECASE)
_CITATION_TAG_RE = re.compile(r"\[(?:citation|cite|cit)\s*:\s*([^\]\s]+)\]", flags=re.IGNORECASE)


def _dedup_keep_order(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        item = str(raw).strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _extract_tag_ids(text: str, *, tag: Literal["data", "citation"]) -> list[str]:
    if not text:
        return []
    matches = _DATA_TAG_RE.findall(text) if tag == "data" else _CITATION_TAG_RE.findall(text)
    return _dedup_keep_order([str(item).strip() for item in matches])


class _ClaimPayload(BaseModel):
    items: dict[str, Claim] = Field(default_factory=dict)


class ClaimGraph:
    """File-backed claim graph with grounding validation."""

    def __init__(self, storage_path: Path):
        self.storage_path = storage_path
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> _ClaimPayload:
        if not self.storage_path.exists():
            return _ClaimPayload()
        data = json.loads(self.storage_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return _ClaimPayload()
        return _ClaimPayload.model_validate(data)

    def _save(self, payload: _ClaimPayload) -> None:
        self.storage_path.write_text(payload.model_dump_json(indent=2), encoding="utf-8")

    def upsert(self, claim: Claim) -> Claim:
        payload = self._load()
        payload.items[claim.claim_id] = claim
        self._save(payload)
        return claim

    def get(self, claim_id: str) -> Claim | None:
        return self._load().items.get(claim_id)

    def list(self) -> list[Claim]:
        return list(self._load().items.values())

    def validate_grounding(self, evidence_store: EvidenceStore, citation_registry: CitationRegistry) -> list[ClaimValidationIssue]:
        """Validate hard grounding constraints for claims."""
        issues: list[ClaimValidationIssue] = []
        for claim in self.list():
            explicit_evidence_ids = _extract_tag_ids(claim.text, tag="data")
            explicit_citation_ids = _extract_tag_ids(claim.text, tag="citation")

            valid_evidence_ids = _dedup_keep_order(
                [eid for eid in [*claim.evidence_ids, *explicit_evidence_ids] if evidence_store.get(eid) is not None]
            )
            valid_citation_ids = _dedup_keep_order(
                [cid for cid in [*claim.citation_ids, *explicit_citation_ids] if citation_registry.get(cid) is not None]
            )

            invalid_explicit_evidence_ids = [eid for eid in explicit_evidence_ids if evidence_store.get(eid) is None]
            invalid_explicit_citation_ids = [cid for cid in explicit_citation_ids if citation_registry.get(cid) is None]

            for evidence_id in invalid_explicit_evidence_ids:
                issues.append(
                    ClaimValidationIssue(
                        claim_id=claim.claim_id,
                        severity="error",
                        message=f"Claim text references unknown Data ID '{evidence_id}'.",
                    )
                )
            for citation_id in invalid_explicit_citation_ids:
                issues.append(
                    ClaimValidationIssue(
                        claim_id=claim.claim_id,
                        severity="warning",
                        message=f"Claim text references unknown Citation ID '{citation_id}'.",
                    )
                )
            has_evidence = len(valid_evidence_ids) > 0
            has_citations = len(valid_citation_ids) > 0

            if not (has_evidence or has_citations):
                issues.append(
                    ClaimValidationIssue(
                        claim_id=claim.claim_id,
                        severity="error",
                        message="Each claim must bind to at least one valid data/evidence ID or citation ID.",
                    )
                )

            if claim.claim_type in {"strong", "result"} and not has_evidence:
                issues.append(
                    ClaimValidationIssue(
                        claim_id=claim.claim_id,
                        severity="error",
                        message="Strong/result claim must include valid evidence_ids.",
                    )
                )
            if claim.claim_type in {"strong", "result", "method"} and not has_citations:
                issues.append(
                    ClaimValidationIssue(
                        claim_id=claim.claim_id,
                        severity="warning",
                        message="Claim should include at least one valid citation_id.",
                    )
                )
        return issues
