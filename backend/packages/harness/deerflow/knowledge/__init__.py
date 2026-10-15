"""Read-only knowledge contracts; no catalog or management dependency."""

from .contract import KnowledgeCapabilities, KnowledgeSource, RetrievalHit, RetrievalProvider, RetrievalResult
from .sources import format_result, sources_from_messages

__all__ = ["KnowledgeCapabilities", "KnowledgeSource", "RetrievalHit", "RetrievalProvider", "RetrievalResult", "format_result", "sources_from_messages"]
