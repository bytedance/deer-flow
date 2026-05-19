"""Typed RAG errors.

Why a dedicated module: the RAG path silently swallowed every failure
through generic ``Exception`` handlers, so an embedding misconfig and
a missing collection produced identical user-facing "no results" — and
operators couldn't tell from logs which one they were diagnosing. The
three classes here are the *minimum* taxonomy needed to route a
failure to the right human:

* ``KbResolutionError`` — KB ID not visible / not active for this user
  (auth + visibility + tenant). Resolution: check selection + grants.
* ``EmbeddingDimensionMismatchError`` — vector dim of query embedding
  doesn't match the dim the collection was built with. Resolution:
  reindex KB.
* ``VectorStoreError`` — backend (Chroma / pgvector) refused the call
  or returned malformed data. Resolution: check backend health + logs.

Callers should raise the most specific error they can. Catch sites
(middleware, tool wrappers) translate these into structured decision
events / API responses.
"""

from __future__ import annotations


class RagError(Exception):
    """Base for typed RAG failures."""


class KbResolutionError(RagError):
    """The requested KB is not accessible to the current principal."""


class EmbeddingDimensionMismatchError(RagError):
    """Query/document embedding dim disagrees with the target collection."""

    def __init__(self, *, expected: int, actual: int, collection: str | None = None) -> None:
        self.expected = expected
        self.actual = actual
        self.collection = collection
        super().__init__(
            f"embedding dim mismatch: expected={expected} actual={actual}"
            + (f" collection={collection}" if collection else "")
        )


class VectorStoreError(RagError):
    """The vector backend rejected the request or returned an error."""
