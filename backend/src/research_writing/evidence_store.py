"""Evidence store for cross-modal research-writing provenance."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

EvidenceUnitType = Literal[
    "paper_passage",
    "image_report",
    "raw_data",
    "web_source",
    "manual_note",
]


class EvidenceUnit(BaseModel):
    """Atomic evidence unit used to support claims."""

    evidence_id: str
    evidence_type: EvidenceUnitType
    summary: str
    source_ref: str
    quote: str | None = None
    location: dict[str, Any] = Field(default_factory=dict)
    citation_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class _EvidencePayload(BaseModel):
    items: dict[str, EvidenceUnit] = Field(default_factory=dict)


class EvidenceStore:
    """File-backed evidence storage."""

    def __init__(self, storage_path: Path):
        self.storage_path = storage_path
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> _EvidencePayload:
        if not self.storage_path.exists():
            return _EvidencePayload()
        data = json.loads(self.storage_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return _EvidencePayload()
        return _EvidencePayload.model_validate(data)

    def _save(self, payload: _EvidencePayload) -> None:
        self.storage_path.write_text(payload.model_dump_json(indent=2), encoding="utf-8")

    def upsert(self, evidence: EvidenceUnit) -> EvidenceUnit:
        payload = self._load()
        payload.items[evidence.evidence_id] = evidence
        self._save(payload)
        return evidence

    def get(self, evidence_id: str) -> EvidenceUnit | None:
        return self._load().items.get(evidence_id)

    def list(self) -> list[EvidenceUnit]:
        return list(self._load().items.values())

    def list_by_type(self, evidence_type: EvidenceUnitType) -> list[EvidenceUnit]:
        return [item for item in self.list() if item.evidence_type == evidence_type]
