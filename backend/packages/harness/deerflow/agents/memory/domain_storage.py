"""Domain memory storage with vector-based semantic search.

Stores domain-specific facts (equipment, processes, systems) scoped to
(tenant_id, domain, entity_id) with cross-thread retrieval via vector similarity.
"""

import logging
import math
import re
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from deerflow.rag.embeddings import get_embedding_provider
from deerflow.rag.vector_store import VectorStore, get_vector_store

logger = logging.getLogger(__name__)


class DecayPolicy(str, Enum):
    """Decay policy for domain fact aging."""

    NEVER = "never"
    LINEAR = "linear"
    EXPONENTIAL = "exponential"


def apply_decay(
    facts: list["DomainFact"],
    policy: DecayPolicy,
    half_life_days: float,
) -> list["DomainFact"]:
    """Apply decay to facts based on age.

    Args:
        facts: List of DomainFact objects (mutated in place).
        policy: Decay policy to apply.
        half_life_days: Half-life in days for decay calculation.

    Returns:
        Facts sorted by adjusted_score descending.
    """
    now = datetime.now(UTC)
    for fact in facts:
        if fact.created_at is None:
            fact.adjusted_score = fact.similarity_score
            continue

        age_days = (now - fact.created_at).total_seconds() / 86400

        if policy == DecayPolicy.NEVER:
            decay_factor = 1.0
        elif policy == DecayPolicy.LINEAR:
            decay_factor = max(0.0, 1.0 - age_days / (2.0 * half_life_days))
        elif policy == DecayPolicy.EXPONENTIAL:
            decay_factor = math.exp(-0.693 * age_days / half_life_days)
        else:
            decay_factor = 1.0

        fact.adjusted_score = fact.similarity_score * decay_factor

    return sorted(facts, key=lambda f: f.adjusted_score, reverse=True)


def normalize_entity_id(entity_name: str) -> str:
    """Normalize entity name for consistent lookup.

    Lowercase, replace non-alphanumeric with underscores, strip edges.
    Examples:
        "Pump A" -> "pump_a"
        "Reactor #1" -> "reactor_1"
        "Main Feed Pump" -> "main_feed_pump"
    """
    normalized = entity_name.strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized)
    return normalized.strip("_")


@dataclass
class DomainFact:
    """A domain-specific fact with metadata."""

    id: str
    content: str
    domain: str
    entity_id: str
    tenant_id: str
    confidence: float = 1.0
    created_at: datetime | None = None
    metadata: dict[str, Any] | None = None
    # Set during search with decay
    similarity_score: float = 0.0
    adjusted_score: float = 0.0


class DomainStorage:
    """Vector-based storage for domain-scoped facts.

    Uses the same VectorStore backend as RAG (ChromaDB or pgvector).
    Each tenant gets a separate collection: `domain_{tenant_id}`.
    """

    def __init__(self, vector_store: VectorStore | None = None, embedding_provider=None):
        """Initialize with optional injected dependencies."""
        self._vector_store = vector_store
        self._embedding_provider = embedding_provider

    def _get_vector_store(self) -> VectorStore:
        if self._vector_store is None:
            self._vector_store = get_vector_store()
        return self._vector_store

    def _get_embedding_provider(self):
        if self._embedding_provider is None:
            self._embedding_provider = get_embedding_provider()
        return self._embedding_provider

    def _collection_name(self, tenant_id: str) -> str:
        """Return collection name for tenant isolation."""
        return f"domain_{tenant_id}"

    def store_fact(
        self,
        tenant_id: str,
        domain: str,
        entity_id: str,
        content: str,
        metadata: dict[str, Any] | None = None,
        confidence: float = 1.0,
    ) -> str | None:
        """Store a domain fact with embedding.

        Args:
            tenant_id: Tenant identifier.
            domain: Domain category (e.g., "equipment", "process").
            entity_id: Entity identifier (will be normalized).
            content: Fact text content.
            metadata: Optional additional metadata.
            confidence: Confidence score (0.0-1.0).

        Returns:
            Fact ID if successful, None otherwise.
        """
        normalized_entity = normalize_entity_id(entity_id)
        fact_id = str(uuid.uuid4())
        now = datetime.now(UTC)

        chunk_metadata = {
            "domain": domain,
            "entity_id": normalized_entity,
            "tenant_id": tenant_id,
            "confidence": confidence,
            "created_at": now.isoformat(),
        }
        if metadata:
            chunk_metadata.update(metadata)

        chunk = {
            "id": fact_id,
            "content": content,
            "metadata": chunk_metadata,
        }

        try:
            start = time.monotonic()
            provider = self._get_embedding_provider()
            embeddings = provider.embed([content])
            store = self._get_vector_store()
            collection = self._collection_name(tenant_id)
            store.add(collection, [chunk], embeddings)
            latency_ms = (time.monotonic() - start) * 1000
            logger.info(
                "Domain memory saved: tenant=%s domain=%s entity=%s latency=%.1fms",
                tenant_id,
                domain,
                normalized_entity,
                latency_ms,
            )
            return fact_id
        except Exception:
            logger.error("Failed to store domain fact", exc_info=True)
            return None

    def search_facts(
        self,
        tenant_id: str,
        query: str,
        domain: str | None = None,
        entity_id: str | None = None,
        top_k: int = 20,
        min_score: float = 0.0,
    ) -> list[DomainFact]:
        """Search for domain facts by semantic similarity.

        Args:
            tenant_id: Tenant identifier.
            query: Search query text.
            domain: Optional domain filter.
            entity_id: Optional entity filter (will be normalized).
            top_k: Maximum number of results.
            min_score: Minimum similarity score threshold.

        Returns:
            List of DomainFact objects sorted by similarity score.
        """
        try:
            provider = self._get_embedding_provider()
            query_embedding = provider.embed_query(query)
            store = self._get_vector_store()
            collection = self._collection_name(tenant_id)

            # Build metadata filter
            where_filter: dict[str, Any] = {}
            if domain:
                where_filter["domain"] = domain
            if entity_id:
                where_filter["entity_id"] = normalize_entity_id(entity_id)

            results = store.search(
                collection,
                query_embedding,
                top_k=top_k,
                score_threshold=min_score,
            )

            facts: list[DomainFact] = []
            for result in results:
                meta = result.metadata or {}
                # Apply metadata filters (vector store may not support all filters)
                if domain and meta.get("domain") != domain:
                    continue
                if entity_id and meta.get("entity_id") != normalize_entity_id(entity_id):
                    continue

                created_at_str = meta.get("created_at")
                created_at = None
                if created_at_str:
                    try:
                        created_at = datetime.fromisoformat(created_at_str)
                    except (ValueError, TypeError):
                        pass

                fact = DomainFact(
                    id=result.chunk_id,
                    content=result.content,
                    domain=meta.get("domain", ""),
                    entity_id=meta.get("entity_id", ""),
                    tenant_id=tenant_id,
                    confidence=meta.get("confidence", 1.0),
                    created_at=created_at,
                    metadata=meta,
                    similarity_score=result.score,
                    adjusted_score=result.score,
                )
                facts.append(fact)

            return facts

        except Exception:
            logger.error("Failed to search domain facts", exc_info=True)
            return []


# Global singleton
_domain_storage_instance: DomainStorage | None = None
_domain_storage_lock = threading.Lock()


def get_domain_storage() -> DomainStorage | None:
    """Get the global domain storage singleton.

    Returns None if vector store is not available.
    """
    global _domain_storage_instance

    if _domain_storage_instance is not None:
        return _domain_storage_instance

    with _domain_storage_lock:
        if _domain_storage_instance is not None:
            return _domain_storage_instance

        try:
            _domain_storage_instance = DomainStorage()
            return _domain_storage_instance
        except Exception as e:
            logger.warning("Failed to create DomainStorage: %s", e)
            return None


def set_domain_storage(storage: DomainStorage | None) -> None:
    """Replace the domain storage singleton (for testing)."""
    global _domain_storage_instance
    with _domain_storage_lock:
        _domain_storage_instance = storage
