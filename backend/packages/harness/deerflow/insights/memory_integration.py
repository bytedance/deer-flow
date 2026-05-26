"""Feedback-memory integration.

Feeds verified improvement signals into the agent memory system so the
lead agent can adapt behavior over time.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from deerflow.insights.cache import InsightsCache
    from deerflow.insights.models import ImprovementSuggestion

logger = logging.getLogger(__name__)


class FeedbackMemoryIntegration:
    """Integrate improvement suggestions into agent memory.

    When a suggestion is applied, creates a memory fact with:
    - source="feedback_loop"
    - category="improvement"
    - confidence=0.9
    - suggestion_id for provenance tracking
    """

    def __init__(self, cache: InsightsCache) -> None:
        self._cache = cache

    async def on_suggestion_applied(self, suggestion: ImprovementSuggestion) -> None:
        """Called when a suggestion is applied via the dashboard.

        Creates or boosts a memory fact for the improvement.
        """
        from deerflow.agents.memory.updater import create_memory_fact

        # Construct fact content from suggestion
        content = f"{suggestion.target}: {suggestion.suggestion}"

        # Check for existing fact with same content (deduplication)
        existing_fact = self._find_existing_fact(content)

        if existing_fact is not None:
            # Boost confidence of existing fact
            boosted = self._boost_confidence(existing_fact)
            logger.info(
                "Boosted existing improvement fact (id=%s, confidence=%.2f)",
                boosted.get("id"),
                boosted.get("confidence", 0),
            )
            # Update in cache
            self._update_fact_in_cache(boosted)
        else:
            # Create new fact
            fact = create_memory_fact(
                content=content,
                category="improvement",
                confidence=0.9,
                source="feedback_loop",
            )
            # Add provenance metadata
            fact["suggestion_id"] = suggestion.id
            fact["target"] = suggestion.target
            fact["issue_pattern"] = suggestion.issue_pattern

            logger.info(
                "Created improvement memory fact (id=%s, target=%s)",
                fact.get("id"),
                suggestion.target,
            )

            # Store in cache for memory system to pick up
            self._store_fact_in_cache(fact)

    def _find_existing_fact(self, content: str) -> dict[str, Any] | None:
        """Search for an existing fact with matching content (whitespace-normalized)."""
        # Normalize content for comparison
        normalized = " ".join(content.split())

        # Search in memory storage
        # This is a simplified implementation; full integration would query
        # the actual memory storage backend
        facts = self._cache.get("global", "improvement_facts") or []
        for fact in facts:
            fact_content = fact.get("content", "")
            fact_normalized = " ".join(fact_content.split())
            if fact_normalized == normalized:
                return fact

        return None

    def _boost_confidence(self, fact: dict[str, Any]) -> dict[str, Any]:
        """Boost confidence of an existing fact by 0.1 (capped at 1.0)."""
        current_confidence = fact.get("confidence", 0.5)
        new_confidence = min(current_confidence + 0.1, 1.0)

        return {
            **fact,
            "confidence": new_confidence,
            "updatedAt": datetime.now(UTC).isoformat(),
        }

    def _update_fact_in_cache(self, fact: dict[str, Any]) -> None:
        """Update an existing fact in the cache."""
        facts = self._cache.get("global", "improvement_facts") or []
        fact_id = fact.get("id")

        updated_facts = [
            fact if f.get("id") == fact_id else f
            for f in facts
        ]

        self._cache.set("global", "improvement_facts", updated_facts)

    def _store_fact_in_cache(self, fact: dict[str, Any]) -> None:
        """Store a new fact in the cache."""
        facts = self._cache.get("global", "improvement_facts") or []
        facts.append(fact)
        self._cache.set("global", "improvement_facts", facts)
