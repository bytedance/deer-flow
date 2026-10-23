"""Version 1 management boundary, owned by the optional extension.

No client identity, credentials, arbitrary upstream JSON, or local task store.
Providers own execution and resource authorization; submission is not completion.
"""

from dataclasses import dataclass
from typing import Literal, Protocol

from deerflow_extension_api.auth import ExtensionPrincipal
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

Operation = Literal["capabilities", "status", "upload", "url", "manual", "reprocess", "cancel"]


class ManagementCredentialUnavailable(RuntimeError):
    """Local credential validation failed before an upstream request."""


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


@dataclass(frozen=True)
class ManagementContext:
    principal: ExtensionPrincipal
    # HTTP management does not claim an executing Agent or a platform space.
    # Future delegates must be supplied by a trusted host, never request JSON.


class ProcessingOptions(Model):
    chunk_size: int | None = Field(default=None, ge=64, le=8192, strict=True)
    chunk_overlap: int | None = Field(default=None, ge=0, le=4096, strict=True)
    summary_enabled: bool | None = Field(default=None, strict=True)
    graph_enabled: bool | None = Field(default=None, strict=True)

    @model_validator(mode="after")
    def chunks(self):
        if (self.chunk_size is None) != (self.chunk_overlap is None):
            raise ValueError("chunk_size and chunk_overlap must be supplied together")
        if self.chunk_size is not None and self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        return self


class IngestRequest(Model):
    kind: Literal["url", "manual"]
    title: str = Field(default="", max_length=500)
    content: str | None = Field(default=None, min_length=1, max_length=1_000_000)
    url: HttpUrl | None = None
    processing: ProcessingOptions = Field(default_factory=ProcessingOptions)

    @model_validator(mode="after")
    def payload(self):
        if self.kind == "manual":
            if not self.title.strip() or self.content is None or not self.content.strip() or self.url is not None:
                raise ValueError("manual ingestion requires title/content and no URL")
        elif self.url is None or self.content is not None:
            raise ValueError("URL ingestion requires URL and no content")
        if self.url is not None and (self.url.username or self.url.password or self.url.fragment):
            raise ValueError("URL must not contain credentials or a fragment")
        return self


class ProcessingResult(Model):
    version: Literal[1] = 1
    provider: str
    connection_id: str
    dataset_id: str
    document_id: str
    state: Literal["queued", "running", "completed", "failed", "cancelled", "unknown"]
    provider_state: str
    searchable: bool
    # Deliberately no made-up per-stage completion, percent, or synthetic task ID.


class Capabilities(Model):
    version: Literal[1] = 1
    operations: frozenset[Operation]
    processing_options: frozenset[str]
    pipeline: dict[str, Literal["provider_managed", "unsupported"]]


class ManagementProvider(Protocol):
    async def capabilities(self, context: ManagementContext, connection: str, base: str) -> Capabilities:
        raise NotImplementedError

    async def ingest(self, context: ManagementContext, connection: str, base: str, body: IngestRequest) -> ProcessingResult:
        raise NotImplementedError

    async def upload(self, context: ManagementContext, connection: str, base: str, filename: str, content: bytes, options: ProcessingOptions) -> ProcessingResult:
        raise NotImplementedError

    async def status(self, context: ManagementContext, connection: str, base: str, document: str) -> ProcessingResult:
        raise NotImplementedError

    async def process(self, context: ManagementContext, connection: str, base: str, document: str, action: Literal["reprocess", "cancel"], options: ProcessingOptions) -> ProcessingResult:
        raise NotImplementedError
