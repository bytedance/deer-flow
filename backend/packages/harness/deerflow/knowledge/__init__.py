"""Read-only knowledge contracts with optional catalog and filter capabilities."""

from .contract import (
    KnowledgeCapabilities,
    KnowledgeRequestContext,
    KnowledgeSource,
    RetrievalCatalogItem,
    RetrievalCatalogPage,
    RetrievalCatalogProvider,
    RetrievalDocumentsProvider,
    RetrievalHit,
    RetrievalProvider,
    RetrievalResult,
    ScopedRetrievalProvider,
)
from .sources import format_result, sources_from_messages

__all__ = [
    "KnowledgeCapabilities",
    "KnowledgeRequestContext",
    "KnowledgeSource",
    "RetrievalCatalogItem",
    "RetrievalCatalogPage",
    "RetrievalCatalogProvider",
    "RetrievalDocumentsProvider",
    "RetrievalHit",
    "RetrievalProvider",
    "RetrievalResult",
    "ScopedRetrievalProvider",
    "format_result",
    "sources_from_messages",
]
