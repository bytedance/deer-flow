"""Optional phase-four library contract. New operator grants are opt-in."""

from typing import Literal

from pydantic import Field, field_validator, model_validator

from .contracts import Model, ProcessingResult

LIBRARY_OPERATIONS = frozenset({"documents", "entries", "entry", "revisions", "revision", "entry_edit", "entry_restore", "graph"})


def entry_key(value: str) -> str:
    if not value or len(value) > 255 or any(c in value for c in "%?#\\") or any(ord(c) < 32 or ord(c) == 127 for c in value) or any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError("Invalid entry key")
    return value


class LibraryQuery(Model):
    page: int = Field(default=1, ge=1, le=10000, strict=True)
    page_size: int = Field(default=20, ge=1, le=50, strict=True)
    search: str = Field(default="", max_length=500)
    state: Literal["", "pending", "unprocessed", "processing", "parsing", "finalizing", "completed", "failed", "cancelled"] = ""
    entry: str | None = None
    version: int | None = Field(default=None, ge=1, strict=True)

    @field_validator("entry")
    @classmethod
    def key(cls, value):
        return entry_key(value) if value is not None else None


class EditEntry(Model):
    entry: str
    expected_version: int = Field(ge=1, strict=True)
    title: str = Field(min_length=1, max_length=500)
    content: str = Field(max_length=500_000)

    _key = field_validator("entry")(entry_key)

    @field_validator("title")
    @classmethod
    def title_present(cls, value):
        if not value.strip():
            raise ValueError("Title is required")
        return value


class RestoreEntry(Model):
    entry: str
    expected_version: int = Field(ge=1, strict=True)
    version: int = Field(ge=1, strict=True)

    _key = field_validator("entry")(entry_key)


class Entry(Model):
    key: str
    title: str = Field(max_length=500)
    content: str = Field(default="", max_length=500_000)
    summary: str = Field(default="", max_length=10000)
    version: int = Field(ge=1, strict=True)
    status: str = Field(max_length=32)

    _key = field_validator("key")(entry_key)


class Document(Model):
    title: str = Field(max_length=500)
    processing: ProcessingResult


class Revision(Model):
    version: int = Field(ge=1, strict=True)
    editor: str = Field(default="", max_length=256)
    source: str = Field(default="", max_length=64)
    edited_at: str = Field(default="", max_length=64)


class Entity(Model):
    id: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=10000)


class Evidence(Model):
    id: str = Field(min_length=1, max_length=500)
    content: str = Field(max_length=100_000)


class Relation(Model):
    source: str = Field(min_length=1, max_length=500)
    target: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=10000)
    evidence_ids: tuple[str, ...] = Field(default=(), max_length=100)


class Graph(Model):
    entities: tuple[Entity, ...] = Field(default=(), max_length=200)
    relations: tuple[Relation, ...] = Field(default=(), max_length=100)
    evidence: tuple[Evidence, ...] = Field(default=(), max_length=100)
    # Retrieval is always a bounded projection, never a full graph census.
    bounded: Literal[True] = True

    @model_validator(mode="after")
    def identities(self):
        nodes, chunks = {item.id for item in self.entities}, {item.id for item in self.evidence}
        if len(nodes) != len(self.entities) or len(chunks) != len(self.evidence):
            raise ValueError("Ambiguous graph identity")
        if any(edge.source not in nodes or edge.target not in nodes or not set(edge.evidence_ids) <= chunks for edge in self.relations):
            raise ValueError("Unresolved graph identity")
        return self


class LibraryResult(Model):
    version: Literal[1] = 1
    provider: str
    connection_id: str
    dataset_id: str
    title: str = Field(default="", max_length=500)
    documents: tuple[Document, ...] = Field(default=(), max_length=50)
    entries: tuple[Entry, ...] = Field(default=(), max_length=50)
    revisions: tuple[Revision, ...] = Field(default=(), max_length=50)
    entry: Entry | None = None
    total: int = Field(default=0, ge=0, strict=True)
    page: int = Field(default=1, ge=1, strict=True)
    page_size: int = Field(default=20, ge=1, le=50, strict=True)
    graph: Graph | None = None
