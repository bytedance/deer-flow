"""Versioned per-message knowledge-retrieval scope contract.

The message snapshot may contain an untrusted display block for historical
UI rendering. Runtime consumers must use execution_scope, which projects only
the fields that can constrain retrieval.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

KNOWLEDGE_SCOPE_KEY = "knowledge_scope"
KNOWLEDGE_SCOPE_RUNTIME_KEY = "__knowledge_scope_execution"
KNOWLEDGE_SCOPE_VERSION = 1
MAX_KNOWLEDGE_SCOPE_BYTES = 64 * 1024
MAX_DATASET_IDS = 100
MAX_DOCUMENT_IDS = 1000
MAX_DISPLAY_DATASETS = 20
MAX_DISPLAY_DOCUMENTS = 50
MAX_ID_CODEPOINTS = 256
MAX_DISPLAY_NAME_CODEPOINTS = 256


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _clean_id(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("knowledge scope IDs must be strings")
    cleaned = value.strip()
    if not cleaned or len(cleaned) > MAX_ID_CODEPOINTS:
        raise ValueError(f"knowledge scope IDs must contain between 1 and {MAX_ID_CODEPOINTS} characters")
    return cleaned


def _stable_unique_ids(values: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = _clean_id(value)
        if cleaned not in seen:
            normalized.append(cleaned)
            seen.add(cleaned)
    return normalized


class KnowledgeDocumentFilter(_StrictModel):
    dataset_id: str
    document_ids: list[str] = Field(min_length=1, max_length=MAX_DOCUMENT_IDS)

    @model_validator(mode="after")
    def _normalize(self) -> KnowledgeDocumentFilter:
        object.__setattr__(self, "dataset_id", _clean_id(self.dataset_id))
        object.__setattr__(self, "document_ids", _stable_unique_ids(self.document_ids))
        return self


class KnowledgeDisplayDocument(_StrictModel):
    id: str
    name: str = Field(min_length=1, max_length=MAX_DISPLAY_NAME_CODEPOINTS)

    @model_validator(mode="after")
    def _normalize(self) -> KnowledgeDisplayDocument:
        object.__setattr__(self, "id", _clean_id(self.id))
        if not self.name.strip():
            raise ValueError("display names must not be blank")
        return self


class KnowledgeDisplayDataset(_StrictModel):
    id: str
    name: str = Field(min_length=1, max_length=MAX_DISPLAY_NAME_CODEPOINTS)
    documents: list[KnowledgeDisplayDocument] | None = Field(default=None, max_length=MAX_DISPLAY_DOCUMENTS)

    @model_validator(mode="after")
    def _normalize(self) -> KnowledgeDisplayDataset:
        object.__setattr__(self, "id", _clean_id(self.id))
        if not self.name.strip():
            raise ValueError("display names must not be blank")
        if self.documents is not None:
            document_ids = [item.id for item in self.documents]
            if len(document_ids) != len(set(document_ids)):
                raise ValueError("display document IDs must not be duplicated")
        return self


class KnowledgeScopeDisplay(_StrictModel):
    datasets: list[KnowledgeDisplayDataset] = Field(max_length=MAX_DISPLAY_DATASETS)


class KnowledgeScope(_StrictModel):
    """Canonical message snapshot for one user turn."""

    version: Literal[1]
    mode: Literal["all", "selected", "disabled"]
    dataset_ids: list[str] | None = Field(default=None, max_length=MAX_DATASET_IDS)
    document_filters: list[KnowledgeDocumentFilter] | None = Field(default=None, max_length=MAX_DATASET_IDS)
    display: KnowledgeScopeDisplay | None = None

    @model_validator(mode="after")
    def _validate_and_normalize(self) -> KnowledgeScope:
        dataset_ids = _stable_unique_ids(self.dataset_ids or [])
        filters = self.document_filters or []

        if self.mode in {"all", "disabled"}:
            if dataset_ids or filters or self.display is not None:
                raise ValueError(f"{self.mode} knowledge scope must not contain selections or display")
            object.__setattr__(self, "dataset_ids", None)
            object.__setattr__(self, "document_filters", None)
            return self._validate_size()

        if not dataset_ids:
            raise ValueError("selected knowledge scope requires at least one dataset ID")
        object.__setattr__(self, "dataset_ids", dataset_ids)

        allowed_datasets = set(dataset_ids)
        filter_ids = [item.dataset_id for item in filters]
        if len(filter_ids) != len(set(filter_ids)):
            raise ValueError("each dataset may have at most one document filter")
        if any(dataset_id not in allowed_datasets for dataset_id in filter_ids):
            raise ValueError("document filters must belong to selected datasets")
        if sum(len(item.document_ids) for item in filters) > MAX_DOCUMENT_IDS:
            raise ValueError(f"knowledge scope may contain at most {MAX_DOCUMENT_IDS} document IDs")
        object.__setattr__(self, "document_filters", filters or None)

        if self.display is not None:
            display_dataset_ids = [item.id for item in self.display.datasets]
            if len(display_dataset_ids) != len(set(display_dataset_ids)):
                raise ValueError("display dataset IDs must not be duplicated")
            if any(dataset_id not in allowed_datasets for dataset_id in display_dataset_ids):
                raise ValueError("display datasets must belong to selected datasets")
            filters_by_dataset = {item.dataset_id: set(item.document_ids) for item in filters}
            display_document_count = 0
            for dataset in self.display.datasets:
                documents = dataset.documents or []
                display_document_count += len(documents)
                allowed_documents = filters_by_dataset.get(dataset.id)
                if documents and allowed_documents is None:
                    raise ValueError("display documents require an explicit document filter")
                if allowed_documents is not None and any(document.id not in allowed_documents for document in documents):
                    raise ValueError("display documents must belong to the corresponding document filter")
            if display_document_count > MAX_DISPLAY_DOCUMENTS:
                raise ValueError(f"display may contain at most {MAX_DISPLAY_DOCUMENTS} document names")

        return self._validate_size()

    def _canonical_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"version": self.version, "mode": self.mode}
        if self.mode == "selected":
            payload["dataset_ids"] = list(self.dataset_ids or [])
            if self.document_filters:
                payload["document_filters"] = [item.model_dump() for item in self.document_filters]
            if self.display is not None:
                payload["display"] = self.display.model_dump(exclude_none=True)
        return payload

    def _validate_size(self) -> KnowledgeScope:
        raw = json.dumps(
            self._canonical_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(raw) > MAX_KNOWLEDGE_SCOPE_BYTES:
            raise ValueError(f"knowledge scope must not exceed {MAX_KNOWLEDGE_SCOPE_BYTES} UTF-8 JSON bytes")
        return self


def canonicalize_knowledge_scope(value: object) -> dict[str, Any]:
    """Validate and return the stable JSON-safe message representation."""
    scope = value if isinstance(value, KnowledgeScope) else KnowledgeScope.model_validate(value)
    return scope._canonical_dict()


def execution_scope(value: object) -> dict[str, Any]:
    """Return only the execution fields, excluding the untrusted display block."""
    canonical = canonicalize_knowledge_scope(value)
    canonical.pop("display", None)
    return canonical


def strip_message_knowledge_scope(message: Any) -> Any:
    """Copy a LangChain message without its knowledge-scope snapshot."""
    additional_kwargs = getattr(message, "additional_kwargs", None)
    if not isinstance(additional_kwargs, dict) or KNOWLEDGE_SCOPE_KEY not in additional_kwargs:
        return message
    cleaned = dict(additional_kwargs)
    cleaned.pop(KNOWLEDGE_SCOPE_KEY, None)
    return message.model_copy(update={"additional_kwargs": cleaned})
