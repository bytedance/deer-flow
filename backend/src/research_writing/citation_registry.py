"""Citation registry for verifiable source tracking."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class CitationRecord(BaseModel):
    """Normalized citation metadata entry."""

    citation_id: str
    doi: str | None = None
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    source: str = "unknown"
    verified: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class _CitationPayload(BaseModel):
    items: dict[str, CitationRecord] = Field(default_factory=dict)


class CitationRegistry:
    """File-backed citation registry."""

    def __init__(self, storage_path: Path):
        self.storage_path = storage_path
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> _CitationPayload:
        if not self.storage_path.exists():
            return _CitationPayload()
        data = json.loads(self.storage_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return _CitationPayload()
        return _CitationPayload.model_validate(data)

    def _save(self, payload: _CitationPayload) -> None:
        self.storage_path.write_text(payload.model_dump_json(indent=2), encoding="utf-8")

    def upsert(self, record: CitationRecord) -> CitationRecord:
        payload = self._load()
        payload.items[record.citation_id] = record
        self._save(payload)
        return record

    def get(self, citation_id: str) -> CitationRecord | None:
        return self._load().items.get(citation_id)

    def list(self) -> list[CitationRecord]:
        return list(self._load().items.values())

    def mark_verified(self, citation_id: str, *, metadata: dict[str, Any] | None = None) -> CitationRecord:
        payload = self._load()
        record = payload.items.get(citation_id)
        if record is None:
            raise ValueError(f"Citation '{citation_id}' not found")
        record.verified = True
        if metadata:
            record.metadata = {**record.metadata, **metadata}
        payload.items[citation_id] = record
        self._save(payload)
        return record
