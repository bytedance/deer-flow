"""Provider-neutral retrieval evidence and operation-level capabilities."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, computed_field, field_validator


class KnowledgeCapabilities(BaseModel):
    """An operation is supported only when explicitly advertised.

    Search-only providers need no catalog, scope, or management implementation.
    """

    operations: frozenset[Literal["search", "sources", "catalog", "documents", "dataset_filter", "document_filter"]] = frozenset({"search"})

    model_config = ConfigDict(frozen=True)

    def supports(self, operation: str) -> bool:
        return operation in self.operations


class KnowledgeSource(BaseModel):
    """One attributable excerpt actually returned by a retrieval tool.

    Titles and optional locators are provider evidence, never inferred links,
    page numbers, or local reference ordinals. IDs expose no provider internals.
    """

    model_config = ConfigDict(frozen=True, extra="ignore", str_strip_whitespace=True)

    provider: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=500)
    excerpt: str = Field(min_length=1, max_length=100_000)
    dataset_name: str | None = Field(default=None, max_length=500)
    url: HttpUrl | None = None
    page: int | None = Field(default=None, gt=0, le=9_007_199_254_740_991, strict=True)

    @field_validator("url")
    @classmethod
    def reject_credentials(cls, value: HttpUrl | None) -> HttpUrl | None:
        if value is not None and (value.username is not None or value.password is not None):
            raise ValueError("source URL must not contain credentials")
        return value

    @computed_field
    @property
    def id(self) -> str:
        identity = [self.provider, self.title, self.excerpt, self.dataset_name, str(self.url) if self.url else None, self.page]
        return hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode("utf-8")).hexdigest()[:32]


class RetrievalHit(BaseModel):
    content: str
    source: KnowledgeSource | None = None
    score: float | None = Field(default=None, allow_inf_nan=False)


class RetrievalResult(BaseModel):
    hits: list[RetrievalHit] = Field(default_factory=list)


class RetrievalProvider(Protocol):
    capabilities: KnowledgeCapabilities

    async def search(self, query: str) -> RetrievalResult: ...


@dataclass(frozen=True)
class KnowledgeRequestContext:
    """Host identity and execution constraints, never provider authorization.

    Providers must enforce their own permissions on every operation. ``scope``
    is a fresh execution-only snapshot; display labels never reach providers.
    No tenant or credential is inferred from caller-supplied metadata.
    ``agent_name`` identifies the current executor: the selected assistant
    (``lead_agent`` by default), or the executing subagent's configured name.
    It is not the parent assistant name. Direct provider callers may omit it.
    """

    user_id: str
    agent_name: str | None = None
    scope: dict[str, Any] | None = None


class RetrievalCatalogItem(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(min_length=1, max_length=256)
    name: str = Field(min_length=1, max_length=500)
    selectable: bool = False


class RetrievalCatalogPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[RetrievalCatalogItem] = Field(default_factory=list, max_length=100)
    page: int = Field(ge=1, strict=True)
    page_size: int = Field(ge=1, le=100, strict=True)
    total: int = Field(ge=0, strict=True)


class ScopedRetrievalProvider(Protocol):
    """Optional contextual search; required for either filter capability.

    A missing/inaccessible selection must fail as a whole. Never retry a
    constrained request as an unconstrained search. Context is also supplied
    for all-scope searches when this method is implemented.
    """

    async def search_scoped(self, query: str, *, context: KnowledgeRequestContext) -> RetrievalResult: ...


class RetrievalCatalogProvider(Protocol):
    async def catalog(self, *, context: KnowledgeRequestContext, page: int, page_size: int, search: str) -> RetrievalCatalogPage: ...


class RetrievalDocumentsProvider(Protocol):
    async def documents(self, dataset_id: str, *, context: KnowledgeRequestContext, page: int, page_size: int, search: str) -> RetrievalCatalogPage: ...
